from fastapi.testclient import TestClient

from app.main import app


def test_connector_register():
    payload = {
        "connector_id": "connector-1",
        "tenant_id": "tenant-1",
        "home_id": "home-1",
        "connector_secret": "secret-1",
        "capabilities": {"ma": {"reachable": True}},
    }
    with TestClient(app) as client:
        resp = client.post("/v1/connectors/register", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["connector_id"] == "connector-1"
    assert data["status"] == "registered"
