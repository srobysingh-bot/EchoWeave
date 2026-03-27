from __future__ import annotations

from datetime import datetime

from app.storage.models import ConnectorRecord


class MemoryStore:
    def __init__(self) -> None:
        self.connectors: dict[str, ConnectorRecord] = {}
        self.commands: dict[str, list[dict]] = {}
        self.command_by_id: dict[str, dict] = {}

    def upsert_connector(self, record: ConnectorRecord) -> ConnectorRecord:
        record.last_seen = datetime.utcnow()
        self.connectors[record.connector_id] = record
        return record

    def get_connector(self, connector_id: str) -> ConnectorRecord | None:
        return self.connectors.get(connector_id)

    def enqueue_command(self, connector_id: str, command: dict) -> None:
        queue = self.commands.setdefault(connector_id, [])
        queue.append(command)
        self.command_by_id[command["command_id"]] = command

    def claim_next_command(self, connector_id: str) -> dict | None:
        queue = self.commands.get(connector_id, [])
        if not queue:
            return None
        return queue.pop(0)

    def get_command(self, command_id: str) -> dict | None:
        return self.command_by_id.get(command_id)


store = MemoryStore()
