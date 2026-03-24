"""Helpers for Home Assistant ingress-aware URL generation."""

from __future__ import annotations

from fastapi import Request


def get_ingress_base_path(request: Request) -> str:
    """Return effective base path from ingress header or ASGI root_path.

    Priority:
    1) Home Assistant's X-Ingress-Path header
    2) ASGI root_path (when app is mounted behind a proxy)
    3) empty string for direct/local mode
    """
    candidate = request.headers.get("X-Ingress-Path") or request.scope.get("root_path") or ""
    candidate = str(candidate).strip()
    if not candidate:
        return ""
    if not candidate.startswith("/"):
        candidate = f"/{candidate}"
    if candidate != "/":
        candidate = candidate.rstrip("/")
    return "" if candidate == "/" else candidate


def build_base_url(request: Request, route_path: str) -> str:
    """Build an ingress-aware URL for the given app-local route path."""
    if not route_path.startswith("/"):
        route_path = f"/{route_path}"
    return f"{get_ingress_base_path(request)}{route_path}"
