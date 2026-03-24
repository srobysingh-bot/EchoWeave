"""Typed models for Music Assistant API responses used by EchoWeave."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class MAServerInfo(BaseModel):
    """Subset of MA ``/api`` response used for connectivity checks."""
    server_id: str = ""
    server_version: str = ""
    schema_version: int = 0
    # Allow extra fields so we don't break on new MA releases.
    model_config = {"extra": "allow"}


class MAStreamDetails(BaseModel):
    """Stream resolution details for a queue item."""
    url: str = ""
    content_type: str = ""
    sample_rate: int = 0
    bit_depth: int = 0
    model_config = {"extra": "allow"}


class MAQueueItem(BaseModel):
    """A single item in an MA player queue."""
    queue_item_id: str = Field("", alias="queue_item_id")
    queue_id: str = ""
    name: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    uri: str = ""
    image_url: str = ""
    streamdetails: Optional[MAStreamDetails] = None
    model_config = {"extra": "allow", "populate_by_name": True}


class MAPlayer(BaseModel):
    """Simplified MA player representation."""
    player_id: str = ""
    name: str = ""
    available: bool = False
    model_config = {"extra": "allow"}
