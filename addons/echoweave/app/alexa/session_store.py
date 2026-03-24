"""In-memory + persistent playback session store.

Tracks the playback state of each Alexa device so the bridge can respond
correctly to lifecycle events and serve the right next-track.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.storage.models import PlayState, SessionRecord

logger = logging.getLogger(__name__)

# Module-level singleton — see ``get_session_store()``.
_instance: Optional["SessionStore"] = None


class SessionStore:
    """Thread-safe (single-event-loop) session state manager.

    Sessions are kept in memory for fast access and persisted to disk
    through the ``PersistenceService`` on every write so state survives
    restarts.
    """

    def __init__(self, persistence=None) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._persistence = persistence
        self._load_persisted()

    def _load_persisted(self) -> None:
        """Hydrate in-memory cache from persisted sessions on startup."""
        if self._persistence is None:
            return
        try:
            for session in self._persistence.list_sessions():
                self._sessions[session.device_id] = session
            logger.info("Loaded %d persisted sessions.", len(self._sessions))
        except Exception:
            logger.exception("Failed to load persisted sessions.")

    # -- read ----------------------------------------------------------------

    def get(self, device_id: str) -> SessionRecord | None:
        """Return the session for *device_id*, or ``None``."""
        return self._sessions.get(device_id)

    def list_all(self) -> list[SessionRecord]:
        """Return all active sessions."""
        return list(self._sessions.values())

    # -- write ---------------------------------------------------------------

    def update_session(
        self,
        device_id: str,
        *,
        queue_id: str | None = None,
        play_state: PlayState | None = None,
        current_track_token: str | None = None,
        previous_track_token: str | None = None,
        expected_next_token: str | None = None,
        last_event_type: str | None = None,
    ) -> SessionRecord:
        """Create or update the session for *device_id*.

        Only the provided keyword arguments are changed; ``None`` values
        are skipped so callers only need to pass the fields they want to
        update.
        """
        session = self._sessions.get(device_id)
        if session is None:
            session = SessionRecord(device_id=device_id)

        if queue_id is not None:
            session.queue_id = queue_id
        if play_state is not None:
            session.play_state = play_state
        if current_track_token is not None:
            # Shift current → previous before overwriting.
            session.previous_track_token = session.current_track_token
            session.current_track_token = current_track_token
        if expected_next_token is not None:
            session.expected_next_token = expected_next_token
        if last_event_type is not None:
            session.last_event_type = last_event_type
            session.last_event_timestamp = datetime.utcnow()

        session.updated_at = datetime.utcnow()
        self._sessions[device_id] = session
        self._persist(session)
        return session

    def delete(self, device_id: str) -> None:
        """Remove session for *device_id*."""
        self._sessions.pop(device_id, None)
        if self._persistence:
            self._persistence.delete_session(device_id)

    # -- persistence ---------------------------------------------------------

    def _persist(self, session: SessionRecord) -> None:
        if self._persistence is None:
            return
        try:
            self._persistence.save_session(session)
        except Exception:
            logger.exception("Failed to persist session for device %s", session.device_id)


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------

def init_session_store(persistence=None) -> SessionStore:
    """Create the singleton ``SessionStore`` (called at app startup)."""
    global _instance
    _instance = SessionStore(persistence=persistence)
    return _instance


def get_session_store() -> SessionStore:
    """Return the singleton ``SessionStore``.

    Raises ``RuntimeError`` if ``init_session_store()`` has not been called.
    """
    if _instance is None:
        raise RuntimeError("SessionStore has not been initialised. Call init_session_store() first.")
    return _instance
