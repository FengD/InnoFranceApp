from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from ..config import load_app_config
from ..mcp_clients import MCPToolClient
from ..pipeline import (
    _parse_speaker_configs,
    _detect_speaker_configs,
    _group_segments_by_speaker,
    _select_speaker_clips,
    _extract_speaker_tags,
    _build_speaker_clip_candidates,
    _speaker_sort_key,
    _extract_audio_clip,
)
from ..speaker_profiles import build_speaker_configs
from ..text_utils import normalize_translation_text, parse_speaker_lines
from ..s3 import S3Client
from .queue import PipelineQueue
from .schemas import (
    PipelineJobResponse,
    PipelineListResponse,
    PipelineStartRequest,
    JobMetaUpdateRequest,
    QueueReorderRequest,
    SpeakersSubmitRequest,
    SettingsResponse,
    SettingsUpdate,
    StepEvent,
    SummaryUpdateRequest,
    TranslationUpdateRequest,
)


def create_app(config_path: Optional[Path] = None) -> FastAPI:
    app = FastAPI(
        title="InnoFrance Pipeline API",
        description="API for running and monitoring YouTube-to-Chinese summary/audio pipelines.",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    config = load_app_config(config_path)
    s3_client = S3Client(config.settings)
    queue = PipelineQueue(
        parallel_enabled=False,
        max_concurrent=1,
        state_path=config.runs_dir / "pipeline_state.json",
        s3_client=s3_client,
        runs_dir=config.runs_dir,
    )

    def _allowed_path(relative_path: str) -> Path:
        if not relative_path or ".." in relative_path or relative_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid path")
        rel = relative_path.strip("/")
        if not rel:
            raise HTTPException(status_code=400, detail="Invalid path")
        for base in (config.output_dir, config.runs_dir):
            full = (base / rel).resolve()
            try:
                if full.exists() and full.is_file() and full.is_relative_to(base.resolve()):
                    return full
            except ValueError:
                continue
        raise HTTPException(status_code=404, detail="File not found")

    def _get_job_or_404(job_id: str):
        job = queue.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    def _relative_to_output(path: Path) -> str:
        out_dir = config.runs_dir.resolve()
        try:
            if path.resolve().is_relative_to(out_dir):
                return str(path.resolve().relative_to(out_dir))
        except ValueError:
            pass
        return path.name

    def _assets_root() -> Path:
        return config.settings.project_root / "InnoFranceApp" / "assets"

    def _asset_custom_dir(asset_type: str) -> Path:
        return _assets_root() / "custom" / asset_type

    def _default_asset_filename(asset_type: str) -> str:
        return "start_music.wav" if asset_type == "start_music" else "beginning.wav"

    def _asset_selection_for_type(asset_type: str) -> Optional[str]:
        return queue.asset_selections.get(asset_type)

    def _resolve_asset_for_type(asset_type: str) -> Path:
        selection = _asset_selection_for_type(asset_type)
        if selection and selection.startswith("custom:"):
            filename = selection.split(":", 1)[1]
            candidate = _asset_custom_dir(asset_type) / filename
            if candidate.exists():
                return candidate
        default_name = _default_asset_filename(asset_type)
        assets_dir = _assets_root()
        candidate = assets_dir / default_name
        if candidate.exists():
            return candidate
        fallback = config.settings.project_root / "InnoFrance" / default_name
        if fallback.exists():
            return fallback
        raise HTTPException(status_code=404, detail=f"Asset not found: {default_name}")

    def _list_asset_options(asset_type: str) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        default_name = _default_asset_filename(asset_type)
        try:
            _resolve_asset_for_type(asset_type)
            options.append(
                {
                    "id": "default",
                    "label": f"Default ({default_name})",
                }
            )
        except HTTPException:
            pass
        custom_dir = _asset_custom_dir(asset_type)
        if custom_dir.exists():
            for path in sorted(custom_dir.glob("*.wav")):
                options.append({"id": f"custom:{path.name}", "label": path.name})
        return options

    def _safe_asset_filename(filename: str) -> str:
        name = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(filename).name)
        name = name.strip("._")
        return name or f"asset_{uuid.uuid4().hex}.wav"

    def _provider_key_env(provider: str) -> Optional[str]:
        mapping = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "qwen": "DASHSCOPE_API_KEY",
            "glm": "ZHIPUAI_API_KEY",
            "vllm": "VLLM_API_KEY",
            "sglang": "SGLANG_API_KEY",
        }
        return mapping.get(provider)

    def _provider_key_source(provider: str) -> str:
        if provider in {"ollama", "vllm", "sglang"}:
            return "local"
        if queue.get_api_key(provider):
            return "setting"
        env_name = _provider_key_env(provider)
        if env_name and os.getenv(env_name):
            return "env"
        return "none"

    def _provider_available(provider: str) -> bool:
        return _provider_key_source(provider) != "none"

    def _sanitize_export_name(value: str) -> str:
        cleaned = value.strip().lower()
        cleaned = re.sub(r"\s+", "_", cleaned)
        cleaned = re.sub(r"[^a-z0-9_-]", "_", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned or "pipeline_export"

    def _collect_export_paths(job) -> list[Path]:
        paths: list[Path] = []
        if not job.result:
            return paths
        for key in (
            "summary_path",
            "translated_path",
            "transcript_path",
            "speakers_path",
            "audio_path",
            "summary_audio_path",
            "merged_audio_path",
            "input_audio_path",
        ):
            value = job.result.get(key)
            if isinstance(value, str) and value:
                path = Path(value)
                if path.exists() and path.is_file():
                    paths.append(path)
        for value in job.result.get("speaker_audio_paths", []) or []:
            if isinstance(value, str) and value:
                path = Path(value)
                if path.exists() and path.is_file():
                    paths.append(path)
        return paths

    def _build_export_zip(job) -> Path:
        if not job.result or not job.result.get("run_dir"):
            raise HTTPException(status_code=400, detail="Run directory not available")
        run_dir = Path(job.result["run_dir"])
        export_path = run_dir / "pipeline_export.zip"
        paths = _collect_export_paths(job)
        if not paths:
            raise HTTPException(status_code=400, detail="No artifacts available for export")
        metadata = {
            "job_id": job.job_id,
            "created_at": job.created_at.isoformat() + "Z",
            "custom_name": job.custom_name,
            "note": job.note,
            "tags": job.tags,
            "published": job.published,
        }
        with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                try:
                    rel = path.resolve().relative_to(run_dir.resolve())
                    arcname = str(rel)
                except ValueError:
                    arcname = path.name
                zf.write(path, arcname=arcname)
            zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        return export_path

    def _summary_paths(job) -> tuple[Path, str]:
        if not job.result or not job.result.get("summary_path"):
            raise HTTPException(status_code=400, detail="Summary not available for this job")
        summary_path = Path(job.result["summary_path"])
        if not summary_path.exists():
            raise HTTPException(status_code=404, detail="Summary not found")
        return summary_path, summary_path.read_text(encoding="utf-8")

    def _translated_paths(job) -> tuple[Path, str]:
        if not job.result or not job.result.get("translated_path"):
            translated_path = _find_translated_from_steps(job)
            if not translated_path:
                raise HTTPException(
                    status_code=400,
                    detail="Translation not available for this job",
                )
        else:
            translated_path = Path(job.result["translated_path"])
        if not translated_path.exists():
            raise HTTPException(status_code=404, detail="Translation not found")
        return translated_path, translated_path.read_text(encoding="utf-8")

    def _speakers_template(job) -> tuple[list[dict[str, Any]], list[str]]:
        if job.result and job.result.get("speakers_path"):
            speakers_path = Path(job.result["speakers_path"])
            if speakers_path.exists():
                try:
                    speakers = json.loads(speakers_path.read_text(encoding="utf-8"))
                    detected = [
                        item.get("speaker_tag")
                        for item in speakers
                        if isinstance(item, dict) and item.get("speaker_tag")
                    ]
                    return speakers, sorted(detected)
                except json.JSONDecodeError:
                    pass
        _, translated_text = _translated_paths(job)
        speaker_lines = parse_speaker_lines(translated_text)
        detected_tags = sorted(speaker_lines.keys())
        return build_speaker_configs(translated_text), detected_tags

    def _find_translated_from_steps(job) -> Optional[Path]:
        for step in reversed(job.steps):
            if step.step == "translate" and step.detail:
                for line in step.detail.splitlines():
                    if line.strip().lower().startswith("file:"):
                        rel = line.split(":", 1)[1].strip()
                        candidate = (config.runs_dir / rel).resolve()
                        if candidate.exists():
                            return candidate
        return None

    def _resolve_asset_path(filename: str) -> Path:
        assets_dir = config.settings.project_root / "InnoFranceApp" / "assets"
        candidate = assets_dir / filename
        if candidate.exists():
            return candidate
        fallback = config.settings.project_root / "InnoFrance" / filename
        if fallback.exists():
            return fallback
        raise HTTPException(status_code=404, detail=f"Asset not found: {filename}")

    def _merge_audio_files(inputs: list[Path], output_path: Path) -> None:
        cmd = [
            "ffmpeg",
            "-y",
        ]
        for path in inputs:
            cmd.extend(["-i", str(path)])
        cmd.extend(
            [
                "-filter_complex",
                f"concat=n={len(inputs)}:v=0:a=1[out]",
                "-map",
                "[out]",
                str(output_path),
            ]
        )
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Audio merge failed: {result.stderr}")

    def _save_upload(file: UploadFile) -> Path:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing filename")
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".mp3", ".wav"}:
            raise HTTPException(status_code=400, detail="Only .mp3 or .wav files are supported")
        uploads_dir = config.runs_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        target = uploads_dir / f"{Path(file.filename).stem}_{uuid.uuid4().hex}{suffix}"
        with open(target, "wb") as out:
            shutil.copyfileobj(file.file, out)
        return target


    @app.get("/api/settings", response_model=SettingsResponse)
    def get_settings() -> SettingsResponse:
        providers = ["openai", "deepseek", "qwen", "glm", "ollama", "sglang", "vllm"]
        availability = {p: _provider_available(p) for p in providers}
        sources = {p: _provider_key_source(p) for p in providers}
        asset_options = {
            "start_music": _list_asset_options("start_music"),
            "beginning": _list_asset_options("beginning"),
        }
        return SettingsResponse(
            parallel_enabled=queue.parallel_enabled,
            max_concurrent=queue.max_concurrent,
            max_queued=PipelineQueue.MAX_QUEUED,
            tags=queue.tags,
            provider_availability=availability,
            provider_key_source=sources,
            asset_options=asset_options,
            asset_selections=queue.asset_selections,
        )

    @app.post("/api/settings", response_model=SettingsResponse)
    def update_settings(body: SettingsUpdate) -> SettingsResponse:
        if body.parallel_enabled is not None:
            queue.parallel_enabled = body.parallel_enabled
        if body.max_concurrent is not None:
            queue.max_concurrent = body.max_concurrent
        if body.tags is not None:
            queue.tags = body.tags
        if body.api_keys is not None:
            merged = queue.api_keys
            merged.update(body.api_keys)
            queue.api_keys = merged
        if body.asset_selections is not None:
            merged = queue.asset_selections
            merged.update(body.asset_selections)
            queue.asset_selections = merged
        queue.save_state()
        return get_settings()

    @app.post("/api/pipeline/start", response_model=PipelineJobResponse)
    async def start_pipeline(req: PipelineStartRequest) -> PipelineJobResponse:
        sources = [v for v in (req.youtube_url, req.audio_url, req.audio_path) if v]
        if len(sources) != 1:
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one of youtube_url, audio_url, or audio_path.",
            )
        if not req.model_name or not req.model_name.strip():
            raise HTTPException(status_code=400, detail="model_name is required")
        try:
            job = await queue.enqueue(req, config_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.post("/api/uploads/audio")
    def upload_audio(file: UploadFile = File(...)):
        saved = _save_upload(file)
        return {"path": str(saved)}

    @app.get("/api/pipeline/jobs", response_model=PipelineListResponse)
    def list_pipeline_jobs(include_steps: bool = Query(False)) -> PipelineListResponse:
        return PipelineListResponse(
            jobs=[PipelineJobResponse(**j) for j in queue.list_jobs(include_steps=include_steps)],
            max_concurrent=queue.max_concurrent,
            parallel_enabled=queue.parallel_enabled,
        )

    @app.get("/api/pipeline/jobs/{job_id}", response_model=PipelineJobResponse)
    def get_pipeline_job(job_id: str) -> PipelineJobResponse:
        job = queue.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.delete("/api/pipeline/jobs/{job_id}", response_model=PipelineJobResponse)
    def delete_pipeline_job(job_id: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        queue.delete_job(job_id)
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )


    @app.post("/api/pipeline/queue/reorder", response_model=PipelineListResponse)
    def reorder_pipeline_queue(body: QueueReorderRequest) -> PipelineListResponse:
        queue.reorder_queue(body.job_ids)
        return PipelineListResponse(
            jobs=[PipelineJobResponse(**j) for j in queue.list_jobs(include_steps=False)],
            max_concurrent=queue.max_concurrent,
            parallel_enabled=queue.parallel_enabled,
        )


    @app.post("/api/pipeline/jobs/{job_id}/metadata", response_model=PipelineJobResponse)
    def update_pipeline_metadata(job_id: str, body: JobMetaUpdateRequest) -> PipelineJobResponse:
        try:
            job = queue.update_job_meta(
                job_id,
                note=body.note,
                custom_name=body.custom_name,
                tags=body.tags,
                published=body.published,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )


    @app.get("/api/pipeline/jobs/{job_id}/stream")
    async def stream_pipeline_events(job_id: str):
        job = queue.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        async def event_generator():
            async for ev in job.stream_events():
                yield {
                    "event": "progress",
                    "data": ev.model_dump_json(),
                }
            yield {"event": "done", "data": "{}"}

        return EventSourceResponse(event_generator())

    @app.post("/api/pipeline/jobs/{job_id}/speakers", response_model=PipelineJobResponse)
    def submit_speakers(job_id: str, body: SpeakersSubmitRequest) -> PipelineJobResponse:
        try:
            job = queue.submit_speakers(job_id, body.speakers_json)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )


    @app.post("/api/pipeline/jobs/{job_id}/speakers-redetect", response_model=PipelineJobResponse)
    async def redetect_speakers(job_id: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        if not job.result:
            raise HTTPException(status_code=400, detail="Job results not available")
        transcript_path_value = job.result.get("transcript_path")
        translated_path_value = job.result.get("translated_path")
        run_dir_value = job.result.get("run_dir")
        if not all([transcript_path_value, translated_path_value, run_dir_value]):
            raise HTTPException(status_code=400, detail="Transcript/translation not available")
        clip_paths = job.result.get("speaker_audio_paths") or []
        if not clip_paths:
            raise HTTPException(status_code=400, detail="Speaker clips not available")
        transcript_path = Path(transcript_path_value)
        translated_path = Path(translated_path_value)
        run_dir = Path(run_dir_value)
        if not transcript_path.exists() or not translated_path.exists():
            raise HTTPException(status_code=404, detail="Required files not found")

        translated_text = translated_path.read_text(encoding="utf-8").strip()

        def emit(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
            job.steps.append(StepEvent(step=step, status=status, message=message, detail=detail))
            queue.save_state()

        emit("speakers", "running", "Re-detecting speakers from clips", None)
        speaker_client = MCPToolClient(config.services["speaker_detect"])

        clip_tags = job.result.get("speaker_audio_tags") or []
        speaker_tags = clip_tags or _extract_speaker_tags(translated_text)
        if not speaker_tags:
            speaker_tags = ["SPEAKER0"]
        clips_with_tags: list[tuple[str, Path]] = []
        for index, path_value in enumerate(clip_paths):
            if not isinstance(path_value, str):
                continue
            tag = speaker_tags[index] if index < len(speaker_tags) else f"SPEAKER{index}"
            clips_with_tags.append((tag, Path(path_value)))
        speakers: list[dict[str, Any]] = []
        for tag, clip_path in clips_with_tags:
            result = await speaker_client.call_tool(
                "detect_speaker", {"audio_path": str(clip_path)}
            )
            profile = None
            if result.get("success"):
                profiles = result.get("result", [])
                if isinstance(profiles, list) and profiles:
                    profile = profiles[0]
            else:
                error = result.get("error", "Unknown error")
                emit("speakers", "running", f"Speaker detect failed for {tag}", error)
            speakers.append(
                {
                    "speaker_tag": f"[{tag}]",
                    "design_text": (profile or {}).get("design_text") or f"说话人 {tag}",
                    "design_instruct": (profile or {}).get("design_instruct")
                    or "性别与年龄未知，语速适中，音色自然清晰。",
                    "language": "Chinese",
                }
            )

        speakers_path = run_dir / "speakers.json"
        speakers_path.write_text(
            json.dumps(speakers, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        emit(
            "speakers",
            "completed",
            "Speaker configs updated",
            _relative_to_output(speakers_path),
        )

        speakers_url = job.result.get("speakers_url") if job.result else None
        speaker_audio_urls: list[str] = []
        if s3_client.enabled:
            run_prefix = run_dir.name
            speakers_uploaded = s3_client.upload_file(
                str(speakers_path), f"{run_prefix}/{speakers_path.name}"
            )
            if speakers_uploaded:
                speakers_url = speakers_uploaded.url
            for path_value in clip_paths:
                if isinstance(path_value, str):
                    uploaded = s3_client.upload_file(
                        path_value, f"{run_prefix}/{Path(path_value).name}"
                    )
                    if uploaded and uploaded.url:
                        speaker_audio_urls.append(uploaded.url)

        job = queue.update_job_result(
            job_id,
            {
                "speakers_path": str(speakers_path),
                "speakers_relative": _relative_to_output(speakers_path),
                "speaker_audio_paths": [str(p) for p in clip_paths if isinstance(p, str)],
                "speaker_audio_relatives": [
                    _relative_to_output(Path(p))
                    for p in clip_paths
                    if isinstance(p, str)
                ],
                "speaker_audio_tags": speaker_tags,
                "speakers_url": speakers_url,
                "speaker_audio_urls": speaker_audio_urls,
            },
        )
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.post("/api/pipeline/jobs/{job_id}/speakers-reclip", response_model=PipelineJobResponse)
    async def reclip_speakers(job_id: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        if not job.result:
            raise HTTPException(status_code=400, detail="Job results not available")
        audio_path_value = job.result.get("audio_path")
        transcript_path_value = job.result.get("transcript_path")
        translated_path_value = job.result.get("translated_path")
        run_dir_value = job.result.get("run_dir")
        if not all([audio_path_value, transcript_path_value, translated_path_value, run_dir_value]):
            raise HTTPException(status_code=400, detail="Audio/transcript/translation not available")
        audio_path = Path(audio_path_value)
        transcript_path = Path(transcript_path_value)
        translated_path = Path(translated_path_value)
        run_dir = Path(run_dir_value)
        if not audio_path.exists() or not transcript_path.exists() or not translated_path.exists():
            raise HTTPException(status_code=404, detail="Required files not found")

        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        translated_text = translated_path.read_text(encoding="utf-8").strip()

        def emit(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
            job.steps.append(StepEvent(step=step, status=status, message=message, detail=detail))
            queue.save_state()

        emit("speakers", "running", "Re-selecting speaker clips", None)
        speaker_groups = _group_segments_by_speaker(transcript)
        candidates = job.result.get("speaker_clip_candidates") if job.result else None
        if not isinstance(candidates, dict) or not candidates:
            candidates = _build_speaker_clip_candidates(speaker_groups)
        selected = job.result.get("speaker_clip_selected") if job.result else None
        if not isinstance(selected, dict):
            selected = {}
        tags = job.result.get("speaker_audio_tags") if job.result else None
        if not isinstance(tags, list) or not tags:
            tags = sorted(candidates.keys(), key=_speaker_sort_key)

        clips_with_tags: list[tuple[str, Path]] = []
        chosen: dict[str, dict[str, Any]] = {}
        for tag in tags:
            options = candidates.get(tag) or []
            if not options:
                continue
            current_index = int(selected.get(tag, 0))
            next_index = (current_index + 1) % len(options)
            selected[tag] = next_index
            seg = options[next_index]
            chosen[tag] = seg
            output_path = run_dir / f"{tag.lower()}.wav"
            await asyncio.to_thread(
                _extract_audio_clip,
                audio_path,
                seg["start"],
                seg["end"],
                output_path,
            )
            clips_with_tags.append((tag, output_path))
            emit(
                "speakers",
                "running",
                f"Speaker clip saved for {tag}",
                _relative_to_output(output_path),
            )

        if not clips_with_tags:
            raise HTTPException(status_code=400, detail="No valid speaker clips found")

        speaker_tags = [tag for tag, _ in clips_with_tags]
        clip_paths = [str(path) for _, path in clips_with_tags]
        speaker_audio_urls: list[str] = []
        if s3_client.enabled:
            run_prefix = run_dir.name
            for path_value in clip_paths:
                uploaded = s3_client.upload_file(
                    path_value, f"{run_prefix}/{Path(path_value).name}"
                )
                if uploaded and uploaded.url:
                    speaker_audio_urls.append(uploaded.url)

        job = queue.update_job_result(
            job_id,
            {
                "speaker_audio_paths": clip_paths,
                "speaker_audio_relatives": [
                    _relative_to_output(Path(p)) for p in clip_paths
                ],
                "speaker_audio_urls": speaker_audio_urls,
                "speaker_audio_tags": speaker_tags,
                "speaker_clip_segments": chosen,
                "speaker_clip_candidates": candidates,
                "speaker_clip_selected": selected,
            },
        )
        emit("speakers", "completed", "Speaker clips updated", None)
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )


    @app.post("/api/pipeline/jobs/{job_id}/speakers-reclip/{speaker_tag}", response_model=PipelineJobResponse)
    async def reclip_speaker(job_id: str, speaker_tag: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        if not job.result:
            raise HTTPException(status_code=400, detail="Job results not available")
        audio_path_value = job.result.get("input_audio_path") or job.result.get("audio_path")
        transcript_path_value = job.result.get("transcript_path")
        run_dir_value = job.result.get("run_dir")
        if not all([audio_path_value, transcript_path_value, run_dir_value]):
            raise HTTPException(status_code=400, detail="Audio/transcript not available")
        audio_path = Path(audio_path_value)
        transcript_path = Path(transcript_path_value)
        run_dir = Path(run_dir_value)
        if not audio_path.exists() or not transcript_path.exists():
            raise HTTPException(status_code=404, detail="Required files not found")

        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

        def emit(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
            job.steps.append(StepEvent(step=step, status=status, message=message, detail=detail))
            queue.save_state()

        emit("speakers", "running", f"Re-selecting clip for {speaker_tag}", None)
        speaker_groups = _group_segments_by_speaker(transcript)
        candidates = job.result.get("speaker_clip_candidates") if job.result else None
        if not isinstance(candidates, dict) or not candidates:
            candidates = _build_speaker_clip_candidates(speaker_groups)
        selected = job.result.get("speaker_clip_selected") if job.result else None
        if not isinstance(selected, dict):
            selected = {}

        options = candidates.get(speaker_tag) or []
        if not options:
            raise HTTPException(status_code=400, detail="No candidate clips for speaker")
        current_index = int(selected.get(speaker_tag, 0))
        next_index = (current_index + 1) % len(options)
        selected[speaker_tag] = next_index
        seg = options[next_index]
        output_path = run_dir / f"{speaker_tag.lower()}.wav"
        await asyncio.to_thread(
            _extract_audio_clip,
            audio_path,
            seg["start"],
            seg["end"],
            output_path,
        )
        emit(
            "speakers",
            "running",
            f"Speaker clip saved for {speaker_tag}",
            _relative_to_output(output_path),
        )

        clip_paths = job.result.get("speaker_audio_paths") or []
        clip_tags = job.result.get("speaker_audio_tags") or sorted(candidates.keys(), key=_speaker_sort_key)
        if len(clip_paths) < len(clip_tags):
            clip_paths = list(clip_paths) + [""] * (len(clip_tags) - len(clip_paths))
        for index, tag in enumerate(clip_tags):
            if tag == speaker_tag:
                clip_paths[index] = str(output_path)
        chosen = job.result.get("speaker_clip_segments") or {}
        if isinstance(chosen, dict):
            chosen[speaker_tag] = seg

        speaker_audio_urls: list[str] = []
        if s3_client.enabled:
            run_prefix = run_dir.name
            for path_value in clip_paths:
                if not path_value:
                    continue
                uploaded = s3_client.upload_file(
                    path_value, f"{run_prefix}/{Path(path_value).name}"
                )
                if uploaded and uploaded.url:
                    speaker_audio_urls.append(uploaded.url)

        job = queue.update_job_result(
            job_id,
            {
                "speaker_audio_paths": clip_paths,
                "speaker_audio_relatives": [
                    _relative_to_output(Path(p)) for p in clip_paths if p
                ],
                "speaker_audio_urls": speaker_audio_urls,
                "speaker_audio_tags": clip_tags,
                "speaker_clip_segments": chosen,
                "speaker_clip_candidates": candidates,
                "speaker_clip_selected": selected,
            },
        )
        emit("speakers", "completed", "Speaker clip updated", None)
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )


    @app.post("/api/pipeline/jobs/{job_id}/speakers-redetect/{speaker_tag}", response_model=PipelineJobResponse)
    async def redetect_speaker(job_id: str, speaker_tag: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        if not job.result:
            raise HTTPException(status_code=400, detail="Job results not available")
        translated_path_value = job.result.get("translated_path")
        run_dir_value = job.result.get("run_dir")
        if not all([translated_path_value, run_dir_value]):
            raise HTTPException(status_code=400, detail="Translation not available")
        clip_paths = job.result.get("speaker_audio_paths") or []
        clip_tags = job.result.get("speaker_audio_tags") or []
        if not clip_paths:
            raise HTTPException(status_code=400, detail="Speaker clips not available")
        translated_path = Path(translated_path_value)
        run_dir = Path(run_dir_value)
        if not translated_path.exists():
            raise HTTPException(status_code=404, detail="Required files not found")

        translated_text = translated_path.read_text(encoding="utf-8").strip()
        if not clip_tags:
            clip_tags = _extract_speaker_tags(translated_text) or ["SPEAKER0"]

        clip_path = None
        for index, path_value in enumerate(clip_paths):
            tag = clip_tags[index] if index < len(clip_tags) else f"SPEAKER{index}"
            if tag == speaker_tag:
                clip_path = Path(path_value)
                break
        if clip_path is None:
            raise HTTPException(status_code=400, detail="Speaker clip not found")

        def emit(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
            job.steps.append(StepEvent(step=step, status=status, message=message, detail=detail))
            queue.save_state()

        emit("speakers", "running", f"Re-detecting {speaker_tag}", None)
        speaker_client = MCPToolClient(config.services["speaker_detect"])
        result = await speaker_client.call_tool(
            "detect_speaker", {"audio_path": str(clip_path)}
        )
        profile = None
        if result.get("success"):
            profiles = result.get("result", [])
            if isinstance(profiles, list) and profiles:
                profile = profiles[0]
        else:
            error = result.get("error", "Unknown error")
            emit("speakers", "running", f"Speaker detect failed for {speaker_tag}", error)

        speakers_path = run_dir / "speakers.json"
        existing = []
        if speakers_path.exists():
            try:
                existing = json.loads(speakers_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        if not isinstance(existing, list):
            existing = []
        target_tag = f"[{speaker_tag}]"
        updated = []
        replaced = False
        for item in existing:
            if isinstance(item, dict) and item.get("speaker_tag") == target_tag:
                updated.append(
                    {
                        "speaker_tag": target_tag,
                        "design_text": (profile or {}).get("design_text") or f"说话人 {speaker_tag}",
                        "design_instruct": (profile or {}).get("design_instruct")
                        or "性别与年龄未知，语速适中，音色自然清晰。",
                        "language": "Chinese",
                    }
                )
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(
                {
                    "speaker_tag": target_tag,
                    "design_text": (profile or {}).get("design_text") or f"说话人 {speaker_tag}",
                    "design_instruct": (profile or {}).get("design_instruct")
                    or "性别与年龄未知，语速适中，音色自然清晰。",
                    "language": "Chinese",
                }
            )
        speakers_path.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        emit("speakers", "completed", "Speaker configs updated", _relative_to_output(speakers_path))

        speakers_url = job.result.get("speakers_url") if job.result else None
        if s3_client.enabled:
            run_prefix = run_dir.name
            speakers_uploaded = s3_client.upload_file(
                str(speakers_path), f"{run_prefix}/{speakers_path.name}"
            )
            if speakers_uploaded:
                speakers_url = speakers_uploaded.url

        job = queue.update_job_result(
            job_id,
            {
                "speakers_path": str(speakers_path),
                "speakers_relative": _relative_to_output(speakers_path),
                "speaker_audio_tags": clip_tags,
                "speakers_url": speakers_url,
            },
        )
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.get("/api/pipeline/jobs/{job_id}/speakers-template")
    def get_speakers_template(job_id: str):
        job = _get_job_or_404(job_id)
        speakers, detected = _speakers_template(job)
        return {"speakers": speakers, "detected_speakers": detected}

    @app.get("/api/pipeline/jobs/{job_id}/summary")
    def get_summary(job_id: str):
        job = _get_job_or_404(job_id)
        _, summary_text = _summary_paths(job)
        return PlainTextResponse(summary_text)

    @app.post("/api/pipeline/jobs/{job_id}/summary", response_model=PipelineJobResponse)
    def update_summary(job_id: str, body: SummaryUpdateRequest) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        summary_path, _ = _summary_paths(job)
        summary_path.write_text(body.text, encoding="utf-8")
        summary_url = job.result.get("summary_url") if job.result else None
        if s3_client.enabled:
            run_prefix = None
            if job.result and job.result.get("run_dir"):
                run_prefix = Path(job.result["run_dir"]).name
            key = f"{run_prefix}/{summary_path.name}" if run_prefix else summary_path.name
            uploaded = s3_client.upload_file(str(summary_path), key)
            if uploaded:
                summary_url = uploaded.url
        if summary_url is not None:
            queue.update_job_result(job_id, {"summary_url": summary_url})
        queue.save_state()
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.get("/api/pipeline/jobs/{job_id}/translated")
    def get_translated(job_id: str):
        job = _get_job_or_404(job_id)
        _, translated_text = _translated_paths(job)
        return PlainTextResponse(translated_text)

    @app.post("/api/pipeline/jobs/{job_id}/translated", response_model=PipelineJobResponse)
    def update_translated(job_id: str, body: TranslationUpdateRequest) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        translated_path, _ = _translated_paths(job)
        translated_path.write_text(body.text, encoding="utf-8")
        translated_url = job.result.get("translated_url") if job.result else None
        if s3_client.enabled:
            run_prefix = None
            if job.result and job.result.get("run_dir"):
                run_prefix = Path(job.result["run_dir"]).name
            key = f"{run_prefix}/{translated_path.name}" if run_prefix else translated_path.name
            uploaded = s3_client.upload_file(str(translated_path), key)
            if uploaded:
                translated_url = uploaded.url
        if translated_url is not None:
            queue.update_job_result(job_id, {"translated_url": translated_url})
        queue.save_state()
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.post("/api/pipeline/jobs/{job_id}/summary-audio", response_model=PipelineJobResponse)
    async def generate_summary_audio(job_id: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        summary_path, summary_text = _summary_paths(job)
        if not summary_text.strip():
            raise HTTPException(status_code=400, detail="Summary text is empty")

        run_dir_value = job.result.get("run_dir") if job.result else None
        if not run_dir_value:
            raise HTTPException(status_code=400, detail="Run directory not available")
        run_dir = Path(run_dir_value)
        summary_audio_path = run_dir / "summary_audio.wav"
        prompt_dir = config.settings.tts_dir / "examples" / "voice_prompts"
        ref_audio = prompt_dir / "zh_young_man.wav"
        ref_text_path = prompt_dir / "zh_young_man.txt"
        if not ref_audio.exists():
            raise HTTPException(status_code=404, detail="Voice prompt audio not found")
        ref_text = ""
        if ref_text_path.exists():
            ref_text = ref_text_path.read_text(encoding="utf-8").strip()

        speaker_configs = [
            {
                "speaker_tag": "[SPEAKER0]",
                "ref_audio": str(ref_audio),
                "ref_text": ref_text,
                "language": "Chinese",
            }
        ]
        tts_client = MCPToolClient(config.services["tts"])
        result = await tts_client.call_tool(
            "clone_voice",
            {
                "text": summary_text,
                "speaker_configs_json": json.dumps(speaker_configs, ensure_ascii=False),
                "speed": 1.0,
                "output_path": str(summary_audio_path),
            },
        )
        if not result.get("success"):
            error = result.get("error", "Summary audio generation failed")
            raise HTTPException(status_code=500, detail=error)

        summary_audio_url = None
        if s3_client.enabled:
            run_prefix = run_dir.name
            uploaded = s3_client.upload_file(
                str(summary_audio_path), f"{run_prefix}/{summary_audio_path.name}"
            )
            if uploaded:
                summary_audio_url = uploaded.url

        job = queue.update_job_result(
            job_id,
            {
                "summary_audio_path": str(summary_audio_path),
                "summary_audio_relative": _relative_to_output(summary_audio_path),
                "summary_audio_url": summary_audio_url,
            },
        )
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.post("/api/pipeline/jobs/{job_id}/merge-audio", response_model=PipelineJobResponse)
    def merge_final_audio(job_id: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        if not job.result:
            raise HTTPException(status_code=400, detail="Job results not available")
        audio_path_value = job.result.get("audio_path")
        summary_audio_value = job.result.get("summary_audio_path")
        if not audio_path_value or not summary_audio_value:
            raise HTTPException(status_code=400, detail="Summary audio and dialogue audio are required")

        run_dir_value = job.result.get("run_dir")
        if not run_dir_value:
            raise HTTPException(status_code=400, detail="Run directory not available")
        run_dir = Path(run_dir_value)
        output_path = run_dir / "final_audio.wav"
        inputs = [
            _resolve_asset_for_type("start_music"),
            _resolve_asset_for_type("beginning"),
            Path(summary_audio_value),
            Path(audio_path_value),
        ]
        _merge_audio_files(inputs, output_path)

        merged_audio_url = None
        if s3_client.enabled:
            run_prefix = run_dir.name
            uploaded = s3_client.upload_file(
                str(output_path), f"{run_prefix}/{output_path.name}"
            )
            if uploaded:
                merged_audio_url = uploaded.url

        job = queue.update_job_result(
            job_id,
            {
                "merged_audio_path": str(output_path),
                "merged_audio_relative": _relative_to_output(output_path),
                "merged_audio_url": merged_audio_url,
            },
        )
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )

    @app.post("/api/pipeline/jobs/{job_id}/tts", response_model=PipelineJobResponse)
    async def regenerate_audio(job_id: str, body: SpeakersSubmitRequest) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        if not body.speakers_json.strip():
            raise HTTPException(status_code=400, detail="speakers_json is required")
        run_dir_value = job.result.get("run_dir") if job.result else None
        if not run_dir_value:
            raise HTTPException(status_code=400, detail="Run directory not available")
        run_dir = Path(run_dir_value)
        _, translated_text = _translated_paths(job)

        speakers = _parse_speaker_configs(body.speakers_json, config.settings.project_root)
        speakers_path = run_dir / "speakers.json"
        speakers_path.write_text(
            json.dumps(speakers, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        job.steps.append(
            StepEvent(step="tts", status="running", message="Regenerating audio", detail=None)
        )
        queue.save_state()

        tts_client = MCPToolClient(config.services["tts"])
        audio_output_path = run_dir / "audio.wav"
        tts_result = await tts_client.call_tool(
            "clone_voice",
            {
                "text": normalize_translation_text(translated_text),
                "speaker_configs_json": json.dumps(speakers, ensure_ascii=False),
                "speed": 1.0,
                "output_path": str(audio_output_path),
            },
        )
        if not tts_result.get("success"):
            error = tts_result.get("error", "Audio regeneration failed")
            job.steps.append(
                StepEvent(step="tts", status="failed", message="Audio regeneration failed", detail=error)
            )
            queue.save_state()
            raise HTTPException(status_code=500, detail=error)

        audio_url = job.result.get("audio_url") if job.result else None
        speakers_url = job.result.get("speakers_url") if job.result else None
        if s3_client.enabled:
            run_prefix = run_dir.name
            speakers_uploaded = s3_client.upload_file(
                str(speakers_path), f"{run_prefix}/{speakers_path.name}"
            )
            if speakers_uploaded:
                speakers_url = speakers_uploaded.url
            audio_uploaded = s3_client.upload_file(
                str(audio_output_path), f"{run_prefix}/{audio_output_path.name}"
            )
            if audio_uploaded:
                audio_url = audio_uploaded.url

        job.steps.append(
            StepEvent(
                step="tts",
                status="completed",
                message="Audio regenerated",
                detail=_relative_to_output(audio_output_path),
            )
        )
        job = queue.update_job_result(
            job_id,
            {
                "audio_path": str(audio_output_path),
                "audio_relative": _relative_to_output(audio_output_path),
                "audio_url": audio_url,
                "speakers_path": str(speakers_path),
                "speakers_relative": _relative_to_output(speakers_path),
                "speakers_url": speakers_url,
            },
        )
        return PipelineJobResponse(
            **job.to_response(queue_position=queue.queue_position(job.job_id))
        )


    @app.get("/api/pipeline/jobs/{job_id}/export")
    def export_pipeline(job_id: str):
        job = _get_job_or_404(job_id)
        if job.status != "completed":
            raise HTTPException(status_code=400, detail="Pipeline must be completed to export")
        if not job.result or not job.result.get("merged_audio_path"):
            raise HTTPException(status_code=400, detail="Merge audio before exporting")
        export_path = _build_export_zip(job)
        base_name = job.custom_name or Path(job.result.get("run_dir", "")).name
        filename = f"{_sanitize_export_name(base_name)}.zip"
        return FileResponse(export_path, filename=filename)


    @app.post("/api/assets/upload")
    def upload_asset(asset_type: str = Query(..., regex="^(start_music|beginning)$"), file: UploadFile = File(...)):
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing filename")
        if Path(file.filename).suffix.lower() != ".wav":
            raise HTTPException(status_code=400, detail="Only .wav files are supported")
        target_dir = _asset_custom_dir(asset_type)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_asset_filename(file.filename)
        target = target_dir / safe_name
        with open(target, "wb") as out:
            shutil.copyfileobj(file.file, out)
        return {"success": True, "filename": target.name}

    @app.get("/api/artifacts/download")
    def download_artifact(
        path: str = Query(..., description="Relative path under output/ or runs/"),
    ):
        full = _allowed_path(path)
        if not full.is_file():
            raise HTTPException(status_code=400, detail="Not a file")
        return FileResponse(full, filename=full.name)

    @app.get("/api/artifacts/preview/summary")
    def preview_summary(
        path: str = Query(..., description="Relative path under output/ (e.g. output/sp1_video.txt)"),
    ):
        full = _allowed_path(path)
        if not full.is_file() or full.suffix.lower() != ".txt":
            raise HTTPException(status_code=400, detail="Not a summary text file")
#        return PlainTextResponse(full.read_text(encoding="utf-8"))
        text = full.read_text(encoding="utf-8")
        return Response(
            content=text,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Length": str(len(text.encode("utf-8")))
            },
        )

    @app.get("/api/artifacts/preview/audio")
    def preview_audio(
        path: str = Query(..., description="Relative path under output/ (e.g. output/sp1_video.wav)"),
    ):
        full = _allowed_path(path)
        if not full.is_file() or full.suffix.lower() not in (".wav", ".mp3"):
            raise HTTPException(status_code=400, detail="Not an audio file")
        return FileResponse(full, media_type="audio/wav" if full.suffix.lower() == ".wav" else "audio/mpeg")

    return app
