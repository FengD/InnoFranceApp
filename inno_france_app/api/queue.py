from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from ..config import load_app_config
from ..db import AppDatabase, SettingsRecord
from ..logging_utils import log_event, setup_logging
from ..s3 import S3Client
from ..pipeline import InnoFrancePipeline, PipelineResult
from .schemas import PipelineStartRequest, StepEvent


@dataclass
class PipelineJob:
    job_id: str
    user_id: int
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
            "user_id": self.user_id,
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
            user_id=int(payload.get("user_id", 0)),
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


@dataclass
class UserSettings:
    parallel_enabled: bool = False
    max_concurrent: int = 1
    tags: list[str] = field(default_factory=list)
    api_keys: dict[str, str] = field(default_factory=dict)
    asset_selections: dict[str, str] = field(default_factory=dict)


class PipelineQueue:
    MAX_QUEUED = 10

    def __init__(
        self,
        db: AppDatabase,
        parallel_enabled: bool = False,
        max_concurrent: int = 1,
        s3_client: Optional[S3Client] = None,
        runs_dir: Optional[Path] = None,
    ) -> None:
        self._db = db
        self._parallel_enabled = parallel_enabled
        self._max_concurrent = max(1, min(5, max_concurrent))
        self._jobs: dict[str, PipelineJob] = {}
        self._running_by_user: dict[int, set[str]] = {}
        self._queue_order_by_user: dict[int, list[str]] = {}
        self._settings_by_user: dict[int, UserSettings] = {}
        self._save_task: Optional[asyncio.Task[None]] = None
        self._save_pending = False
        self._lock = asyncio.Lock()
        self._s3_client = s3_client
        self._runs_dir = runs_dir
        self._logger = setup_logging()
        self._load_state()

    def _settings_for_user(self, user_id: int) -> UserSettings:
        if user_id not in self._settings_by_user:
            self._settings_by_user[user_id] = UserSettings(
                parallel_enabled=self._parallel_enabled,
                max_concurrent=self._max_concurrent,
            )
        return self._settings_by_user[user_id]

    def _slots_available(self, user_id: int) -> int:
        settings = self._settings_for_user(user_id)
        running = self._running_by_user.get(user_id, set())
        if settings.parallel_enabled:
            return settings.max_concurrent - len(running)
        return 1 - len(running) if running else 1

    def get_settings(self, user_id: int) -> UserSettings:
        return self._settings_for_user(user_id)

    def update_settings(
        self,
        user_id: int,
        parallel_enabled: Optional[bool] = None,
        max_concurrent: Optional[int] = None,
        tags: Optional[list[str]] = None,
        api_keys: Optional[dict[str, str]] = None,
        asset_selections: Optional[dict[str, str]] = None,
    ) -> UserSettings:
        settings = self._settings_for_user(user_id)
        if parallel_enabled is not None:
            settings.parallel_enabled = bool(parallel_enabled)
        if max_concurrent is not None:
            settings.max_concurrent = max(1, min(5, int(max_concurrent)))
        if tags is not None:
            normalized: list[str] = []
            for item in tags:
                label = str(item).strip()
                if not label:
                    continue
                if label not in normalized:
                    normalized.append(label)
            settings.tags = normalized
        if api_keys is not None:
            normalized: dict[str, str] = {}
            for key, raw in (api_keys or {}).items():
                name = str(key).strip()
                if not name:
                    continue
                val = str(raw).strip()
                if val:
                    normalized[name] = val
            settings.api_keys = normalized
        if asset_selections is not None:
            normalized: dict[str, str] = {}
            for key, raw in (asset_selections or {}).items():
                name = str(key).strip()
                if not name:
                    continue
                val = str(raw).strip()
                if val:
                    normalized[name] = val
            settings.asset_selections = normalized
        self._save_state()
        return settings

    def get_api_key(self, user_id: int, provider: str) -> Optional[str]:
        return self._settings_for_user(user_id).api_keys.get(provider)

    def _queue_position(self, user_id: int, job_id: str) -> Optional[int]:
        queue = self._queue_order_by_user.get(user_id, [])
        try:
            return queue.index(job_id)
        except ValueError:
            return None

    def queue_position(self, user_id: int, job_id: str) -> Optional[int]:
        return self._queue_position(user_id, job_id)

    def _can_start(self, job: PipelineJob) -> bool:
        slots = self._slots_available(job.user_id)
        if slots <= 0:
            return False
        queue = self._queue_order_by_user.get(job.user_id, [])
        if job.job_id not in queue:
            return True
        allowed = queue[: (slots if self._settings_for_user(job.user_id).parallel_enabled else 1)]
        return job.job_id in allowed

    def list_jobs(self, user_id: int, include_steps: bool = True) -> list[dict[str, Any]]:
        response: list[dict[str, Any]] = []
        ordered_ids: list[str] = []
        queue_ids = self._queue_order_by_user.get(user_id, [])
        ordered_ids.extend([jid for jid in queue_ids if jid in self._jobs])
        running = [
            j.job_id
            for j in sorted(
                self._jobs.values(),
                key=lambda x: x.started_at or x.created_at,
            )
            if j.status == "running" and j.job_id not in ordered_ids and j.user_id == user_id
        ]
        ordered_ids.extend(running)
        remaining = [
            j.job_id
            for j in sorted(
                self._jobs.values(),
                key=lambda x: x.finished_at or x.created_at,
                reverse=True,
            )
            if j.job_id not in ordered_ids and j.user_id == user_id
        ]
        ordered_ids.extend(remaining)
        for job_id in ordered_ids:
            job = self._jobs.get(job_id)
            if not job:
                continue
            response.append(
                job.to_response(
                    include_steps=include_steps,
                    queue_position=self._queue_position(user_id, job_id),
                )
            )
        return response

    def get_job(self, job_id: str) -> Optional[PipelineJob]:
        return self._jobs.get(job_id)

    async def enqueue(
        self,
        req: PipelineStartRequest,
        user_id: int,
        config_path: Optional[Any] = None,
    ) -> PipelineJob:
        async with self._lock:
            queued = sum(
                1
                for j in self._jobs.values()
                if j.status in ("queued", "running") and j.user_id == user_id
            )
            if queued >= self.MAX_QUEUED:
                raise ValueError(f"Queue full: at most {self.MAX_QUEUED} pipelines allowed (queued + running)")

            job_id = str(uuid.uuid4())
            progress_queue: asyncio.Queue[Optional[StepEvent]] = asyncio.Queue()

            def on_progress(step: str, status: str, message: str, detail: Optional[str] = None) -> None:
                ev = StepEvent(step=step, status=status, message=message, detail=detail)
                job = self._jobs.get(job_id)
                if job:
                    job.steps.append(ev)
                    if status == "completed" and detail and self._runs_dir:
                        rel_path = _extract_detail_path(detail)
                        if rel_path:
                            resolved_path = (self._runs_dir / rel_path).resolve()
                            job.result = job.result or {}
                            if step == "translate":
                                job.result["translated_path"] = str(resolved_path)
                                try:
                                    job.result["translated_relative"] = str(
                                        resolved_path.relative_to(self._runs_dir.resolve())
                                    )
                                except ValueError:
                                    job.result["translated_relative"] = resolved_path.name
                            elif step == "polish":
                                job.result["polished_path"] = str(resolved_path)
                                try:
                                    job.result["polished_relative"] = str(
                                        resolved_path.relative_to(self._runs_dir.resolve())
                                    )
                                except ValueError:
                                    job.result["polished_relative"] = resolved_path.name
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
                user_id=user_id,
                status="queued",
                created_at=datetime.utcnow(),
                _progress_queue=progress_queue,
                speaker_required=bool(req.manual_speakers),
            )
            if req.manual_speakers:
                job._speaker_future = asyncio.Future()
            self._jobs[job_id] = job
            self._queue_order_by_user.setdefault(user_id, []).append(job_id)
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
                if self._can_start(job):
                    queue = self._queue_order_by_user.get(job.user_id, [])
                    if job_id in queue:
                        queue.remove(job_id)
                    self._running_by_user.setdefault(job.user_id, set()).add(job_id)
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
                provider_api_key=self.get_api_key(job.user_id, req.provider),
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
            polished_url = None
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
                polished_uploaded = self._s3_client.upload_file(
                    str(result.polished_text_path),
                    f"{run_prefix}/{result.polished_text_path.name}",
                )
                if polished_uploaded:
                    polished_url = polished_uploaded.url
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
                "polished_path": str(result.polished_text_path),
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
                "polished_relative": str(result.polished_text_path.resolve().relative_to(runs_dir))
                if result.polished_text_path.resolve().is_relative_to(runs_dir)
                else result.polished_text_path.name,
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
                "polished_url": polished_url,
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
                self._running_by_user.get(job.user_id, set()).discard(job_id)
                queue = self._queue_order_by_user.get(job.user_id, [])
                if job_id in queue:
                    queue.remove(job_id)
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
            for queue in self._queue_order_by_user.values():
                if job_id in queue:
                    queue.remove(job_id)
            for running in self._running_by_user.values():
                running.discard(job_id)
            self._db.delete_job(job_id)
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
            settings = self._settings_for_user(job.user_id)
            if settings.tags:
                filtered = [t for t in tags if t in settings.tags]
            else:
                filtered = tags
            job.tags = [str(t) for t in filtered if str(t).strip()]
        if published is not None:
            job.published = bool(published)
        self._save_state()
        return job

    def reorder_queue(self, user_id: int, job_ids: list[str]) -> list[str]:
        current = [jid for jid in self._queue_order_by_user.get(user_id, []) if jid in self._jobs]
        wanted = [jid for jid in job_ids if jid in current]
        remaining = [jid for jid in current if jid not in wanted]
        self._queue_order_by_user[user_id] = wanted + remaining
        self._save_state()
        return list(self._queue_order_by_user[user_id])


    def save_state(self) -> None:
        self._save_state()

    def _load_state(self) -> None:
        jobs = self._db.load_jobs()
        for payload in jobs:
            job = PipelineJob.from_state(payload)
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = job.error or "Server restarted before completion"
                job.finished_at = job.finished_at or datetime.utcnow()
            self._jobs[job.job_id] = job
        self._settings_by_user = {
            user_id: UserSettings(
                parallel_enabled=settings.parallel_enabled,
                max_concurrent=settings.max_concurrent,
                tags=settings.tags,
                api_keys=settings.api_keys,
                asset_selections=settings.asset_selections,
            )
            for user_id, settings in self._db.load_all_settings().items()
        }
        self._queue_order_by_user = self._db.load_queue_order()
        for user_id, queue in list(self._queue_order_by_user.items()):
            filtered = [
                jid
                for jid in queue
                if self._jobs.get(jid, None) and self._jobs[jid].status == "queued"
            ]
            self._queue_order_by_user[user_id] = filtered
        for job in sorted(self._jobs.values(), key=lambda x: x.created_at):
            if job.status != "queued":
                continue
            queue = self._queue_order_by_user.setdefault(job.user_id, [])
            if job.job_id not in queue:
                queue.append(job.job_id)

    def _write_state_payload(self) -> None:
        for job in self._jobs.values():
            payload = job.to_state()
            self._db.save_job(payload)
            self._db.save_steps(job.job_id, payload.get("steps", []))
        for user_id, settings in self._settings_by_user.items():
            self._db.save_settings(
                user_id,
                SettingsRecord(
                    parallel_enabled=settings.parallel_enabled,
                    max_concurrent=settings.max_concurrent,
                    tags=settings.tags,
                    api_keys=settings.api_keys,
                    asset_selections=settings.asset_selections,
                ),
            )
        for user_id, queue in self._queue_order_by_user.items():
            self._db.save_queue_order(user_id, queue)

    async def _save_state_async(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._write_state_payload)
            except Exception:
                return
            if self._save_pending:
                self._save_pending = False
                continue
            return

    def _save_state(self) -> None:
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
            self._write_state_payload()
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
