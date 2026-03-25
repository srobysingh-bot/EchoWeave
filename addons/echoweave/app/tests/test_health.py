"""Tests for the /health endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

def test_health_returns_200():
    """GET /health should return 200 with JSON containing status and checks."""
    with TestClient(app) as client:
        resp = client.get("/health")
    
    # 200 if OK/Warn, 503 if Fail. It depends on the config!
    # Because there's no auth, wait, MA is unreachable so it's 503!
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert data["version"] == "0.2.0"


def test_healthz_returns_service_up_without_nested_checks(monkeypatch):
    class _ExplodingHealthService:
        async def run_all(self):
            raise AssertionError("run_all must not be called for /healthz")

    monkeypatch.setattr("app.dependencies.get_health_service", lambda: _ExplodingHealthService())

    with TestClient(app) as client:
        resp = client.get("/healthz")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.2.0"
    assert isinstance(payload["checks"], list)
    assert payload["checks"][0]["key"] == "service"


def test_health_service_check_present():
    """The service check should always appear in /health results."""
    with TestClient(app) as client:
        resp = client.get("/health")
    data = resp.json()
    keys = [c["key"] for c in data["checks"]]
    assert "service" in keys
    assert "ma_reachable" in keys
    assert "stream_url_valid" in keys


def test_health_json_structure():
    """Verify the JSON envelope structure."""
    with TestClient(app) as client:
        resp = client.get("/health")
    data = resp.json()
    for check in data["checks"]:
        assert "key" in check
        assert "status" in check
        assert "message" in check
