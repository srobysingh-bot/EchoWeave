"""Tests for Alexa LaunchRequest and PlayIntent compatibility."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app


def _base_envelope(request_obj: dict) -> dict:
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "SessionId.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test"},
        },
        "context": {
            "System": {
                "device": {"deviceId": "device.test"},
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test"},
            }
        },
        "request": request_obj,
    }


def _bypass_signature_and_timestamp(monkeypatch):
    monkeypatch.setattr("app.alexa.validators.verify_alexa_timestamp", lambda body: True)

    async def _ok_sig(request, raw_body, enforce=True):
        return True

    monkeypatch.setattr("app.alexa.validators.verify_alexa_signature", _ok_sig)


def test_launch_request_returns_valid_welcome_response(monkeypatch):
    _bypass_signature_and_timestamp(monkeypatch)

    payload = _base_envelope(
        {
            "type": "LaunchRequest",
            "requestId": "EdwRequestId.launch",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "locale": "en-US",
        }
    )

    with TestClient(app) as client:
        resp = client.post("/alexa", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("version") == "1.0"
    assert "sessionAttributes" in data
    assert isinstance(data["sessionAttributes"], dict)
    response = data.get("response", {})
    assert response.get("shouldEndSession") is False
    assert "outputSpeech" in response
    assert response["outputSpeech"].get("type") == "PlainText"
    assert response["outputSpeech"].get("text") == "Welcome to EchoWeave."
    assert "reprompt" in response
    assert "outputSpeech" in response["reprompt"]
    assert response["reprompt"]["outputSpeech"].get("text") == "Say play audio to begin."


def test_play_intent_still_returns_success_response(monkeypatch):
    _bypass_signature_and_timestamp(monkeypatch)

    payload = _base_envelope(
        {
            "type": "IntentRequest",
            "requestId": "EdwRequestId.intent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "locale": "en-US",
            "intent": {"name": "PlayIntent", "confirmationStatus": "NONE"},
        }
    )

    with TestClient(app) as client:
        resp = client.post("/alexa", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("version") == "1.0"
    response = data.get("response", {})
    assert "outputSpeech" in response
    assert response.get("shouldEndSession") is True


def test_playaudio_intent_maps_to_play_handler(monkeypatch):
    _bypass_signature_and_timestamp(monkeypatch)

    payload = _base_envelope(
        {
            "type": "IntentRequest",
            "requestId": "EdwRequestId.playaudio",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "locale": "en-US",
            "intent": {"name": "PlayAudio", "confirmationStatus": "NONE"},
        }
    )

    with TestClient(app) as client:
        resp = client.post("/alexa", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    response = data.get("response", {})
    assert response.get("shouldEndSession") is True
    assert "outputSpeech" in response
    assert (
        response["outputSpeech"].get("text")
        == "Playback will start once Music Assistant integration is complete."
    )
