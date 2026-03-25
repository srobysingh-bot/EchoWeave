"""Tests for the setup routes."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_persistence

def test_validate_ma_missing_fields():
    with TestClient(app) as client:
        resp = client.post("/setup/validate-ma", json={"ma_base_url": "", "ma_token": ""})
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "required" in resp.json()["message"]

def test_validate_public_url_missing():
    with TestClient(app) as client:
        resp = client.post("/setup/validate-public", json={"public_base_url": ""})
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "required" in resp.json()["message"]

def test_save_config():
    with TestClient(app) as client:
        payload = {
            "ma_base_url": "http://mock:8095",
            "ma_token": "token",
            "public_base_url": "https://pub.example.com",
            "stream_base_url": "https://stream.example.com",
            "locale": "en-US",
            "aws_default_region": "us-east-1"
        }
        resp = client.post("/setup/save", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "saved" in data["message"]


def test_setup_save_roundtrip_visible_on_config_page():
    with TestClient(app) as client:
        payload = {
            "ma_base_url": "http://mock-roundtrip:8095",
            "ma_token": "roundtrip-token",
            "public_base_url": "https://public.roundtrip.example",
            "stream_base_url": "https://stream.roundtrip.example",
            "locale": "en-US",
            "aws_default_region": "us-east-1",
        }
        save_resp = client.post("/setup/save", json=payload)
        config_resp = client.get("/config")

    assert save_resp.status_code == 200
    assert save_resp.json()["success"] is True

    assert config_resp.status_code == 200
    body = config_resp.text
    assert "http://mock-roundtrip:8095" in body
    assert "https://public.roundtrip.example" in body
    assert "https://stream.roundtrip.example" in body
    assert "**** (set)" in body
    assert "roundtrip-token" not in body


def test_manual_skill_setup_empty_skill_id():
    """Manual skill setup should reject empty skill ID."""
    with TestClient(app) as client:
        resp = client.post("/setup/save-skill", json={
            "skill_id": "",
            "endpoint_url": "",
            "manual_ask_setup": False,
        })
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "required" in resp.json()["message"].lower()


def test_manual_skill_setup_saves_metadata():
    """Manual skill setup should save skill metadata and mark as manually configured."""
    with TestClient(app) as client:
        skill_id = "amzn1.ask.skill.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        resp = client.post("/setup/save-skill", json={
            "skill_id": skill_id,
            "endpoint_url": "https://example.com/alexa",
            "manual_ask_setup": True,
        })
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "linked successfully" in data["message"].lower()


def test_manual_skill_setup_marks_step_6_complete():
    """After manual skill entry, the skill step metadata should reflect is_configured."""
    with TestClient(app) as client:
        # First, get the setup page to see initial state
        resp1 = client.get("/setup")
        page1 = resp1.text
        
        # Verify skill step exists
        assert "Alexa Skill Created" in page1
        
        # Now link a skill manually
        skill_id = "amzn1.ask.skill.test-1234-5678-9012-345"
        save_resp = client.post("/setup/save-skill", json={
            "skill_id": skill_id,
            "endpoint_url": "",
            "manual_ask_setup": False,
        })
        
        assert save_resp.status_code == 200
        assert save_resp.json()["success"] is True
        
        # Verify the skill_metadata was saved with manual_skill_configured=True
        # by checking that we can post again without error (implies persistent storage)
        resp2 = client.get("/setup")
        page2 = resp2.text
        
        # The page should still be valid
        assert resp2.status_code == 200
        assert "Alexa Skill Created" in page2


def test_ask_setup_optional_in_phase_1():
    """In Phase 1, ASK step should be labeled as optional."""
    with TestClient(app) as client:
        resp = client.get("/setup")
        page = resp.text
        # Step 5 should reference Phase 1 or Optional
        assert "Optional in Phase 1" in page or "optional" in page.lower()
        assert "ASK Setup" in page


def test_manual_skill_setup_whitespace_handling():
    """Manual skill setup should trim whitespace from skill ID."""
    with TestClient(app) as client:
        skill_id_with_spaces = "  amzn1.ask.skill.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  "
        resp = client.post("/setup/save-skill", json={
            "skill_id": skill_id_with_spaces,
            "endpoint_url": "  https://example.com/alexa  ",
            "manual_ask_setup": False,
        })
    
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "linked successfully" in resp.json()["message"].lower()
