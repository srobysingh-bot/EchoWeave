"""Tests for the session store and token mapper."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.alexa.session_store import SessionStore
from app.alexa.token_mapper import decode_token, encode_token, is_echoweave_token
from app.storage.models import PlayState
from app.storage.persistence import PersistenceService


# ---------------------------------------------------------------------------
# Token mapper tests
# ---------------------------------------------------------------------------

class TestTokenMapper:
    def test_encode_token(self):
        token = encode_token("queue-1", "item-42")
        assert token == "ma:queue-1:item-42"

    def test_decode_token(self):
        parts = decode_token("ma:queue-1:item-42")
        assert parts is not None
        assert parts.queue_id == "queue-1"
        assert parts.item_id == "item-42"

    def test_decode_invalid_token(self):
        assert decode_token("invalid-token") is None
        assert decode_token("") is None
        assert decode_token("ma:only-two") is None

    def test_roundtrip(self):
        token = encode_token("q1", "i99")
        parts = decode_token(token)
        assert parts is not None
        assert parts.queue_id == "q1"
        assert parts.item_id == "i99"

    def test_is_echoweave_token(self):
        assert is_echoweave_token("ma:q:i") is True
        assert is_echoweave_token("other:token") is False


# ---------------------------------------------------------------------------
# Session store tests
# ---------------------------------------------------------------------------

class TestSessionStore:
    def test_create_session(self):
        store = SessionStore()
        session = store.update_session("device-1", queue_id="q1", play_state=PlayState.PLAYING)
        assert session.device_id == "device-1"
        assert session.queue_id == "q1"
        assert session.play_state == PlayState.PLAYING

    def test_get_session(self):
        store = SessionStore()
        store.update_session("device-1", queue_id="q1")
        session = store.get("device-1")
        assert session is not None
        assert session.queue_id == "q1"

    def test_get_nonexistent(self):
        store = SessionStore()
        assert store.get("no-such-device") is None

    def test_update_shifts_token(self):
        store = SessionStore()
        store.update_session("d1", current_track_token="track-1")
        store.update_session("d1", current_track_token="track-2")
        session = store.get("d1")
        assert session is not None
        assert session.current_track_token == "track-2"
        assert session.previous_track_token == "track-1"

    def test_partial_update(self):
        store = SessionStore()
        store.update_session("d1", queue_id="q1", play_state=PlayState.PLAYING)
        store.update_session("d1", last_event_type="PlaybackStarted")
        session = store.get("d1")
        assert session is not None
        assert session.queue_id == "q1"  # unchanged
        assert session.play_state == PlayState.PLAYING  # unchanged
        assert session.last_event_type == "PlaybackStarted"

    def test_delete_session(self):
        store = SessionStore()
        store.update_session("d1", queue_id="q1")
        store.delete("d1")
        assert store.get("d1") is None

    def test_list_all(self):
        store = SessionStore()
        store.update_session("d1", queue_id="q1")
        store.update_session("d2", queue_id="q2")
        sessions = store.list_all()
        assert len(sessions) == 2

    def test_persistence_roundtrip(self):
        """Session should survive write/read via PersistenceService."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = PersistenceService(tmpdir)
            store1 = SessionStore(persistence=persistence)
            store1.update_session("d1", queue_id="q1", play_state=PlayState.PLAYING,
                                  current_track_token="t1")

            # New store instance loading from same directory
            store2 = SessionStore(persistence=persistence)
            session = store2.get("d1")
            assert session is not None
            assert session.queue_id == "q1"
            assert session.play_state == PlayState.PLAYING
            assert session.current_track_token == "t1"
