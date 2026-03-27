from __future__ import annotations

from datetime import datetime

from app.storage.models import ConnectorRecord


class MemoryStore:
    def __init__(self) -> None:
        self.connectors: dict[str, ConnectorRecord] = {}

    def upsert_connector(self, record: ConnectorRecord) -> ConnectorRecord:
        record.last_seen = datetime.utcnow()
        self.connectors[record.connector_id] = record
        return record

    def get_connector(self, connector_id: str) -> ConnectorRecord | None:
        return self.connectors.get(connector_id)


store = MemoryStore()
