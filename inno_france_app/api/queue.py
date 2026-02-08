from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from ..config import load_app_config
from ..logging_utils import log_event, setup_logging
from ..s3 import S3Client
from ..pipeline import InnoFrancePipeline, PipelineResult
from .schemas import PipelineStartRequest, StepEvent


@dataclass
class PipelineJob:
    job_id: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    steps: list[StepEvent] = field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    _progress_queue: Optional[asyncio.Queue[Optional[StepEvent]]] = None
    speaker_required: bool = False
    speaker_submitted: bool = False
    _speaker_future: Optional[asyncio.Future[str]] = None
    note: Optional[str] = None
    custom_name: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    published: bool = False

    def to_response(
        self,
        include_steps: bool = True,
        queue_position: Optional[int] = None,
    ) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "error": self.error,
            "steps": [s.model_dump() for s in self.steps] if include_steps else [],
            "result": self.result,
            "speaker_required": self.speaker_required,
            "speaker_submitted": self.speaker_submitted,
            "queue_position": queue_position,
            "note": self.note,
            "custom_name": self.custom_name,
            "tags": list(self.tags),
            "published": self.published,
        }

    async def stream_events(self) -> AsyncIterator[StepEvent]:
        for s in list(self.steps):
            yield s
        if not self._progress_queue:
            return
        while True:
            ev = await self._progress_queue.get()
            if ev is None:
                break
            yield ev

    def to_state(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "error": self.error,
            "steps": [s.model_dump() for s in self.steps],
            "result": self.result,
            "speaker_required": self.speaker_required,
            "speaker_submitted": self.speaker_submitted,
            "note": self.note,
            "custom_name": self.custom_name,
            "tags": list(self.tags),
            "published": self.published,
        }

    @staticmethod
    def from_state(payload: dict[str, Any]) -> "PipelineJob":
        created_at = _parse_datetime(payload.get("created_at")) or datetime.utcnow()
        started_at = _parse_datetime(payload.get("started_at"))
        finished_at = _parse_datetime(payload.get("finished_at"))
        steps = []
        for item in payload.get("steps", []) or []:
            if isinstance(item, dict):
                steps.append(StepEvent(**item))
        job = PipelineJob(
            job_id=str(payload.get("job_id")),
            status=str(payload.get("status", "failed")),
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
            error=payload.get("error"),
            steps=steps,
            result=payload.get("result"),
            speaker_required=bool(payload.get("speaker_required", False)),
            speaker_submitted=bool(payload.get("speaker_submitted", False)),
            note=payload.get("note"),
            custom_name=payload.get("custom_name"),
            tags=[str(t) for t in payload.get("tags", []) or []],
            published=bool(payload.get("published", False)),
        )
        return job


class PipelineQueue:
    MAX_QUEUED = 10

    def __init__(
        self,
        parallel_enabled: bool = False,
        max_concurrent: int = 1,
        state_path: Optional[Path] = None,
        s3_client: Optional[S3Client] = None,
        runs_dir: Optional[Path] = None,
    ) -> None:
        self._parallel_enabled = parallel_enabled
        self._max_concurrent = max(1, min(5, max_concurrent))
        self._jobs: dict[str, PipelineJob] = {}
        self._running: set[str] = set()
        self._queue_order: list[str] = []
        self._tags: list[str] = []
        self._api_keys: dict[str, str] = {}
        self._asset_selections: dict[str, str] = {}
        self._save_task: Optional[asyncio.Task[None]] = None
        self._save_pending = False
        self._lock = asyncio.Lock()
        self._state_path = state_path
        self._s3_client = s3_client
        self._runs_dir = runs_dir
        self._logger = setup_logging()
        self._load_state()

    @property
    def parallel_enabled(self) -> bool:
        return self._parallel_enabled

    @parallel_enabled.setter
    def parallel_enabled(self, value: bool) -> None:
        self._parallel_enabled = value

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int) -> None:
        self._max_concurrent = max(1, min(5, value))

    def _slots_available(self) -> int:
        if self._parallel_enabled:
            return self._max_concurrent - len(self._running)
        return 1 - len(self._running) if self._running else 1

    @property
    def tags(self) -> list[str]:
        return list(self._tags)

    @tags.setter
    def tags(self, value: list[str]) -> None:
        normalized: list[str] = []
        for item in value:
            label = str(item).strip()
            if not label:
                continue
            if label not in normalized:
                normalized.append(label)
        self._tags = normalized

    @property
    def api_keys(self) -> dict[str, str]:
        return dict(self._api_keys)

    @api_keys.setter
    def api_keys(self, value: dict[str, str]) -> None:
        normalized: dict[str, str] = {}
        for key, raw in (value or {}).items():
            name = str(key).strip()
            if not name:
                continue
            val = str(raw).strip()
            if val:
                normalized[name] = val
        self._api_keys = normalized

    def get_api_key(self, provider: str) -> Optional[str]:
        return self._api_keys.get(provider)

    @property
    def asset_selections(self) -> dict[str, str]:
        return dict(self._asset_selections)

    @asset_selections.setter
    def asset_selections(self, value: dict[str, str]) -> None:
        normalized: dict[str, str] = {}
        for key, raw in (value or {}).items():
            name = str(key).strip()
            if not name:
                continue
            val = str(raw).strip()
            if val:
                normalized[name] = val
        self._asset_selections = normalized

    def _queue_position(self, job_id: str) -> Optional[int]:
        try:
            return self._queue_order.index(job_id)
        except ValueError:
            return None

    def queue_position(self, job_id: str) -> Optional[int]:
        return self._queue_position(job_id)

    def _can_start(self, job_id: str) -> bool:
        slots = self._slots_available()
        if slots <= 0:
            return False
        if job_id not in self._queue_order:
            return True
        allowed = self._queue_order[: (slots if self._parallel_enabled else 1)]
        return job_id in allowed

    def list_jobs(self, include_steps: bool = True) -> list[dict[str, Any]]:
        response: list[dict[str, Any]] = []
        ordered_ids: list[str] = []
        ordered_ids.extend([jid for jid in self._queue_order if jid in self._jobs])
        running = [
            j.job_id
            for j in sorted(
                self._jobs.values(),
                key=lambda x: x.started_at or x.created_at,
            )
            if j.status == "running" and j.job_id not in ordered_ids
        ]
        ordered_ids.extend(running)
        remaining = [
            j.job_id
            for j in sorted(
                self._jobs.values(),
                key=lambda x: x.finished_at or x.created_at,
                reverse=True,
            )
            if j.job_id not in ordered_ids
        ]
        ordered_ids.extend(remaining)
        for job_id in ordered_ids:
            job = self._jobs.get(job_id)
            if not job:
                continue
            response.append(
                job.to_response(
                    include_steps=include_steps,
                    queue_position=self._queue_position(job_id),
                )
            )
        return response

    def get_job(self, job_id: str) -> Optional[PipelineJob]:
        return self._jobs.get(job_id)

    async def enqueue(self, req: PipelineStartRequest, config_path: Optional[Path] = None) -> PipelineJob:
        async with self._lock:
            queued = sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))
            if queued >= self.MAX_QUEUED:
                raise ValueError(f"Queue full: at most {self.MAX_QUEUED} pipelines allowed (queued + running)")

            job_id = str(uuid.uuid4())
            progress_queue: asyncio.Queue[Optional[StepEvent]] = asyncio.Queue()

            def on_progress(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
                ev = StepEvent(step=step, status=status, message=message, detail=detail)
                job = self._jobs.get(job_id)
                if job:
                    job.steps.append(ev)
                    if (
                        step == "translate"
                        and status == "completed"
                        and detail
                        and self._runs_dir
                    ):
                        rel_path = _extract_detail_path(detail)
                        if rel_path:
                            translated_path = (self._runs_dir / rel_path).resolve()
                            job.result = job.result or {}
                            job.result["translated_path"] = str(translated_path)
                            try:
                                job.result["translated_relative"] = str(
                                    translated_path.relative_to(self._runs_dir.resolve())
                                )
                            except ValueError:
                                job.result["translated_relative"] = translated_path.name
                    self._save_state()
                try:
                    progress_queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass
                log_event(
                    self._logger,
                    "pipeline_step",
                    job_id=job_id,
                    step=step,
                    status=status,
                    message=message,
                    detail=detail,
                )

            job = PipelineJob(
                job_id=job_id,
                status="queued",
                created_at=datetime.utcnow(),
                _progress_queue=progress_queue,
                speaker_required=bool(req.manual_speakers),
            )
            if req.manual_speakers:
                job._speaker_future = asyncio.Future()
            self._jobs[job_id] = job
            self._queue_order.append(job_id)
            self._save_state()

        log_event(
            self._logger,
            "job_enqueued",
            job_id=job_id,
            youtube_url=req.youtube_url,
            audio_url=req.audio_url,
            audio_path=req.audio_path,
            provider=req.provider,
            model_name=req.model_name,
            language=req.language,
            chunk_length=req.chunk_length,
            speed=req.speed,
            manual_speakers=req.manual_speakers,
        )
        asyncio.create_task(self._run_job(job_id, req, on_progress, progress_queue, config_path))
        return job

    async def _run_job(
        self,
        job_id: str,
        req: PipelineStartRequest,
        on_progress: Any,
        progress_queue: asyncio.Queue[Optional[StepEvent]],
        config_path: Optional[Path],
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return

        while True:
            async with self._lock:
                if self._can_start(job_id):
                    if job_id in self._queue_order:
                        self._queue_order.remove(job_id)
                    self._running.add(job_id)
                    break
            await asyncio.sleep(0.5)

        job.status = "running"
        job.started_at = datetime.utcnow()
        self._save_state()
        log_event(
            self._logger,
            "job_started",
            job_id=job_id,
            started_at=job.started_at.isoformat() + "Z",
        )

        try:
            config = load_app_config(config_path)
            pipeline = InnoFrancePipeline(config)
            result: PipelineResult = await pipeline.run(
                youtube_url=req.youtube_url,
                audio_url=req.audio_url,
                audio_path=req.audio_path,
                provider=req.provider,
                model_name=req.model_name,
                language=req.language,
                chunk_length=req.chunk_length,
                speed=req.speed,
                yt_cookies_file=req.yt_cookies_file,
                yt_cookies_from_browser=req.yt_cookies_from_browser,
                yt_user_agent=req.yt_user_agent,
                yt_proxy=req.yt_proxy,
                provider_api_key=self.get_api_key(req.provider),
                on_progress=on_progress,
                manual_speakers=req.manual_speakers,
                speaker_future=job._speaker_future,
            )
            job.status = "completed"
            source_url = req.youtube_url or req.audio_url
            if source_url:
                if job.note:
                    if source_url not in job.note:
                        separator = "\n" if not job.note.endswith("\n") else ""
                        job.note = f"{job.note}{separator}{source_url}"
                else:
                    job.note = source_url
            runs_dir = config.runs_dir.resolve()
            audio_url = None
            summary_url = None
            speakers_url = None
            translated_url = None
            transcript_url = None
            input_audio_url = None
            speaker_audio_urls: list[str] = []
            if self._s3_client and self._s3_client.enabled:
                run_prefix = result.run_dir.name
                summary_uploaded = self._s3_client.upload_file(
                    str(result.summary_path), f"{run_prefix}/{result.summary_path.name}"
                )
                if summary_uploaded:
                    summary_url = summary_uploaded.url
                speakers_uploaded = self._s3_client.upload_file(
                    str(result.speakers_path), f"{run_prefix}/{result.speakers_path.name}"
                )
                if speakers_uploaded:
                    speakers_url = speakers_uploaded.url
                uploaded = self._s3_client.upload_file(
                    str(result.audio_path), f"{run_prefix}/{result.audio_path.name}"
                )
                if uploaded:
                    audio_url = uploaded.url
                translated_uploaded = self._s3_client.upload_file(
                    str(result.translated_text_path),
                    f"{run_prefix}/{result.translated_text_path.name}",
                )
                if translated_uploaded:
                    translated_url = translated_uploaded.url
                transcript_uploaded = self._s3_client.upload_file(
                    str(result.transcript_path),
                    f"{run_prefix}/{result.transcript_path.name}",
                )
                if transcript_uploaded:
                    transcript_url = transcript_uploaded.url
                input_audio_uploaded = self._s3_client.upload_file(
                    str(result.input_audio_path),
                    f"{run_prefix}/{result.input_audio_path.name}",
                )
                if input_audio_uploaded:
                    input_audio_url = input_audio_uploaded.url
                for path in result.speaker_audio_paths:
                    uploaded_path = self._s3_client.upload_file(
                        str(path),
                        f"{run_prefix}/{path.name}",
                    )
                    if uploaded_path and uploaded_path.url:
                        speaker_audio_urls.append(uploaded_path.url)
            job.result = {
                "translated_path": str(result.translated_text_path),
                "summary_path": str(result.summary_path),
                "audio_path": str(result.audio_path),
                "run_dir": str(result.run_dir),
                "speakers_path": str(result.speakers_path),
                "transcript_path": str(result.transcript_path),
                "input_audio_path": str(result.input_audio_path),
                "speaker_audio_paths": [str(p) for p in result.speaker_audio_paths],
                "speaker_clip_segments": getattr(result, "speaker_clip_segments", {}),
                "speaker_clip_candidates": getattr(result, "speaker_clip_candidates", {}),
                "speaker_clip_selected": getattr(result, "speaker_clip_selected", {}),
                "speaker_audio_tags": getattr(result, "speaker_audio_tags", []),
                "summary_name": result.summary_path.name,
                "audio_name": result.audio_path.name,
                "translated_relative": str(result.translated_text_path.resolve().relative_to(runs_dir))
                if result.translated_text_path.resolve().is_relative_to(runs_dir)
                else result.translated_text_path.name,
                "transcript_relative": str(result.transcript_path.resolve().relative_to(runs_dir))
                if result.transcript_path.resolve().is_relative_to(runs_dir)
                else result.transcript_path.name,
                "input_audio_relative": str(result.input_audio_path.resolve().relative_to(runs_dir))
                if result.input_audio_path.resolve().is_relative_to(runs_dir)
                else result.input_audio_path.name,
                "speaker_audio_relatives": [
                    str(p.resolve().relative_to(runs_dir))
                    if p.resolve().is_relative_to(runs_dir)
                    else p.name
                    for p in result.speaker_audio_paths
                ],
                "summary_relative": str(result.summary_path.resolve().relative_to(runs_dir))
                if result.summary_path.resolve().is_relative_to(runs_dir)
                else result.summary_path.name,
                "audio_relative": str(result.audio_path.resolve().relative_to(runs_dir))
                if result.audio_path.resolve().is_relative_to(runs_dir)
                else result.audio_path.name,
                "speakers_relative": str(result.speakers_path.resolve().relative_to(runs_dir))
                if result.speakers_path.resolve().is_relative_to(runs_dir)
                else result.speakers_path.name,
                "summary_url": summary_url,
                "audio_url": audio_url,
                "speakers_url": speakers_url,
                "translated_url": translated_url,
                "transcript_url": transcript_url,
                "input_audio_url": input_audio_url,
                "speaker_audio_urls": speaker_audio_urls,
            }
            log_event(
                self._logger,
                "job_completed",
                job_id=job_id,
                finished_at=datetime.utcnow().isoformat() + "Z",
                run_dir=str(result.run_dir),
            )
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            self._logger.exception(
                json.dumps(
                    {
                        "event": "job_failed",
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "job_id": job_id,
                        "error": str(e),
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            job.finished_at = datetime.utcnow()
            try:
                progress_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            async with self._lock:
                self._running.discard(job_id)
                if job_id in self._queue_order:
                    self._queue_order.remove(job_id)
            self._save_state()

    def submit_speakers(self, job_id: str, speakers_json: str) -> PipelineJob:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")
        if not job.speaker_required:
            raise ValueError("Speaker input not required for this job")
        if not job._speaker_future:
            raise ValueError("Speaker input not available for this job")
        if job._speaker_future.done():
            raise ValueError("Speaker input already submitted")
        job.speaker_submitted = True
        job._speaker_future.set_result(speakers_json)
        self._save_state()
        return job

    def update_job_result(self, job_id: str, updates: dict[str, Any]) -> PipelineJob:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")
        if job.result is None:
            job.result = {}
        job.result.update(updates)
        self._save_state()
        return job

    def delete_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._jobs.pop(job_id)
            if job_id in self._queue_order:
                self._queue_order.remove(job_id)
            self._running.discard(job_id)
            self._save_state()

    def update_job_meta(
        self,
        job_id: str,
        note: Optional[str] = None,
        custom_name: Optional[str] = None,
        tags: Optional[list[str]] = None,
        published: Optional[bool] = None,
    ) -> PipelineJob:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")
        if note is not None:
            job.note = note.strip() if note else None
        if custom_name is not None:
            job.custom_name = custom_name.strip() if custom_name else None
        if tags is not None:
            if self._tags:
                filtered = [t for t in tags if t in self._tags]
            else:
                filtered = tags
            job.tags = [str(t) for t in filtered if str(t).strip()]
        if published is not None:
            job.published = bool(published)
        self._save_state()
        return job

    def reorder_queue(self, job_ids: list[str]) -> list[str]:
        current = [jid for jid in self._queue_order if jid in self._jobs]
        wanted = [jid for jid in job_ids if jid in current]
        remaining = [jid for jid in current if jid not in wanted]
        self._queue_order = wanted + remaining
        self._save_state()
        return list(self._queue_order)


    def save_state(self) -> None:
        self._save_state()

    def _load_state(self) -> None:
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        settings = data.get("settings", {}) if isinstance(data, dict) else {}
        if isinstance(settings, dict):
            self._parallel_enabled = bool(settings.get("parallel_enabled", self._parallel_enabled))
            self._max_concurrent = max(1, min(5, int(settings.get("max_concurrent", self._max_concurrent))))
            tags = settings.get("tags")
            if isinstance(tags, list):
                self.tags = [str(t) for t in tags if str(t).strip()]
            api_keys = settings.get("api_keys")
            if isinstance(api_keys, dict):
                self.api_keys = {str(k): str(v) for k, v in api_keys.items()}
            asset_selections = settings.get("asset_selections")
            if isinstance(asset_selections, dict):
                self.asset_selections = {str(k): str(v) for k, v in asset_selections.items()}
        stored_queue = data.get("queue_order") if isinstance(data, dict) else None
        if isinstance(stored_queue, list):
            self._queue_order = [str(item) for item in stored_queue if item]
        for payload in data.get("jobs", []) or []:
            if not isinstance(payload, dict):
                continue
            job = PipelineJob.from_state(payload)
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = job.error or "Server restarted before completion"
                job.finished_at = job.finished_at or datetime.utcnow()
            self._jobs[job.job_id] = job
        if self._queue_order:
            self._queue_order = [
                jid
                for jid in self._queue_order
                if self._jobs.get(jid, None) and self._jobs[jid].status == "queued"
            ]
        if not self._queue_order:
            self._queue_order = [
                j.job_id
                for j in sorted(self._jobs.values(), key=lambda x: x.created_at)
                if j.status == "queued"
            ]

    def _build_state_payload(self) -> dict[str, Any]:
        return {
            "settings": {
                "parallel_enabled": self._parallel_enabled,
                "max_concurrent": self._max_concurrent,
                "tags": list(self._tags),
                "api_keys": dict(self._api_keys),
                "asset_selections": dict(self._asset_selections),
            },
            "queue_order": list(self._queue_order),
            "jobs": [job.to_state() for job in self._jobs.values()],
        }

    def _write_state_payload(self, payload: dict[str, Any]) -> None:
        if not self._state_path:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _save_state_async(self) -> None:
        while True:
            payload = self._build_state_payload()
            try:
                await asyncio.to_thread(self._write_state_payload, payload)
            except Exception:
                return
            if self._save_pending:
                self._save_pending = False
                continue
            return

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop:
            if self._save_task and not self._save_task.done():
                self._save_pending = True
                return
            self._save_task = loop.create_task(self._save_state_async())
            return
        try:
            payload = self._build_state_payload()
            self._write_state_payload(payload)
        except Exception:
            return


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _extract_detail_path(detail: str) -> Optional[str]:
    for line in detail.splitlines():
        if line.strip().lower().startswith("file:"):
            return line.split(":", 1)[1].strip()
    return None
