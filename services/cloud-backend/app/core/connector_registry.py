from __future__ import annotations

from datetime import datetime

from app.storage.memory_store import store
from app.storage.models import ConnectorRecord


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


registry = ConnectorRegistry()
