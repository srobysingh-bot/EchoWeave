"""Tests for the setup routes."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

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
