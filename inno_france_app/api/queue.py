from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from ..config import load_app_config
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

    def to_response(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "error": self.error,
            "steps": [s.model_dump() for s in self.steps],
            "result": self.result,
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
            self.steps.append(ev)
            yield ev


class PipelineQueue:
    MAX_QUEUED = 3

    def __init__(self, parallel_enabled: bool = False, max_concurrent: int = 1) -> None:
        self._parallel_enabled = parallel_enabled
        self._max_concurrent = max(1, min(3, max_concurrent))
        self._jobs: dict[str, PipelineJob] = {}
        self._running: set[str] = set()
        self._lock = asyncio.Lock()

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

    def list_jobs(self) -> list[dict[str, Any]]:
        return [j.to_response() for j in sorted(self._jobs.values(), key=lambda x: x.created_at)]

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
                try:
                    progress_queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass

            job = PipelineJob(
                job_id=job_id,
                status="queued",
                created_at=datetime.utcnow(),
                _progress_queue=progress_queue,
            )
            self._jobs[job_id] = job

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
            )
            job.status = "completed"
            out_dir = config.output_dir.resolve()
            job.result = {
                "summary_path": str(result.summary_path),
                "audio_path": str(result.audio_path),
                "run_dir": str(result.run_dir),
                "summary_name": result.summary_path.name,
                "audio_name": result.audio_path.name,
                "summary_relative": str(result.summary_path.resolve().relative_to(out_dir))
                if result.summary_path.resolve().is_relative_to(out_dir)
                else result.summary_path.name,
                "audio_relative": str(result.audio_path.resolve().relative_to(out_dir))
                if result.audio_path.resolve().is_relative_to(out_dir)
                else result.audio_path.name,
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
