from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.connector_registry import registry
from app.core.tenant_registry import tenant_registry
from app.storage.models import (
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterConnectorRequest,
    RegisterConnectorResponse,
)

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


@router.post("/register", response_model=RegisterConnectorResponse)
async def register_connector(payload: RegisterConnectorRequest) -> RegisterConnectorResponse:
    tenant_registry.mark_seen(payload.tenant_id)
    record = registry.register(
        connector_id=payload.connector_id,
        tenant_id=payload.tenant_id,
        home_id=payload.home_id,
        connector_secret=payload.connector_secret,
        capabilities=payload.capabilities,
    )
    return RegisterConnectorResponse(
        success=True,
        connector_id=record.connector_id,
        tenant_id=record.tenant_id,
        home_id=record.home_id,
        status=record.status,
    )


@router.post("/{connector_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(connector_id: str, payload: HeartbeatRequest) -> HeartbeatResponse:
    record = registry.heartbeat(
        connector_id=connector_id,
        connector_secret=payload.connector_secret,
        status=payload.status,
    )
    if record is None:
        raise HTTPException(status_code=401, detail="Unknown connector or invalid secret.")

    return HeartbeatResponse(
        success=True,
        connector_id=record.connector_id,
        status=record.last_heartbeat_status,
        last_seen=record.last_seen.isoformat() + "Z",
    )
