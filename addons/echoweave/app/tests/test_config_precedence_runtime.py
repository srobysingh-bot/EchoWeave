"""Tests for effective runtime config precedence and diagnostics visibility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.models import PersistedConfig


def _write_options(path: Path, public_url: str, stream_url: str) -> None:
    options = {
        "ma_base_url": "http://ma.example:8095",
        "ma_token": "token-from-addon",
        "public_base_url": public_url,
        "stream_base_url": stream_url,
        "locale": "en-US",
        "aws_default_region": "us-east-1",
        "log_level": "info",
        "debug": False,
        "allow_insecure_local_test": False,
    }
    (path / "options.json").write_text(json.dumps(options), encoding="utf-8")


def _write_stale_persisted(path: Path) -> None:
    stale = PersistedConfig(
        ma_base_url="http://old.local:8095",
        ma_token="old-token",
        public_base_url="http://192.168.1.135:5000",
        stream_base_url="http://192.168.1.135:8097",
        locale="en-US",
        aws_default_region="us-east-1",
        log_level="info",
        debug=False,
        allow_insecure_local_test=False,
    )
    (path / "config.json").write_text(stale.model_dump_json(indent=2), encoding="utf-8")


def _clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ECHOWEAVE_MA_BASE_URL",
        "ECHOWEAVE_MA_TOKEN",
        "ECHOWEAVE_PUBLIC_BASE_URL",
        "ECHOWEAVE_STREAM_BASE_URL",
        "ECHOWEAVE_LOCALE",
        "ECHOWEAVE_AWS_DEFAULT_REGION",
        "ECHOWEAVE_LOG_LEVEL",
        "ECHOWEAVE_DEBUG",
        "ECHOWEAVE_ALLOW_INSECURE_LOCAL_TEST",
    ):
        monkeypatch.delenv(key, raising=False)


def test_addon_options_override_stale_persisted_on_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    public_url = "https://parker-custody-sufficiently-naturals.trycloudflare.com"
    stream_url = "https://doom-latinas-ethnic-collaborative.trycloudflare.com"

    _write_options(tmp_path, public_url, stream_url)
    _write_stale_persisted(tmp_path)
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))

    with TestClient(app) as client:
        resp = client.get("/config")

    assert resp.status_code == 200
    body = resp.text
    assert public_url in body
    assert stream_url in body
    assert "http://192.168.1.135:5000" not in body
    assert "http://192.168.1.135:8097" not in body
    assert "addon_options" in body

    repaired = PersistedConfig.model_validate_json((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert repaired.public_base_url == public_url
    assert repaired.stream_base_url == stream_url


def test_status_diagnostics_matches_config_effective_runtime_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    public_url = "https://parker-custody-sufficiently-naturals.trycloudflare.com"
    stream_url = "https://doom-latinas-ethnic-collaborative.trycloudflare.com"

    _write_options(tmp_path, public_url, stream_url)
    _write_stale_persisted(tmp_path)
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))

    with TestClient(app) as client:
        config_resp = client.get("/config")
        status_resp = client.get("/status")

    assert config_resp.status_code == 200
    assert status_resp.status_code == 200

    config_body = config_resp.text
    status_body = status_resp.text

    assert public_url in config_body
    assert stream_url in config_body
    assert public_url in status_body
    assert stream_url in status_body
    assert "Diagnostics" in status_body
    assert "addon_options" in status_body


@pytest.mark.anyio
async def test_public_health_check_uses_effective_runtime_public_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    captured: dict[str, str] = {}
    effective_public = "https://parker-custody-sufficiently-naturals.trycloudflare.com"

    async def _fake_public_check(url: str):
        captured["url"] = url
        return {"key": "public_url_reachable", "status": "ok", "message": "ok"}

    _write_options(tmp_path, effective_public, "https://doom-latinas-ethnic-collaborative.trycloudflare.com")
    _write_stale_persisted(tmp_path)
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("ECHOWEAVE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.diagnostics.checks.check_public_url", _fake_public_check)

    async def _always_true(_self):
        return True

    monkeypatch.setattr("app.ma.client.MusicAssistantClient.ping", _always_true)
    monkeypatch.setattr("app.ma.client.MusicAssistantClient.validate_token", _always_true)

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert captured["url"] == effective_public
