from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConnectorRecord(BaseModel):
    connector_id: str
    tenant_id: str
    home_id: str
    connector_secret: str
    status: str = "registered"
    capabilities: dict = Field(default_factory=dict)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat_status: str = "never"


class RegisterConnectorRequest(BaseModel):
    connector_id: str
    tenant_id: str
    home_id: str
    connector_secret: str
    capabilities: dict = Field(default_factory=dict)


class RegisterConnectorResponse(BaseModel):
    success: bool
    connector_id: str
    tenant_id: str
    home_id: str
    status: str


class HeartbeatRequest(BaseModel):
    connector_secret: str
    status: str = "online"


class HeartbeatResponse(BaseModel):
    success: bool
    connector_id: str
    status: str
    last_seen: str


class ConnectorCommandRecord(BaseModel):
    command_id: str
    connector_id: str
    tenant_id: str
    home_id: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "acked", "failed", "timeout"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    claimed_at: datetime | None = None
    acked_at: datetime | None = None
    ack_success: bool | None = None
    ack_message: str = ""


class ConnectorCommandResponse(BaseModel):
    success: bool
    connector_id: str
    command_id: str
    command_type: str
    payload: dict[str, Any]
    created_at: str


class ConnectorCommandPollRequest(BaseModel):
    connector_secret: str


class ConnectorCommandAckRequest(BaseModel):
    connector_secret: str
    success: bool
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class ConnectorCommandAckResponse(BaseModel):
    success: bool
    connector_id: str
    command_id: str
    status: str
    ack_success: bool
    ack_message: str
