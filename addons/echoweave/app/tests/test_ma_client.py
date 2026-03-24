"""Tests for the Music Assistant client."""

from __future__ import annotations

import pytest
import httpx

from app.ma.client import MusicAssistantClient
from app.ma.auth import build_auth_headers
from app.core.exceptions import MusicAssistantAuthError, MusicAssistantUnreachableError


# ---------------------------------------------------------------------------
# Auth header tests
# ---------------------------------------------------------------------------

def test_auth_headers_with_token():
    """Headers should include Authorization when token is provided."""
    headers = build_auth_headers("my-token")
    assert headers["Authorization"] == "Bearer my-token"


def test_auth_headers_without_token():
    """Headers should be empty when no token is provided."""
    headers = build_auth_headers("")
    assert headers == {}


# ---------------------------------------------------------------------------
# Client tests (using httpx mock transport)
# ---------------------------------------------------------------------------

class _MockTransport(httpx.AsyncBaseTransport):
    """Minimal mock transport for testing the MA client."""

    def __init__(self, responses: dict[str, tuple[int, dict]] | None = None):
        self._responses = responses or {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self._responses:
            status, body = self._responses[path]
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def mock_client():
    """Create a MusicAssistantClient with a mock transport."""
    responses = {
        "/api": (200, {"server_id": "test-server", "server_version": "1.0.0", "schema_version": 1}),
        "/api/players": (200, [{"player_id": "p1", "name": "Test Player"}]),
    }
    client = MusicAssistantClient(base_url="http://mock-ma", token="test-token")
    # Inject mock transport
    client._client = httpx.AsyncClient(
        base_url="http://mock-ma",
        headers=build_auth_headers("test-token"),
        transport=_MockTransport(responses),
    )
    return client


@pytest.fixture
def auth_fail_client():
    """Client where auth always returns 401."""
    responses = {
        "/api": (200, {"server_id": "s", "server_version": "1", "schema_version": 1}),
        "/api/players": (401, {"error": "unauthorized"}),
    }
    client = MusicAssistantClient(base_url="http://mock-ma", token="bad-token")
    client._client = httpx.AsyncClient(
        base_url="http://mock-ma",
        headers=build_auth_headers("bad-token"),
        transport=_MockTransport(responses),
    )
    return client


@pytest.mark.anyio
async def test_ping_success(mock_client: MusicAssistantClient):
    result = await mock_client.ping()
    assert result is True
    await mock_client.close()


@pytest.mark.anyio
async def test_get_server_info(mock_client: MusicAssistantClient):
    info = await mock_client.get_server_info()
    assert info.server_id == "test-server"
    assert info.server_version == "1.0.0"
    await mock_client.close()


@pytest.mark.anyio
async def test_validate_token_success(mock_client: MusicAssistantClient):
    result = await mock_client.validate_token()
    assert result is True
    await mock_client.close()


@pytest.mark.anyio
async def test_validate_token_failure(auth_fail_client: MusicAssistantClient):
    result = await auth_fail_client.validate_token()
    assert result is False
    await auth_fail_client.close()


@pytest.mark.anyio
async def test_get_players(mock_client: MusicAssistantClient):
    players = await mock_client.get_players()
    assert len(players) == 1
    assert players[0]["player_id"] == "p1"
    await mock_client.close()
