from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from ..config import load_app_config
from .queue import PipelineQueue
from .schemas import (
    PipelineJobResponse,
    PipelineListResponse,
    PipelineStartRequest,
    SettingsResponse,
    SettingsUpdate,
    StepEvent,
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

    queue = PipelineQueue(parallel_enabled=False, max_concurrent=1)

    def _allowed_path(relative_path: str) -> Path:
        if not relative_path or ".." in relative_path or relative_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid path")
        rel = relative_path.strip("/")
        if not rel:
            raise HTTPException(status_code=400, detail="Invalid path")
        config = load_app_config(config_path)
        for base in (config.output_dir, config.runs_dir):
            full = (base / rel).resolve()
            try:
                if full.exists() and full.is_file() and full.is_relative_to(base.resolve()):
                    return full
            except ValueError:
                continue
        raise HTTPException(status_code=404, detail="File not found")

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
        return get_settings()

    @app.post("/api/pipeline/start", response_model=PipelineJobResponse)
    async def start_pipeline(req: PipelineStartRequest) -> PipelineJobResponse:
        sources = [v for v in (req.youtube_url, req.audio_url, req.audio_path) if v]
        if len(sources) != 1:
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one of youtube_url, audio_url, or audio_path.",
            )
        try:
            job = await queue.enqueue(req, config_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return PipelineJobResponse(**job.to_response())

    @app.get("/api/pipeline/jobs", response_model=PipelineListResponse)
    def list_pipeline_jobs() -> PipelineListResponse:
        return PipelineListResponse(
            jobs=[PipelineJobResponse(**j) for j in queue.list_jobs()],
            max_concurrent=queue.max_concurrent,
            parallel_enabled=queue.parallel_enabled,
        )

    @app.get("/api/pipeline/jobs/{job_id}", response_model=PipelineJobResponse)
    def get_pipeline_job(job_id: str) -> PipelineJobResponse:
        job = queue.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
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
