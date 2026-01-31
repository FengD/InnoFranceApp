from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class PipelineStartRequest(BaseModel):
    youtube_url: Optional[str] = None
    audio_url: Optional[str] = None
    audio_path: Optional[str] = None
    provider: str = "openai"
    model_name: str
    language: str = "fr"
    chunk_length: int = 30
    speed: float = 1.0
    yt_cookies_file: Optional[str] = None
    yt_cookies_from_browser: Optional[str] = None
    yt_user_agent: Optional[str] = None
    yt_proxy: Optional[str] = None
    manual_speakers: bool = False


class StepEvent(BaseModel):
    step: str
    status: str
    message: str
    detail: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class PipelineJobResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    steps: list[StepEvent] = Field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    speaker_required: bool = False
    speaker_submitted: bool = False


class PipelineListResponse(BaseModel):
    jobs: list[PipelineJobResponse]
    max_concurrent: int
    parallel_enabled: bool


class SettingsResponse(BaseModel):
    parallel_enabled: bool
    max_concurrent: int
    max_queued: int


class SettingsUpdate(BaseModel):
    parallel_enabled: Optional[bool] = None
    max_concurrent: Optional[int] = None


class SpeakersSubmitRequest(BaseModel):
    speakers_json: str


class SummaryUpdateRequest(BaseModel):
    text: str
