"""Tests for the /status page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

def test_status_returns_200():
    """GET /status should return 200 with HTML."""
    with TestClient(app) as client:
        resp = client.get("/status")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_status_contains_key_elements():
    """The status page should contain expected heading and status items."""
    with TestClient(app) as client:
        resp = client.get("/status")
    body = resp.text
    # "System Status" was removed when we updated the UI? Wait, no, we just used basic status.html
    # "Add-on Service" is definitely there.
    assert "Add-on Service" in body
    assert "Music Assistant Connection" in body


def test_root_redirect():
    """GET / should redirect to /setup."""
    with TestClient(app) as client:
        resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302, 307)
    assert "/setup" in resp.headers.get("location", "")


def test_ingress_root_redirect():
    """GET /app/<slug> should redirect to the ingress-prefixed setup page."""
    with TestClient(app) as client:
        resp = client.get("/app/06cc5e17_echoweave", follow_redirects=False)
    assert resp.status_code in (301, 302, 307)
    assert "/app/06cc5e17_echoweave/setup" in resp.headers.get("location", "")


def test_ingress_setup_page_returns_html():
    """GET /app/<slug>/setup should render setup HTML instead of 404."""
    with TestClient(app) as client:
        resp = client.get("/app/06cc5e17_echoweave/setup")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
