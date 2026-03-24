"""Tests for the /health endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_health_returns_200():
    """GET /health should return 200 with JSON containing status and checks."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert data["version"] == "0.1.0"


@pytest.mark.anyio
async def test_health_service_check_present():
    """The service check should always appear in /health results."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    data = resp.json()
    keys = [c["key"] for c in data["checks"]]
    assert "service" in keys


@pytest.mark.anyio
async def test_health_json_structure():
    """Verify the JSON envelope structure."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    data = resp.json()
    for check in data["checks"]:
        assert "key" in check
        assert "status" in check
        assert "message" in check
