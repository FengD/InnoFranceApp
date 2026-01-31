from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from ..config import load_app_config
from ..mcp_clients import MCPToolClient
from ..s3 import S3Client
from .queue import PipelineQueue
from .schemas import (
    PipelineJobResponse,
    PipelineListResponse,
    PipelineStartRequest,
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
        return SettingsResponse(
            parallel_enabled=queue.parallel_enabled,
            max_concurrent=queue.max_concurrent,
            max_queued=PipelineQueue.MAX_QUEUED,
        )

    @app.patch("/api/settings", response_model=SettingsResponse)
    def update_settings(body: SettingsUpdate) -> SettingsResponse:
        if body.parallel_enabled is not None:
            queue.parallel_enabled = body.parallel_enabled
        if body.max_concurrent is not None:
            queue.max_concurrent = body.max_concurrent
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
        return PipelineJobResponse(**job.to_response())

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
        return PipelineJobResponse(**job.to_response())

    @app.delete("/api/pipeline/jobs/{job_id}", response_model=PipelineJobResponse)
    def delete_pipeline_job(job_id: str) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        queue.delete_job(job_id)
        return PipelineJobResponse(**job.to_response())


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
        return PipelineJobResponse(**job.to_response())

    @app.get("/api/pipeline/jobs/{job_id}/summary")
    def get_summary(job_id: str):
        job = _get_job_or_404(job_id)
        _, summary_text = _summary_paths(job)
        return PlainTextResponse(summary_text)

    @app.patch("/api/pipeline/jobs/{job_id}/summary", response_model=PipelineJobResponse)
    def update_summary(job_id: str, body: SummaryUpdateRequest) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        summary_path, _ = _summary_paths(job)
        summary_path.write_text(body.text, encoding="utf-8")
        summary_url = job.result.get("summary_url") if job.result else None
        if s3_client.enabled:
            uploaded = s3_client.upload_file(str(summary_path), summary_path.name)
            if uploaded:
                summary_url = uploaded.url
        if summary_url is not None:
            queue.update_job_result(job_id, {"summary_url": summary_url})
        queue.save_state()
        return PipelineJobResponse(**job.to_response())

    @app.get("/api/pipeline/jobs/{job_id}/translated")
    def get_translated(job_id: str):
        job = _get_job_or_404(job_id)
        _, translated_text = _translated_paths(job)
        return PlainTextResponse(translated_text)

    @app.patch("/api/pipeline/jobs/{job_id}/translated", response_model=PipelineJobResponse)
    def update_translated(job_id: str, body: TranslationUpdateRequest) -> PipelineJobResponse:
        job = _get_job_or_404(job_id)
        translated_path, _ = _translated_paths(job)
        translated_path.write_text(body.text, encoding="utf-8")
        queue.save_state()
        return PipelineJobResponse(**job.to_response())

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
        return PipelineJobResponse(**job.to_response())

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
            _resolve_asset_path("start_music.wav"),
            _resolve_asset_path("beginning.wav"),
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
        return PipelineJobResponse(**job.to_response())

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
        return PlainTextResponse(full.read_text(encoding="utf-8"))

    @app.get("/api/artifacts/preview/audio")
    def preview_audio(
        path: str = Query(..., description="Relative path under output/ (e.g. output/sp1_video.wav)"),
    ):
        full = _allowed_path(path)
        if not full.is_file() or full.suffix.lower() not in (".wav", ".mp3"):
            raise HTTPException(status_code=400, detail="Not an audio file")
        return FileResponse(full, media_type="audio/wav" if full.suffix.lower() == ".wav" else "audio/mpeg")

    return app
