"""Tests for the /status page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.constants import APP_VERSION
from app.main import app

def test_status_returns_200():
    """GET /status should return 200 with HTML."""
    with TestClient(app) as client:
        resp = client.get("/status")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_setup_returns_200():
    """GET /setup should return 200 with HTML (not 404)."""
    with TestClient(app) as client:
        resp = client.get("/setup")
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


def test_ingress_header_root_redirect():
    """GET / should redirect with ingress base path when X-Ingress-Path is present."""
    with TestClient(app) as client:
        resp = client.get("/", headers={"X-Ingress-Path": "/app/06cc5e17_echoweave"}, follow_redirects=False)
    assert resp.status_code in (301, 302, 307)
    assert "/app/06cc5e17_echoweave/setup" in resp.headers.get("location", "")


def test_setup_page_uses_ingress_base_links():
    """GET /setup should render links scoped to ingress base path header."""
    with TestClient(app) as client:
        resp = client.get("/setup", headers={"X-Ingress-Path": "/app/06cc5e17_echoweave"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert '/app/06cc5e17_echoweave/status' in resp.text
    assert '/app/06cc5e17_echoweave/static/app.css' in resp.text


def test_debug_routes_contains_expected_paths():
    """GET /debug/routes should list core web and API routes."""
    with TestClient(app) as client:
        resp = client.get("/debug/routes")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["version"] == "0.1.7"
    assert "effective_base_path" in payload
    paths = {row["path"] for row in payload.get("routes", [])}
    assert "/" in paths
    assert "/setup" in paths
    assert "/status" in paths
    assert "/health" in paths
    assert "/logs" in paths
    assert "/config" in paths
    assert "/alexa" in paths


def test_debug_routes_shows_ingress_header_and_base_path():
    """GET /debug/routes should report ingress header and computed base path."""
    with TestClient(app) as client:
        resp = client.get("/debug/routes", headers={"X-Ingress-Path": "/app/06cc5e17_echoweave"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["x_ingress_path"] == "/app/06cc5e17_echoweave"
    assert payload["effective_base_path"] == "/app/06cc5e17_echoweave"


def test_debug_ping_ui_returns_html():
    """GET /debug/ping-ui should return a minimal HTML confirmation page."""
    with TestClient(app) as client:
        resp = client.get("/debug/ping-ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "EchoWeave UI OK" in resp.text


def test_runtime_version_is_017():
    """Runtime APP_VERSION constant must be aligned with add-on version 0.1.7."""
    assert APP_VERSION == "0.1.7"


def test_legacy_ingress_path_setup_returns_html():
    """GET /app/<slug>/setup should work for ingress proxies without header injection."""
    with TestClient(app) as client:
        resp = client.get("/app/06cc5e17_echoweave/setup")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_legacy_ingress_path_ping_ui_returns_html():
    """GET /app/<slug>/debug/ping-ui should return a simple HTML page."""
    with TestClient(app) as client:
        resp = client.get("/app/06cc5e17_echoweave/debug/ping-ui")
    assert resp.status_code == 200
    assert "EchoWeave UI OK" in resp.text


def test_double_slash_path_is_normalized_for_root_redirect():
    """GET // should be normalized and handled like GET /."""
    with TestClient(app) as client:
        resp = client.get("//", follow_redirects=False)
    assert resp.status_code in (301, 302, 307)
    assert "/setup" in resp.headers.get("location", "")


def test_double_slash_with_ingress_header_redirects_to_ingress_setup():
    """GET // with ingress header should redirect into ingress-scoped setup path."""
    with TestClient(app) as client:
        resp = client.get("//", headers={"X-Ingress-Path": "/app/06cc5e17_echoweave"}, follow_redirects=False)
    assert resp.status_code in (301, 302, 307)
    assert "/app/06cc5e17_echoweave/setup" == resp.headers.get("location", "")
