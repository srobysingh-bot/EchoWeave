"""Tests for Alexa PlaybackEvents end to end."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app

def test_nearly_finished_ignores_invalid_token():
    now = datetime.now(timezone.utc).isoformat()
    with TestClient(app) as client:
        payload = {
            "version": "1.0",
            "request": {
                "type": "AudioPlayer.PlaybackNearlyFinished", 
                "token": "notma:123",
                "timestamp": now
            },
            "context": {
                "System": {"device": {"deviceId": "test"}}
            }
        }
        resp = client.post("/alexa", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # Returns an empty response (no directives) because token doesn't start with "ma:"
    assert "directives" not in data.get("response", {})

def test_nearly_finished_handles_missing_registry(monkeypatch):
    """If missing MA registry, returns empty response without throwing 500."""
    now = datetime.now(timezone.utc).isoformat()
    with TestClient(app) as client:
        payload = {
            "version": "1.0",
            "request": {
                "type": "AudioPlayer.PlaybackNearlyFinished", 
                "token": "ma:queue1:item1",
                "timestamp": now
            },
            "context": {
                "System": {"device": {"deviceId": "test"}}
            }
        }
        # Assuming MA client fails to connect or queue misses
        resp = client.post("/alexa", json=payload)
    
    assert resp.status_code == 200
    data = resp.json()
    assert "directives" not in data.get("response", {})
