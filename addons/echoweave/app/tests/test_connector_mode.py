from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.connector.client import ConnectorClient
from app.main import app
from app.settings import Settings
from app.storage.models import PersistedConfig


def test_connector_mode_settings_loads():
    settings = Settings(
        mode="connector",
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
        ma_base_url="http://ma.local:8095",
        ma_token="token",
    )
    assert settings.is_connector_mode is True
    assert settings.connector_configured is True


@pytest.mark.anyio
async def test_registration_client_uses_backend_url(monkeypatch: pytest.MonkeyPatch):
    captured = {"url": ""}

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict):
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
            captured["url"] = url
            return _FakeResponse(200, {"success": True})

    monkeypatch.setattr("app.connector.client.httpx.AsyncClient", lambda timeout=10: _FakeAsyncClient())

    client = ConnectorClient(
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
    )
    ok = await client.register()

    assert ok is True
    assert captured["url"] == "https://cloud.example.com/v1/connectors/register"


def test_setup_page_shows_connector_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cfg = PersistedConfig(
        mode="connector",
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
        ma_base_url="http://ma.local:8095",
        ma_token="token",
    )
    (tmp_path / "config.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))

    with TestClient(app) as client:
        resp = client.get("/setup")

    assert resp.status_code == 200
    body = resp.text
    assert "Cloud Backend URL" in body
    assert "Connector ID" in body
    assert "Connector Secret" in body
    assert "Manual Alexa Skill Setup" not in body


def test_status_page_shows_connector_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cfg = PersistedConfig(
        mode="connector",
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
        ma_base_url="http://ma.local:8095",
        ma_token="token",
    )
    (tmp_path / "config.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))

    with TestClient(app) as client:
        resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.text
    assert "connector_registered" in body
    assert "Connector Registration" in body
    assert "Connector Heartbeat" in body


def test_status_page_hides_legacy_endpoint_cards_in_connector_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    cfg = PersistedConfig(
        mode="connector",
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
        ma_base_url="http://ma.local:8095",
        ma_token="token",
        public_base_url="https://placeholder.invalid",
        stream_base_url="https://placeholder.invalid",
    )
    (tmp_path / "config.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))

    with TestClient(app) as client:
        resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.text
    assert "Stream Endpoint" not in body
    assert "Public Endpoint" not in body


def test_health_skips_legacy_endpoint_checks_in_connector_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    cfg = PersistedConfig(
        mode="connector",
        backend_url="https://cloud.example.com",
        connector_id="connector-01",
        connector_secret="secret",
        tenant_id="tenant-01",
        home_id="home-01",
        ma_base_url="http://ma.local:8095",
        ma_token="token",
        public_base_url="https://placeholder.invalid",
        stream_base_url="https://placeholder.invalid",
    )
    (tmp_path / "config.json").write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code in (200, 503)
    data = resp.json()
    keys = [c["key"] for c in data["checks"]]
    assert "stream_url_valid" not in keys
    assert "public_url_reachable" not in keys
