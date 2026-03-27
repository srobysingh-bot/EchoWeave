"""Tests for settings parsing and validation."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.settings import Settings


def test_default_settings():
    """Settings should initialise with sane defaults."""
    s = Settings()
    assert s.log_level == "info"
    assert s.locale == "en-US"
    assert s.debug is False
    assert s.allow_insecure_local_test is False
    assert s.mode == "legacy"
    assert s.port == 5000


def test_trailing_slash_stripped():
    """URLs should have trailing slashes removed."""
    s = Settings(ma_base_url="http://example.com/", public_base_url="https://pub.com/")
    assert s.ma_base_url == "http://example.com"
    assert s.public_base_url == "https://pub.com"


def test_invalid_log_level():
    """Invalid log_level should raise a validation error."""
    with pytest.raises(Exception):
        Settings(log_level="verbose")


def test_valid_log_levels():
    """All valid log levels should be accepted."""
    for level in ("trace", "debug", "info", "warning", "error", "critical"):
        s = Settings(log_level=level)
        assert s.log_level == level


def test_ma_configured_property():
    """ma_configured should be True only when both URL and token are set."""
    s1 = Settings(ma_base_url="http://ma.local", ma_token="tok")
    assert s1.ma_configured is True

    s2 = Settings(ma_base_url="http://ma.local", ma_token="")
    assert s2.ma_configured is False


def test_connector_configured_property():
    s1 = Settings(
        mode="connector",
        backend_url="https://cloud.example.com",
        connector_id="c1",
        connector_secret="secret",
        tenant_id="t1",
        home_id="h1",
    )
    assert s1.connector_configured is True

    s2 = Settings(mode="connector", backend_url="https://cloud.example.com")
    assert s2.connector_configured is False


def test_ui_auth_property():
    """ui_auth_enabled should reflect whether a password is set."""
    assert Settings(ui_password="").ui_auth_enabled is False
    assert Settings(ui_password="secret").ui_auth_enabled is True


def test_settings_from_env(monkeypatch):
    """Settings should pick up ECHOWEAVE_ environment variables."""
    monkeypatch.setenv("ECHOWEAVE_LOG_LEVEL", "debug")
    monkeypatch.setenv("ECHOWEAVE_DEBUG", "true")
    s = Settings()
    assert s.log_level == "debug"
    assert s.debug is True
