"""Tests for Alexa PlaybackEvents end to end."""

import os
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

# Force dev mode for tests to bypass RSA signature checking
os.environ["ECHOWEAVE_ALEXA_VALIDATION_MODE"] = "dev"

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
    assert "directives" not in data.get("response", {})

def test_nearly_finished_handles_missing_registry(monkeypatch):
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
        resp = client.post("/alexa", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "directives" not in data.get("response", {})

def test_nearly_finished_success_enqueue():
    from app.core.service_registry import registry
    from app.ma.models import MAQueueItem, MAStreamDetails

    now = datetime.now(timezone.utc).isoformat()
    
    mock_ma = AsyncMock()
    mock_item = MAQueueItem(
        queue_id="q1",
        queue_item_id="item2",
        name="Track 2",
        uri="uri2",
        image="http://img",
        streamdetails=MAStreamDetails(url="https://public.example.com/stream/item2")
    )
    mock_ma.get_queue_items.return_value = [mock_item]
    
    mock_cfg = MagicMock()
    mock_cfg.settings.stream_base_url = "https://public.example.com"
    mock_cfg.settings.allow_insecure_local_test = False
    mock_cfg.settings.alexa_validation_mode = "dev"
    
    mock_sessions = MagicMock()
    
    registry.register("ma_client", mock_ma)
    registry.register("config_service", mock_cfg)
    registry.register("session_store", mock_sessions)
    
    with TestClient(app) as client:
        payload = {
            "version": "1.0",
            "request": {
                "type": "AudioPlayer.PlaybackNearlyFinished", 
                "token": "ma:q1:item1",
                "timestamp": now
            },
            "context": {
                "System": {"device": {"deviceId": "test-device"}}
            }
        }
        resp = client.post("/alexa", json=payload)
    
    assert resp.status_code == 200
    data = resp.json()
    directives = data.get("response", {}).get("directives", [])
    assert len(directives) == 1
    d = directives[0]
    assert d["type"] == "AudioPlayer.Play"
    assert d["playBehavior"] == "ENQUEUE"
    assert d["audioItem"]["stream"]["url"] == "https://public.example.com/stream/item2"
    assert d["audioItem"]["stream"]["expectedPreviousToken"] == "ma:q1:item1"
    assert d["audioItem"]["stream"]["token"] == "ma:q1:item2"

def test_nearly_finished_queue_exhaustion():
    from app.core.service_registry import registry

    now = datetime.now(timezone.utc).isoformat()
    
    mock_ma = AsyncMock()
    mock_ma.get_queue_items.return_value = []
    
    mock_cfg = MagicMock()
    mock_cfg.settings.stream_base_url = "https://public.example.com"
    mock_cfg.settings.alexa_validation_mode = "dev"
    
    registry.register("ma_client", mock_ma)
    registry.register("config_service", mock_cfg)
    
    with TestClient(app) as client:
        payload = {
            "version": "1.0",
            "request": {
                "type": "AudioPlayer.PlaybackNearlyFinished", 
                "token": "ma:q1:end_item",
                "timestamp": now
            },
            "context": {
                "System": {"device": {"deviceId": "test-device"}}
            }
        }
        resp = client.post("/alexa", json=payload)
    
    assert resp.status_code == 200
    data = resp.json()
    assert "directives" not in data.get("response", {})
