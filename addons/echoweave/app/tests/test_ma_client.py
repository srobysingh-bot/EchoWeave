"""Tests for the Music Assistant client."""

from __future__ import annotations

import pytest
import httpx

from app.ma.client import MusicAssistantClient
from app.ma.auth import build_auth_headers
from app.core.exceptions import MusicAssistantAuthError, MusicAssistantError, MusicAssistantUnreachableError


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

    def __init__(self, responses: dict[tuple[str, str], tuple[int, object]] | None = None):
        self._responses = responses or {}
        self.last_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        key = (request.method.upper(), request.url.path)
        if key in self._responses:
            status, body = self._responses[key]
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def mock_client():
    """Create a MusicAssistantClient with a mock transport."""
    responses = {
        ("POST", "/api"): (200, {"result": [{"player_id": "p1", "name": "Test Player"}]}),
    }
    transport = _MockTransport(responses)
    client = MusicAssistantClient(base_url="http://mock-ma", token="test-token")
    # Inject mock transport
    client._client = httpx.AsyncClient(
        base_url="http://mock-ma",
        headers=build_auth_headers("test-token"),
        transport=transport,
    )
    client._transport = transport
    return client


@pytest.fixture
def auth_fail_client():
    """Client where auth always returns 401."""
    responses = {
        ("POST", "/api"): (401, {"error": "unauthorized"}),
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
    # Override transport response for server/info command shape.
    mock_client._client = httpx.AsyncClient(
        base_url="http://mock-ma",
        headers=build_auth_headers("test-token"),
        transport=_MockTransport({
            ("POST", "/api"): (200, {"result": {"server_id": "test-server", "server_version": "1.0.0", "schema_version": 1}}),
        }),
    )
    info = await mock_client.get_server_info()
    assert info.server_id == "test-server"
    assert info.server_version == "1.0.0"
    await mock_client.close()


@pytest.mark.anyio
async def test_validate_token_success(mock_client: MusicAssistantClient):
    result = await mock_client.validate_token()
    assert result is True
    req = mock_client._transport.last_request
    assert req is not None
    assert req.method == "POST"
    assert req.url.path == "/api"
    assert b'"command":"players/all"' in req.content
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


@pytest.mark.anyio
async def test_resolve_play_request_discards_numeric_requested_queue_id(mock_client: MusicAssistantClient):
    seen: list[str | None] = []

    async def _fake_get_current(queue_id: str | None = None, **kwargs):
        seen.append(queue_id)
        if queue_id is None:
            return {
                "queue_id": "queue-live",
                "queue_item_id": "item1",
                "origin_stream_path": "/edge/stream/queue-live/item1",
                "content_type": "audio/mpeg",
            }
        return None

    async def _fake_get_next(queue_id: str | None = None, **kwargs):
        seen.append(queue_id)
        return None

    mock_client.get_current_playable_item = _fake_get_current
    mock_client.get_next_playable_item = _fake_get_next

    payload = await mock_client.resolve_play_request("-1452896388")
    assert payload["queue_id"] == "queue-live"
    assert seen == [None]
    await mock_client.close()


@pytest.mark.anyio
async def test_resolve_play_request_discards_404_requested_queue_id(mock_client: MusicAssistantClient):
    seen: list[str | None] = []

    async def _fake_get_current(queue_id: str | None = None, **kwargs):
        seen.append(queue_id)
        if queue_id == "queue-stale":
            raise MusicAssistantError("MA API error: 404 (method=GET path=/api/playerqueues/queue-stale body=)")
        if queue_id is None:
            return {
                "queue_id": "queue-live",
                "queue_item_id": "item1",
                "origin_stream_path": "/edge/stream/queue-live/item1",
                "content_type": "audio/mpeg",
            }
        return None

    async def _fake_get_next(queue_id: str | None = None, **kwargs):
        seen.append(queue_id)
        return None

    mock_client.get_current_playable_item = _fake_get_current
    mock_client.get_next_playable_item = _fake_get_next

    payload = await mock_client.resolve_play_request("queue-stale")
    assert payload["queue_id"] == "queue-live"
    assert seen == ["queue-stale", None]
    await mock_client.close()


@pytest.mark.anyio
async def test_resolve_default_queue_id_rejects_numeric_candidate(mock_client: MusicAssistantClient):
    requested_paths: list[str] = []

    async def _fake_get_players():
        return [
            {
                "player_id": "player-a",
                "active_queue": "-1452896388",
                "queue_id": "queue-live",
            }
        ]

    async def _fake_get_with_path_fallback(paths: list[str]):
        requested_paths.append(paths[0])

        class _Resp:
            def json(self):
                return {"current_item": {}}

        return _Resp()

    mock_client.get_players = _fake_get_players
    mock_client._get_with_path_fallback = _fake_get_with_path_fallback

    resolved = await mock_client._resolve_default_queue_id()
    assert resolved == "queue-live"
    assert requested_paths == ["/api/player_queues/queue-live"]
    await mock_client.close()


@pytest.mark.anyio
async def test_queue_paths_rejects_stale_numeric_queue_id(mock_client: MusicAssistantClient):
    with pytest.raises(MusicAssistantError, match="Invalid or stale queue id rejected"):
        mock_client._queue_paths("-1452896388")
    await mock_client.close()


@pytest.mark.anyio
async def test_get_queue_state_discards_404_requested_queue(mock_client: MusicAssistantClient):
    calls: list[str] = []

    async def _fake_get_with_path_fallback(paths: list[str]):
        path = paths[0]
        calls.append(path)
        if "/queue-stale" in path:
            raise MusicAssistantError("MA API error: 404 (method=GET path=/api/playerqueues/queue-stale body=)")

        class _Resp:
            def json(self):
                return {
                    "state": "playing",
                    "elapsed_time": 1,
                    "current_item": {"queue_id": "queue-live"},
                    "next_item": {},
                }

        return _Resp()

    async def _fake_resolve_default_queue_id():
        return "queue-live"

    mock_client._get_with_path_fallback = _fake_get_with_path_fallback
    mock_client._resolve_default_queue_id = _fake_resolve_default_queue_id

    state = await mock_client.get_queue_state("queue-stale")
    assert state["queue_id"] == "queue-live"
    assert calls[0] == "/api/player_queues/queue-stale"
    assert calls[1] == "/api/player_queues/queue-live"
    await mock_client.close()


@pytest.mark.anyio
async def test_get_queue_state_raises_structured_queue_empty_when_no_active_queue(mock_client: MusicAssistantClient):
    async def _fake_resolve_default_queue_id():
        return None

    mock_client._resolve_default_queue_id = _fake_resolve_default_queue_id

    with pytest.raises(MusicAssistantError, match='"code": "queue_empty"'):
        await mock_client.get_queue_state()

    await mock_client.close()


def test_normalize_query_strips_music_by_prefix(mock_client: MusicAssistantClient):
    assert mock_client._normalize_query("songs by arijit singh") == "arijit singh"
    assert mock_client._normalize_query("music by arijit singh") == "arijit singh"


@pytest.mark.anyio
async def test_resolve_play_request_prefers_query_search_order(mock_client: MusicAssistantClient):
    searched: list[str] = []

    async def _fake_search_media(query: str, media_type: str, *, limit: int = 10):
        searched.append(media_type)
        if media_type == "albums":
            return [{"uri": "ma:album:1", "name": "Album A"}]
        return []

    async def _fake_try_enqueue(*args, **kwargs):
        return {
            "queue_id": "queue-live",
            "queue_item_id": "item1",
            "origin_stream_path": "/edge/stream/queue-live/item1",
            "content_type": "audio/mpeg",
        }

    mock_client._search_media = _fake_search_media
    mock_client._try_enqueue_search_result = _fake_try_enqueue

    payload = await mock_client.resolve_play_request(query="songs by arijit singh", intent_name="PlayIntent")
    assert payload["queue_id"] == "queue-live"
    assert searched == ["tracks", "artists", "albums"]


@pytest.mark.anyio
async def test_resolve_play_request_uses_artist_top_tracks(mock_client: MusicAssistantClient):
    searched: list[tuple[str, str]] = []

    async def _fake_search_media(query: str, media_type: str, *, limit: int = 10):
        searched.append((media_type, query))
        if media_type == "artists":
            return [{"name": "Arijit Singh", "uri": "ma:artist:1"}]
        if media_type == "tracks" and query == "Arijit Singh":
            return [{"uri": "ma:track:1", "name": "Top Track"}]
        return []

    async def _fake_try_enqueue(*args, **kwargs):
        return {
            "queue_id": "queue-live",
            "queue_item_id": "item-top",
            "origin_stream_path": "/edge/stream/queue-live/item-top",
            "content_type": "audio/mpeg",
        }

    mock_client._search_media = _fake_search_media
    mock_client._try_enqueue_search_result = _fake_try_enqueue

    payload = await mock_client.resolve_play_request(query="music by arijit singh", intent_name="PlayIntent")
    assert payload["queue_item_id"] == "item-top"
    assert ("artists", "arijit singh") in searched
    assert ("tracks", "Arijit Singh") in searched


@pytest.mark.anyio
async def test_handoff_playback_url_success(mock_client: MusicAssistantClient):
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    async def _fake_get_players():
        return [
            {
                "player_id": "player-1",
                "name": "Kitchen Echo",
                "active_queue": "queue-1",
            }
        ]

    async def _fake_post_command_with_fallback(commands, **payload):
        calls.append((tuple(commands), payload))
        return {"ok": True}

    mock_client.get_players = _fake_get_players
    mock_client._post_command_with_fallback = _fake_post_command_with_fallback

    ok, message, details = await mock_client.handoff_playback_url(
        player_id="player-1",
        playback_url="https://stream.example.com/flow/s1/player-1/item1/song.mp3",
        request_id="r1",
        home_id="h1",
    )

    assert ok is True
    assert message == "playback-command-sent"
    assert details["player_id"] == "player-1"
    assert calls[0][0] == ("player_queues/play_media", "playerqueues/play_media")
    assert calls[1][0] == ("players/cmd/play",)


@pytest.mark.anyio
async def test_handoff_playback_url_player_not_found(mock_client: MusicAssistantClient):
    async def _fake_get_players():
        return [{"player_id": "player-2", "name": "Bedroom Echo"}]

    mock_client.get_players = _fake_get_players

    ok, message, details = await mock_client.handoff_playback_url(
        player_id="missing-player",
        playback_url="https://stream.example.com/flow/s1/player-1/item1/song.mp3",
    )

    assert ok is False
    assert message == "player-not-found"
    assert details["player_id"] == "missing-player"
