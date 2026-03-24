"""Unit tests for low-level ASGI path normalization middleware."""

from __future__ import annotations

from app.main import NormalizePathASGIMiddleware


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _capture_send(_message):
    return None


async def _downstream_app(scope, receive, send):
    _downstream_app.last_scope = scope
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_asgi_middleware_normalizes_double_slash():
    """Middleware should rewrite // to / before downstream handling."""
    middleware = NormalizePathASGIMiddleware(_downstream_app)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "//",
        "raw_path": b"//",
        "query_string": b"",
        "headers": [],
        "root_path": "",
        "scheme": "http",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "http_version": "1.1",
    }

    import anyio
    anyio.run(middleware, scope, _empty_receive, _capture_send)

    assert _downstream_app.last_scope["path"] == "/"
    assert _downstream_app.last_scope["raw_path"] == b"/"


def test_asgi_middleware_normalizes_triple_slash_prefix():
    """Middleware should collapse repeated slashes in nested paths."""
    middleware = NormalizePathASGIMiddleware(_downstream_app)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "///setup",
        "raw_path": b"///setup",
        "query_string": b"",
        "headers": [],
        "root_path": "",
        "scheme": "http",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "http_version": "1.1",
    }

    import anyio
    anyio.run(middleware, scope, _empty_receive, _capture_send)

    assert _downstream_app.last_scope["path"] == "/setup"
    assert _downstream_app.last_scope["raw_path"] == b"/setup"
