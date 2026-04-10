from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.service_registry import registry
from app.main import create_app


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code = status_code
        self.text = text


captured_register_payload = {}


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def post(self, url, json, headers):
        captured_register_payload["url"] = url
        captured_register_payload["json"] = json
        captured_register_payload["headers"] = headers
        return _FakeResponse(200, "ok")


def _set_edge_env(monkeypatch):
    monkeypatch.setenv("ECHOWEAVE_MODE", "edge")
    monkeypatch.setenv("ECHOWEAVE_WORKER_BASE_URL", "https://worker.example.com")
    monkeypatch.setenv("ECHOWEAVE_TUNNEL_BASE_URL", "https://origin.example.com")
    monkeypatch.setenv("ECHOWEAVE_EDGE_SHARED_SECRET", "edge-secret")
    monkeypatch.setenv("ECHOWEAVE_CONNECTOR_ID", "conn-a")
    monkeypatch.setenv("ECHOWEAVE_CONNECTOR_SECRET", "conn-secret")
    monkeypatch.setenv("ECHOWEAVE_TENANT_ID", "tenant-a")
    monkeypatch.setenv("ECHOWEAVE_HOME_ID", "home-a")
    monkeypatch.setenv("ECHOWEAVE_ALEXA_SOURCE_QUEUE_ID", "queue-a")
    monkeypatch.setenv("ECHOWEAVE_MA_BASE_URL", "http://ma.local:8095")
    monkeypatch.setenv("ECHOWEAVE_MA_TOKEN", "token")


def _mock_edge_startup(monkeypatch):
    async def _edge_start_noop(self):
        return None

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda timeout=10: _FakeAsyncClient())
    monkeypatch.setattr("app.edge.client_ws.EdgeConnectorWSClient.start", _edge_start_noop)


def test_create_app_does_not_mount_alexa_router_in_edge_mode(monkeypatch):
    _set_edge_env(monkeypatch)

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/alexa" not in paths
    assert "/alexa/intents" in paths
    assert "/edge/stream/{queue_id}/{queue_item_id}" in paths


def test_edge_intents_probe_returns_provider_contract(monkeypatch):
    _set_edge_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/alexa/intents")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("invocationName") == "music assistant"
    intents = payload.get("intents")
    assert isinstance(intents, list)
    assert payload.get("bridgeMode") is None
    assert any(item.get("intent") == "PlayAudio" for item in intents)
    resume_intent = next((item for item in intents if item.get("intent") == "AMAZON.ResumeIntent"), {})
    assert "play audio" in (resume_intent.get("utterances") or [])


def test_edge_intents_probe_state_debug_endpoint(monkeypatch):
    _set_edge_env(monkeypatch)
    _mock_edge_startup(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        probe_resp = client.get("/alexa/intents")
        assert probe_resp.status_code == 200

        debug_resp = client.get("/debug/alexa-probe")
        assert debug_resp.status_code == 200
        payload = debug_resp.json()
        assert payload.get("probe_id")
        assert payload.get("probe_time")
        assert isinstance(payload.get("payload", {}).get("intents"), list)


def test_edge_mode_startup_does_not_start_heartbeat_loop(monkeypatch):
    _set_edge_env(monkeypatch)

    async def _should_not_start(self):
        raise AssertionError("connector heartbeat should not start in edge mode")

    async def _edge_start_noop(self):
        return None

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda timeout=10: _FakeAsyncClient())
    monkeypatch.setattr("app.connector.heartbeat.HeartbeatRunner.start", _should_not_start)
    monkeypatch.setattr("app.edge.client_ws.EdgeConnectorWSClient.start", _edge_start_noop)

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/status")
        assert resp.status_code == 200

        assert registry.get_optional("connector_heartbeat") is None
        assert registry.get_optional("edge_connector_ws") is not None
        assert captured_register_payload["json"]["origin_base_url"] == "https://origin.example.com"


def test_ma_push_url_exempt_from_ui_auth(monkeypatch):
    _set_edge_env(monkeypatch)
    _mock_edge_startup(monkeypatch)
    monkeypatch.setenv("ECHOWEAVE_UI_PASSWORD", "secret")

    app = create_app()
    with TestClient(app) as client:
        # Non-exempt route should require basic auth.
        status_resp = client.get("/status")
        assert status_resp.status_code == 401

        # /ma/push-url must remain callable by MA provider without UI credentials.
        ma_resp = client.post("/ma/push-url", json={})
        assert ma_resp.status_code != 401
