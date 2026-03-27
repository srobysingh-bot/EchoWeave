from __future__ import annotations

import pytest

from app.connector.client import ConnectorClient
from app.connector.command_dispatch import execute_connector_command


@pytest.mark.anyio
async def test_connector_client_poll_and_ack(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload
            self.text = "ok"

        def json(self):
            return self._payload

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def post(self, url, json):
            calls.append((url, str(json)))
            if url.endswith("/commands/next"):
                return _FakeResponse(
                    200,
                    {
                        "success": True,
                        "connector_id": "connector-01",
                        "command_id": "cmd-1",
                        "command_type": "play",
                        "payload": {"action": "play"},
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                )
            return _FakeResponse(200, {"success": True})

    monkeypatch.setattr("app.connector.client.httpx.AsyncClient", lambda timeout=10: _FakeAsyncClient())

    client = ConnectorClient(
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
    )

    command = await client.poll_next_command()
    assert command is not None
    assert command["command_id"] == "cmd-1"

    ok = await client.ack_command(command_id="cmd-1", success=True, message="play-started", result={"ok": True})
    assert ok is True
    assert calls[0][0] == "https://cloud.example.com/v1/connectors/connector-01/commands/next"
    assert calls[1][0] == "https://cloud.example.com/v1/connectors/connector-01/commands/cmd-1/ack"


@pytest.mark.anyio
async def test_execute_connector_command_play_success():
    class _FakeMAClient:
        async def execute_play_command(self, queue_id=None):
            return True, "play-started"

    command = {
        "command_id": "cmd-1",
        "command_type": "play",
        "payload": {"action": "play", "queue_id": "queue-1"},
    }
    success, message, result = await execute_connector_command(command, _FakeMAClient())
    assert success is True
    assert message == "play-started"
    assert result["queue_id"] == "queue-1"
