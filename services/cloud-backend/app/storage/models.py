from __future__ import annotations

from datetime import datetime

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
