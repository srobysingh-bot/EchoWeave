from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorPayload(BaseModel):
    code: str = "edge-error"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AddonStatePayload(BaseModel):
    mode: str = "edge"
    online: bool = False
    connector_id: str
    tenant_id: str
    home_id: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    queue_id: str = ""


class ConnectorHelloEnvelope(BaseModel):
    type: Literal["event"] = "event"
    event: Literal["connector_hello"] = "connector_hello"
    payload: AddonStatePayload


class ConnectorAuthEnvelope(BaseModel):
    type: Literal["event"] = "event"
    event: Literal["connector_auth"] = "connector_auth"
    payload: dict[str, Any] = Field(default_factory=dict)


class EdgeCommandEnvelope(BaseModel):
    type: Literal["command"] = "command"
    request_id: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EdgeRequestEnvelope(BaseModel):
    type: Literal["request"] = "request"
    request_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EdgeResponseEnvelope(BaseModel):
    type: Literal["response"] = "response"
    request_id: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: ErrorPayload | None = None


class PreparePlayPayload(BaseModel):
    queue_id: str = ""
    intent_name: str = ""
    query: str = ""


class PreparedPlayContext(BaseModel):
    queue_id: str
    queue_item_id: str
    title: str
    subtitle: str = ""
    image_url: str = ""
    origin_stream_path: str
    content_type: str = "audio/mpeg"
