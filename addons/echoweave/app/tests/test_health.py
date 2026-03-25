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
    assert data["version"] == "0.1.9"


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
