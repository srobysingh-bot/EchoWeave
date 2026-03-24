"""Tests for ingress base path helper behavior."""

from __future__ import annotations

from fastapi import Request

from app.web.ingress import build_base_url, get_ingress_base_path


def _make_request(headers: dict[str, str] | None = None, root_path: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in (headers or {}).items()],
        "root_path": root_path,
    }
    return Request(scope)


def test_base_path_uses_ingress_header_when_present() -> None:
    request = _make_request(headers={"X-Ingress-Path": "/app/06cc5e17_echoweave"})
    assert get_ingress_base_path(request) == "/app/06cc5e17_echoweave"
    assert build_base_url(request, "/setup") == "/app/06cc5e17_echoweave/setup"


def test_base_path_falls_back_to_root_path() -> None:
    request = _make_request(root_path="/proxy/base")
    assert get_ingress_base_path(request) == "/proxy/base"
    assert build_base_url(request, "/status") == "/proxy/base/status"


def test_base_path_empty_for_direct_mode() -> None:
    request = _make_request()
    assert get_ingress_base_path(request) == ""
    assert build_base_url(request, "/setup") == "/setup"
