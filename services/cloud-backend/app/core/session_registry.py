from __future__ import annotations


class SessionRegistry:
    """In-memory session map for early cloud baseline."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    def put(self, session_id: str, payload: dict) -> None:
        self._sessions[session_id] = payload

    def get(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)


session_registry = SessionRegistry()
