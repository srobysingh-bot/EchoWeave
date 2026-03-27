from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EdgeCommandEnvelope(BaseModel):
    type: Literal["command"] = "command"
    request_id: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EdgeResponseEnvelope(BaseModel):
    type: Literal["response"] = "response"
    request_id: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class PreparedPlayContext(BaseModel):
    queue_id: str
    queue_item_id: str
    title: str
    subtitle: str = ""
    image_url: str = ""
    origin_stream_path: str
    content_type: str = "audio/mpeg"
