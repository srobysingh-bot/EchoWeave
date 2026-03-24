"""Tests for the /status page."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_status_returns_200():
    """GET /status should return 200 with HTML."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.anyio
async def test_status_contains_key_elements():
    """The status page should contain expected heading and status items."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/status")
    body = resp.text
    assert "System Status" in body
    assert "Add-on Service" in body
    assert "Music Assistant" in body


@pytest.mark.anyio
async def test_root_redirect():
    """GET / should redirect to /status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        resp = await client.get("/")
    assert resp.status_code in (301, 302, 307)
    assert "/status" in resp.headers.get("location", "")
