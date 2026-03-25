"""Tests for stream/public endpoint health classification semantics."""

from __future__ import annotations

import pytest
import httpx

from app.diagnostics.checks import check_public_url
from app.ma.health import MAHealthChecker


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_code: int):
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def head(self, _url: str):
        return _FakeResponse(self._status_code)

    async def get(self, _url: str):
        return _FakeResponse(self._status_code)


class _CaptureUrlClient(_FakeClient):
    def __init__(self, status_code: int, captured: dict[str, str]):
        super().__init__(status_code)
        self._captured = captured

    async def get(self, url: str):
        self._captured["url"] = url
        return _FakeResponse(self._status_code)


class _RaisingClient:
    async def __aenter__(self):
        raise httpx.ReadTimeout("timed out")

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.anyio
async def test_stream_url_404_is_not_healthy(monkeypatch):
    monkeypatch.setattr("app.ma.health.httpx.AsyncClient", lambda timeout=10: _FakeClient(404))

    result = await MAHealthChecker.check_stream_url("https://stream.example.com")

    assert result["key"] == "stream_url_valid"
    assert result["status"] == "warn"
    assert "base url reachable" in result["message"].lower()
    assert "/stream/<queue_id>/<queue_item_id>" in result["message"]


@pytest.mark.anyio
async def test_public_local_http_reported_as_local_test(monkeypatch):
    monkeypatch.setattr("app.diagnostics.checks.httpx.AsyncClient", lambda timeout=10: _FakeClient(200))

    result = await check_public_url("http://192.168.1.25:5000")

    assert result["key"] == "public_url_reachable"
    assert result["status"] == "warn"
    assert "local testing" in result["message"].lower()


@pytest.mark.anyio
async def test_public_probe_uses_healthz_path(monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "app.diagnostics.checks.httpx.AsyncClient",
        lambda timeout=10: _CaptureUrlClient(200, captured),
    )

    result = await check_public_url("https://public.example.com")

    assert result["key"] == "public_url_reachable"
    assert result["status"] == "ok"
    assert captured["url"] == "https://public.example.com/healthz"


@pytest.mark.anyio
async def test_public_https_trycloudflare_reachable_is_ok(monkeypatch):
    monkeypatch.setattr("app.diagnostics.checks.httpx.AsyncClient", lambda timeout=10: _FakeClient(200))

    result = await check_public_url("https://parker-custody-sufficiently-naturals.trycloudflare.com")

    assert result["key"] == "public_url_reachable"
    assert result["status"] == "ok"
    assert "alexa-ready" in result["message"].lower()


@pytest.mark.anyio
async def test_public_unreachable_includes_exception_type_and_repr(monkeypatch):
    monkeypatch.setattr("app.diagnostics.checks.httpx.AsyncClient", lambda timeout=10: _RaisingClient())

    result = await check_public_url("https://public.example.com")

    assert result["key"] == "public_url_reachable"
    assert result["status"] == "fail"
    assert "unreachable:" in result["message"].lower()
    assert "readtimeout" in result["message"].lower()


@pytest.mark.anyio
async def test_trycloudflare_https_stream_not_classified_insecure(monkeypatch):
    monkeypatch.setattr("app.ma.health.httpx.AsyncClient", lambda timeout=10: _FakeClient(200))

    result = await MAHealthChecker.check_stream_url(
        "https://doom-latinas-ethnic-collaborative.trycloudflare.com"
    )

    assert result["key"] == "stream_url_valid"
    assert result["status"] == "ok"
    assert "insecure" not in result["message"].lower()
