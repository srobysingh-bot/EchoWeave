from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi.testclient import TestClient

from app.core.service_registry import registry
from app.main import create_app
from app.ma import router as ma_router


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


class _FakeConfigService:
    def __init__(self, *, is_edge_mode: bool = True, home_id: str = "home-a") -> None:
        self.settings = type(
            "_Settings",
            (),
            {
                "is_edge_mode": is_edge_mode,
                "home_id": home_id,
                "worker_base_url": "https://worker.example.com",
                "connector_id": "conn-a",
                "connector_secret": "conn-secret",
                "tenant_id": "tenant-a",
                "ma_base_url": "http://ma.local:8095",
                "ma_token": "token",
                "public_base_url": "https://public.example.com",
                "stream_base_url": "https://stream.example.com",
            },
        )()


class _FakeMAClient:
    def __init__(self, players: list[dict[str, object]]) -> None:
        self._players = players
        self.handoff_calls: list[dict[str, object]] = []

    async def get_players(self):
        return self._players

    async def handoff_playback_url(self, **kwargs):
        self.handoff_calls.append(kwargs)
        return True, "ok", {"handoff": "ok"}


class _CaptureLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message, *args, **kwargs):
        self.messages.append(str(message) % args if args else str(message))

    def warning(self, message, *args, **kwargs):
        self.messages.append(str(message) % args if args else str(message))

    def error(self, message, *args, **kwargs):
        self.messages.append(str(message) % args if args else str(message))

    def exception(self, message, *args, **kwargs):
        self.messages.append(str(message) % args if args else str(message))


def test_ma_push_url_rejects_prototype_skill_without_active_context(monkeypatch):
    _set_edge_env(monkeypatch)
    _mock_edge_startup(monkeypatch)
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(ma_router, "logger", capture_logger)

    async def _fail_if_worker_handoff_called(**kwargs):
        raise AssertionError("worker handoff must not run when Alexa request context is missing")

    monkeypatch.setattr(ma_router, "_request_worker_handoff", _fail_if_worker_handoff_called)

    app = create_app()
    with TestClient(app) as client:
        registry.register("config_service", _FakeConfigService())
        registry.register(
            "ma_client",
            _FakeMAClient([
                {"player_id": "echo-spot", "name": "Echo Spot", "provider": "alexa"},
            ]),
        )
        registry.register("alexa_probe_state", {"probe_id": "", "probe_time": ""})

        resp = client.post(
            "/ma/push-url",
            json={
                "streamUrl": "/flow/session-a/echo-spot/item-1",
                "provider": "alexa",
            },
        )

    assert resp.status_code == 409
    assert resp.json()["reason"] == "ui_play_requires_active_alexa_skill_session"
    assert resp.json()["message"] == "UI playback to Alexa requires an active Alexa skill session"
    assert any("alexa_request_context_missing" in message for message in capture_logger.messages)
    assert any("prototype_skill_response_skipped_no_active_request" in message for message in capture_logger.messages)
    assert any("ui_play_not_supported_without_active_skill_session" in message for message in capture_logger.messages)
    assert not any("ui_play_routed_to_alexa_provider_api" in message for message in capture_logger.messages)


def test_ma_push_url_rejects_prototype_skill_with_stale_probe_context(monkeypatch):
    _set_edge_env(monkeypatch)
    _mock_edge_startup(monkeypatch)
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(ma_router, "logger", capture_logger)

    async def _fail_if_worker_handoff_called(**kwargs):
        raise AssertionError("worker handoff must not run when Alexa probe context is stale")

    monkeypatch.setattr(ma_router, "_request_worker_handoff", _fail_if_worker_handoff_called)

    app = create_app()
    with TestClient(app) as client:
        registry.register("config_service", _FakeConfigService())
        registry.register(
            "ma_client",
            _FakeMAClient([
                {"player_id": "echo-spot", "name": "Echo Spot", "provider": "alexa"},
            ]),
        )
        registry.register(
            "alexa_probe_state",
            {
                "probe_id": "probe-stale",
                "probe_time": "2020-01-01T00:00:00+00:00",
            },
        )

        resp = client.post(
            "/ma/push-url",
            json={
                "streamUrl": "/flow/session-a/echo-spot/item-1",
                "provider": "alexa",
            },
        )

    assert resp.status_code == 409
    assert resp.json()["reason"] == "ui_play_requires_active_alexa_skill_session"
    assert any("alexa_request_context_missing" in message for message in capture_logger.messages)
    assert any("ui_play_not_supported_without_active_skill_session" in message for message in capture_logger.messages)
    assert not any("ui_play_routed_to_alexa_provider_api" in message for message in capture_logger.messages)


def test_ma_push_url_allows_prototype_skill_with_recent_context(monkeypatch):
    _set_edge_env(monkeypatch)
    _mock_edge_startup(monkeypatch)
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(ma_router, "logger", capture_logger)

    async def _fake_request_worker_handoff(**kwargs):
        return {
            "stream_url": "https://worker.example.com/v1/stream/token-123",
            "playback_session_id": "session-123",
            "stream_token_id": "token-123",
        }

    async def _fake_wait_for_worker_stream_fetch_start(**kwargs):
        return True, {"stream_fetch_started": True, "playback_started": False}

    async def _fake_readback_player_state(**kwargs):
        return {"player_id": "echo-spot", "playback_state": "playing", "queue_length": 1}

    monkeypatch.setattr(ma_router, "_request_worker_handoff", _fake_request_worker_handoff)
    monkeypatch.setattr(ma_router, "_wait_for_worker_stream_fetch_start", _fake_wait_for_worker_stream_fetch_start)
    monkeypatch.setattr(ma_router, "_readback_player_state", _fake_readback_player_state)

    app = create_app()
    with TestClient(app) as client:
        registry.register("config_service", _FakeConfigService())
        registry.register(
            "ma_client",
            _FakeMAClient([
                {"player_id": "echo-spot", "name": "Echo Spot", "provider": "alexa"},
            ]),
        )
        registry.register(
            "alexa_probe_state",
            {
                "probe_id": "probe-123",
                "probe_time": datetime.now(timezone.utc).isoformat(),
            },
        )

        resp = client.post(
            "/ma/push-url",
            json={
                "streamUrl": "/flow/session-a/echo-spot/item-1",
                "provider": "alexa",
            },
        )

    assert resp.status_code == 200
    assert any("alexa_request_context_found" in message for message in capture_logger.messages)
    assert any("prototype_skill_response_attached" in message for message in capture_logger.messages)


def test_ma_push_url_routes_ui_play_to_provider_api(monkeypatch):
    _set_edge_env(monkeypatch)
    _mock_edge_startup(monkeypatch)
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(ma_router, "logger", capture_logger)

    async def _fake_request_worker_handoff(**kwargs):
        return {
            "stream_url": "https://worker.example.com/v1/stream/token-456",
            "playback_session_id": "session-456",
            "stream_token_id": "token-456",
        }

    monkeypatch.setattr(ma_router, "_request_worker_handoff", _fake_request_worker_handoff)
    monkeypatch.setattr(ma_router, "_build_public_playback_url", lambda stream_url, settings: "https://public.example.com/flow/session-a/living-room/item-1")

    app = create_app()
    with TestClient(app) as client:
        registry.register("config_service", _FakeConfigService())
        registry.register(
            "ma_client",
            _FakeMAClient([
                {"player_id": "living-room", "name": "Living Room Speaker", "provider": "generic"},
            ]),
        )
        registry.register("alexa_probe_state", {"probe_id": "", "probe_time": ""})

        resp = client.post(
            "/ma/push-url",
            json={
                "streamUrl": "/flow/session-a/living-room/item-1",
                "provider": "musicassistant",
            },
        )

    assert resp.status_code == 200
    assert any("ui_play_routed_to_alexa_provider_api" in message for message in capture_logger.messages)
