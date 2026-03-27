from fastapi.testclient import TestClient

from app.main import app


def test_connector_heartbeat_updates_state():
    register_payload = {
        "connector_id": "connector-heartbeat",
        "tenant_id": "tenant-1",
        "home_id": "home-1",
        "connector_secret": "secret-abc",
        "capabilities": {},
    }
    with TestClient(app) as client:
        client.post("/v1/connectors/register", json=register_payload)
        hb_resp = client.post(
            "/v1/connectors/connector-heartbeat/heartbeat",
            json={"connector_secret": "secret-abc", "status": "online"},
        )

    assert hb_resp.status_code == 200
    data = hb_resp.json()
    assert data["success"] is True
    assert data["connector_id"] == "connector-heartbeat"
    assert data["status"] == "online"
    assert data["last_seen"]
