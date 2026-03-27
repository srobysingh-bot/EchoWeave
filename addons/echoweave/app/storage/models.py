"""Typed persistent config and state models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PlayState(str, Enum):
    """Alexa playback state tracked by the session store."""
    IDLE = "IDLE"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class SessionRecord(BaseModel):
    """Persisted playback session for a single Alexa device."""
    device_id: str
    queue_id: str = ""
    current_track_token: str = ""
    previous_track_token: str = ""
    expected_next_token: str = ""
    last_event_type: str = ""
    last_event_timestamp: Optional[datetime] = None
    play_state: PlayState = PlayState.IDLE
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HealthCacheEntry(BaseModel):
    """Cached result of a single health check."""
    key: str
    status: str  # "ok", "warn", "fail", "unknown"
    message: str = ""
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class HealthCacheModel(BaseModel):
    """Aggregate health check cache."""
    checks: list[HealthCacheEntry] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SkillMetadata(BaseModel):
    """Persisted Alexa skill metadata."""
    skill_id: str = ""
    endpoint_url: str = ""
    locale: str = ""
    last_deployed_at: Optional[datetime] = None
    interaction_model_version: str = ""
    manual_skill_configured: bool = False  # True if user manually entered skill_id
    manual_ask_setup: bool = False  # True if user manually managed ASK setup


class PersistedConfig(BaseModel):
    """User-facing config snapshot saved to disk."""
    mode: str = "legacy"
    backend_url: str = ""
    worker_base_url: str = ""
    tunnel_base_url: str = ""
    edge_shared_secret: str = ""
    connector_id: str = ""
    connector_secret: str = ""
    tenant_id: str = ""
    home_id: str = ""
    alexa_source_queue_id: str = ""
    ma_base_url: str = ""
    ma_token: str = ""
    public_base_url: str = ""
    stream_base_url: str = ""
    locale: str = "en-US"
    aws_default_region: str = "us-east-1"
    log_level: str = "info"
    debug: bool = False
    allow_insecure_local_test: bool = False
    updated_at: datetime = Field(default_factory=datetime.utcnow)
