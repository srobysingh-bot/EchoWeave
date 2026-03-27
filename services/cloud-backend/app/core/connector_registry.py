from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

from app.storage.memory_store import store
from app.storage.models import ConnectorCommandRecord, ConnectorRecord


class ConnectorRegistry:
    def register(
        self,
        *,
        connector_id: str,
        tenant_id: str,
        home_id: str,
        connector_secret: str,
        capabilities: dict,
    ) -> ConnectorRecord:
        record = ConnectorRecord(
            connector_id=connector_id,
            tenant_id=tenant_id,
            home_id=home_id,
            connector_secret=connector_secret,
            capabilities=capabilities or {},
            status="registered",
            last_heartbeat_status="never",
        )
        return store.upsert_connector(record)

    def heartbeat(self, *, connector_id: str, connector_secret: str, status: str) -> ConnectorRecord | None:
        record = store.get_connector(connector_id)
        if record is None:
            return None
        if record.connector_secret != connector_secret:
            return None
        record.status = status
        record.last_heartbeat_status = status
        record.last_seen = datetime.utcnow()
        return store.upsert_connector(record)

    def get(self, connector_id: str) -> ConnectorRecord | None:
        return store.get_connector(connector_id)

    def find_by_tenant_home(self, *, tenant_id: str, home_id: str) -> ConnectorRecord | None:
        for record in store.connectors.values():
            if record.tenant_id == tenant_id and record.home_id == home_id:
                return record
        return None

    def find_default(self) -> ConnectorRecord | None:
        if not store.connectors:
            return None
        records = sorted(store.connectors.values(), key=lambda item: item.last_seen, reverse=True)
        for record in records:
            if record.last_heartbeat_status == "online":
                return record
        return records[0]

    def enqueue_command(
        self,
        *,
        connector_id: str,
        tenant_id: str,
        home_id: str,
        command_type: str,
        payload: dict,
    ) -> ConnectorCommandRecord:
        command = ConnectorCommandRecord(
            command_id=str(uuid4()),
            connector_id=connector_id,
            tenant_id=tenant_id,
            home_id=home_id,
            command_type=command_type,
            payload=payload,
        )
        store.enqueue_command(connector_id, command.model_dump(mode="json"))
        return command

    def claim_next_command(self, *, connector_id: str, connector_secret: str) -> ConnectorCommandRecord | None:
        connector = self.get(connector_id)
        if connector is None or connector.connector_secret != connector_secret:
            return None
        raw = store.claim_next_command(connector_id)
        if raw is None:
            return None
        command = ConnectorCommandRecord.model_validate(raw)
        command.claimed_at = datetime.utcnow()
        store.command_by_id[command.command_id] = command.model_dump(mode="json")
        return command

    def ack_command(
        self,
        *,
        connector_id: str,
        connector_secret: str,
        command_id: str,
        success: bool,
        message: str,
        result: dict,
    ) -> ConnectorCommandRecord | None:
        connector = self.get(connector_id)
        if connector is None or connector.connector_secret != connector_secret:
            return None
        raw = store.get_command(command_id)
        if raw is None:
            return None
        command = ConnectorCommandRecord.model_validate(raw)
        if command.connector_id != connector_id:
            return None
        command.acked_at = datetime.utcnow()
        command.ack_success = success
        command.ack_message = message or ""
        if result:
            command.payload["ack_result"] = result
        command.status = "acked" if success else "failed"
        store.command_by_id[command.command_id] = command.model_dump(mode="json")
        return command

    def get_command(self, command_id: str) -> ConnectorCommandRecord | None:
        raw = store.get_command(command_id)
        if raw is None:
            return None
        return ConnectorCommandRecord.model_validate(raw)

    async def wait_for_ack(self, command_id: str, timeout_seconds: float = 6.0) -> ConnectorCommandRecord | None:
        interval = 0.2
        waited = 0.0
        while waited < timeout_seconds:
            command = self.get_command(command_id)
            if command and command.status in {"acked", "failed"}:
                return command
            await asyncio.sleep(interval)
            waited += interval

        command = self.get_command(command_id)
        if command and command.status == "pending":
            command.status = "timeout"
            command.ack_success = False
            command.ack_message = "ack-timeout"
            store.command_by_id[command.command_id] = command.model_dump(mode="json")
            return command
        return command


registry = ConnectorRegistry()
