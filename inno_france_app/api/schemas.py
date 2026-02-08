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


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    user_id: int
    username: str


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
    queue_position: Optional[int] = None
    note: Optional[str] = None
    custom_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    published: bool = False


class PipelineListResponse(BaseModel):
    jobs: list[PipelineJobResponse]
    max_concurrent: int
    parallel_enabled: bool


class SettingsResponse(BaseModel):
    parallel_enabled: bool
    max_concurrent: int
    max_queued: int
    tags: list[str] = Field(default_factory=list)
    provider_availability: dict[str, bool] = Field(default_factory=dict)
    provider_key_source: dict[str, str] = Field(default_factory=dict)
    asset_options: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    asset_selections: dict[str, str] = Field(default_factory=dict)


class SettingsUpdate(BaseModel):
    parallel_enabled: Optional[bool] = None
    max_concurrent: Optional[int] = None
    tags: Optional[list[str]] = None
    api_keys: Optional[dict[str, str]] = None
    asset_selections: Optional[dict[str, str]] = None


class SpeakersSubmitRequest(BaseModel):
    speakers_json: str


class SummaryUpdateRequest(BaseModel):
    text: str


class TranslationUpdateRequest(BaseModel):
    text: str


class QueueReorderRequest(BaseModel):
    job_ids: list[str]


class JobMetaUpdateRequest(BaseModel):
    note: Optional[str] = None
    custom_name: Optional[str] = None
    tags: Optional[list[str]] = None
    published: Optional[bool] = None
