from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from ..config import load_app_config
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

    def to_response(self, include_steps: bool = True) -> dict[str, Any]:
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
        )
        return job


class PipelineQueue:
    MAX_QUEUED = 3

    def __init__(
        self,
        parallel_enabled: bool = False,
        max_concurrent: int = 1,
        state_path: Optional[Path] = None,
        s3_client: Optional[S3Client] = None,
    ) -> None:
        self._parallel_enabled = parallel_enabled
        self._max_concurrent = max(1, min(3, max_concurrent))
        self._jobs: dict[str, PipelineJob] = {}
        self._running: set[str] = set()
        self._lock = asyncio.Lock()
        self._state_path = state_path
        self._s3_client = s3_client
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
        self._max_concurrent = max(1, min(3, value))

    def _slots_available(self) -> int:
        if self._parallel_enabled:
            return self._max_concurrent - len(self._running)
        return 1 - len(self._running) if self._running else 1

    def list_jobs(self, include_steps: bool = True) -> list[dict[str, Any]]:
        return [
            j.to_response(include_steps=include_steps)
            for j in sorted(self._jobs.values(), key=lambda x: x.created_at)
        ]

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
                    self._save_state()
                try:
                    progress_queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass

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
            self._save_state()

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
                if self._slots_available() > 0:
                    self._running.add(job_id)
                    break
            await asyncio.sleep(0.5)

        job.status = "running"
        job.started_at = datetime.utcnow()
        self._save_state()

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
                on_progress=on_progress,
                manual_speakers=req.manual_speakers,
                speaker_future=job._speaker_future,
            )
            job.status = "completed"
            runs_dir = config.runs_dir.resolve()
            audio_url = None
            summary_url = None
            speakers_url = None
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
            job.result = {
                "translated_path": str(result.translated_text_path),
                "summary_path": str(result.summary_path),
                "audio_path": str(result.audio_path),
                "run_dir": str(result.run_dir),
                "speakers_path": str(result.speakers_path),
                "summary_name": result.summary_path.name,
                "audio_name": result.audio_path.name,
                "translated_relative": str(result.translated_text_path.resolve().relative_to(runs_dir))
                if result.translated_text_path.resolve().is_relative_to(runs_dir)
                else result.translated_text_path.name,
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
            }
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
        finally:
            job.finished_at = datetime.utcnow()
            try:
                progress_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            async with self._lock:
                self._running.discard(job_id)
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
            self._save_state()


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
            self._max_concurrent = max(1, min(3, int(settings.get("max_concurrent", self._max_concurrent))))
        for payload in data.get("jobs", []) or []:
            if not isinstance(payload, dict):
                continue
            job = PipelineJob.from_state(payload)
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = job.error or "Server restarted before completion"
                job.finished_at = job.finished_at or datetime.utcnow()
            self._jobs[job.job_id] = job

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "settings": {
                    "parallel_enabled": self._parallel_enabled,
                    "max_concurrent": self._max_concurrent,
                },
                "jobs": [job.to_state() for job in self._jobs.values()],
            }
            self._state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            return


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
