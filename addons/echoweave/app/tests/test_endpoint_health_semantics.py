"""Tests for stream/public endpoint health classification semantics."""

from __future__ import annotations

import pytest

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


@pytest.mark.anyio
async def test_stream_url_404_is_not_healthy(monkeypatch):
    monkeypatch.setattr("app.ma.health.httpx.AsyncClient", lambda timeout=10: _FakeClient(404))

    result = await MAHealthChecker.check_stream_url("https://stream.example.com")

    assert result["key"] == "stream_url_valid"
    assert result["status"] == "warn"
    assert "reachable but invalid" in result["message"]


@pytest.mark.anyio
async def test_public_local_http_reported_as_local_test(monkeypatch):
    monkeypatch.setattr("app.diagnostics.checks.httpx.AsyncClient", lambda timeout=10: _FakeClient(200))

    result = await check_public_url("http://192.168.1.25:5000")

    assert result["key"] == "public_url_reachable"
    assert result["status"] == "warn"
    assert "local testing" in result["message"].lower()


@pytest.mark.anyio
async def test_trycloudflare_https_stream_not_classified_insecure(monkeypatch):
    monkeypatch.setattr("app.ma.health.httpx.AsyncClient", lambda timeout=10: _FakeClient(200))

    result = await MAHealthChecker.check_stream_url(
        "https://doom-latinas-ethnic-collaborative.trycloudflare.com"
    )

    assert result["key"] == "stream_url_valid"
    assert result["status"] == "ok"
    assert "insecure" not in result["message"].lower()
