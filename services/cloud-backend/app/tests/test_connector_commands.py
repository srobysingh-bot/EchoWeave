from fastapi.testclient import TestClient

from app.core.connector_registry import registry
from app.main import app
from app.storage.memory_store import store


def test_connector_command_poll_and_ack_roundtrip():
    store.connectors.clear()
    store.commands.clear()
    store.command_by_id.clear()

    with TestClient(app) as client:
        client.post(
            "/v1/connectors/register",
            json={
                "connector_id": "connector-cmd-1",
                "tenant_id": "tenant-1",
                "home_id": "home-1",
                "connector_secret": "secret-1",
                "capabilities": {},
            },
        )

        enqueued = registry.enqueue_command(
            connector_id="connector-cmd-1",
            tenant_id="tenant-1",
            home_id="home-1",
            command_type="play",
            payload={"action": "play"},
        )

        poll_resp = client.post(
            "/v1/connectors/connector-cmd-1/commands/next",
            json={"connector_secret": "secret-1"},
        )
        assert poll_resp.status_code == 200
        payload = poll_resp.json()
        assert payload["command_id"] == enqueued.command_id
        assert payload["command_type"] == "play"

        ack_resp = client.post(
            f"/v1/connectors/connector-cmd-1/commands/{enqueued.command_id}/ack",
            json={
                "connector_secret": "secret-1",
                "success": True,
                "message": "play-started",
                "result": {"player_id": "player-1"},
            },
        )
        assert ack_resp.status_code == 200
        ack_payload = ack_resp.json()
        assert ack_payload["ack_success"] is True
        assert ack_payload["status"] == "acked"
