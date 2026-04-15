from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import MusicAssistantError
from app.edge.auth import sign_edge_request, verify_edge_request
from app.edge.command_dispatch import execute_edge_command
from app.main import app


def test_edge_stream_signature_validation_round_trip():
    import time

    ts, sig = sign_edge_request(
        shared_secret="edge-shared",
        method="GET",
        path="/edge/stream/q1/i1",
        timestamp=int(time.time()),
    )
    assert verify_edge_request(
        shared_secret="edge-shared",
        method="GET",
        path="/edge/stream/q1/i1",
        timestamp=ts,
        signature=sig,
        max_age_seconds=10_000_000,
    ) is True

    assert verify_edge_request(
        shared_secret="edge-shared",
        method="GET",
        path="/edge/stream/q1/i2",
        timestamp=ts,
        signature=sig,
        max_age_seconds=10_000_000,
    ) is False


@pytest.mark.anyio
async def test_prepare_play_returns_playable_context():
    class _FakeMA:
        async def resolve_play_request(self, queue_id=None, **kwargs):
            return {
                "queue_id": queue_id or "q1",
                "queue_item_id": "item1",
                "title": "Song One",
                "origin_stream_path": "/edge/stream/q1/item1",
                "content_type": "audio/mpeg",
            }

        async def get_current_playable_item(self, queue_id=None):
            return {"queue_id": queue_id or "q1"}

        async def get_next_playable_item(self, queue_id=None):
            return {"queue_id": queue_id or "q1"}

        async def get_queue_state(self, queue_id=None):
            return {"queue_id": queue_id or "q1", "state": "playing"}

    payload = await execute_edge_command(
        "prepare_play",
        {"queue_id": "queue-a", "intent_name": "PlayIntent"},
        _FakeMA(),
        default_queue_id="queue-default",
    )
    assert payload["queue_id"] == "queue-a"
    assert payload["queue_item_id"] == "item1"
    assert payload["origin_stream_path"].startswith("/edge/stream/")


@pytest.mark.anyio
async def test_prepare_play_falls_back_when_requested_queue_is_stale():
    class _FakeMA:
        async def resolve_play_request(self, queue_id=None, **kwargs):
            if queue_id == "queue-stale":
                raise MusicAssistantError("No playable queue item available.")
            return {
                "queue_id": queue_id or "queue-live",
                "queue_item_id": "item-live",
                "title": "Song Live",
                "origin_stream_path": "/edge/stream/queue-live/item-live",
                "content_type": "audio/mpeg",
            }

    payload = await execute_edge_command(
        "prepare_play",
        {"queue_id": "queue-stale", "intent_name": "PlayIntent"},
        _FakeMA(),
        default_queue_id="queue-default",
    )
    assert payload["queue_id"] == "queue-live"
    assert payload["queue_item_id"] == "item-live"


def test_status_surface_shows_edge_readiness(monkeypatch):
    monkeypatch.setenv("ECHOWEAVE_MODE", "edge")
    monkeypatch.setenv("ECHOWEAVE_WORKER_BASE_URL", "https://worker.example.com")
    monkeypatch.setenv("ECHOWEAVE_TUNNEL_BASE_URL", "https://origin.example.com")
    monkeypatch.setenv("ECHOWEAVE_EDGE_SHARED_SECRET", "edge-secret")
    monkeypatch.setenv("ECHOWEAVE_CONNECTOR_ID", "conn-a")
    monkeypatch.setenv("ECHOWEAVE_CONNECTOR_SECRET", "conn-secret")
    monkeypatch.setenv("ECHOWEAVE_TENANT_ID", "tenant-a")
    monkeypatch.setenv("ECHOWEAVE_HOME_ID", "home-a")
    monkeypatch.setenv("ECHOWEAVE_ALEXA_SOURCE_QUEUE_ID", "queue-a")
    monkeypatch.setenv("ECHOWEAVE_MA_BASE_URL", "http://ma.local:8095")
    monkeypatch.setenv("ECHOWEAVE_MA_TOKEN", "token")

    async def _fake_fetch_worker_home_status(*, worker_base_url: str, tenant_id: str, home_id: str):
        return {
            "reachable": True,
            "provisioned": True,
            "alexa_account_linked": False,
            "connector_online": True,
            "connector_registration_status": "registered",
            "origin_base_url": "https://origin.example.com",
            "queue_binding": "queue-a",
            "message": "ok",
        }

    monkeypatch.setattr(
        "app.edge.admin_client.fetch_worker_home_status",
        _fake_fetch_worker_home_status,
    )

    with TestClient(app) as client:
        resp = client.get("/status")

    assert resp.status_code == 200
    body = resp.text
    assert "Worker Provisioning" in body
    assert "Alexa Account Linking" in body
    assert "worker_home_provisioned" in body
    assert "Alexa UI Playback Limitation" in body
    assert "UI playback to Alexa requires an active Alexa skill session" in body
    assert "alexa_ui_start_supported" in body
