"""Alexa AudioPlayer directive builders.

Helpers to construct the ``directives`` array included in Alexa responses
for audio playback control.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.constants import (
    ALEXA_CLEAR_BEHAVIOR_ALL,
    ALEXA_CLEAR_BEHAVIOR_ENQUEUED,
    ALEXA_PLAY_BEHAVIOR_ENQUEUE,
    ALEXA_PLAY_BEHAVIOR_REPLACE_ALL,
)


def play_directive(
    url: str,
    token: str,
    *,
    offset_ms: int = 0,
    play_behavior: str = ALEXA_PLAY_BEHAVIOR_REPLACE_ALL,
    expected_previous_token: Optional[str] = None,
) -> dict[str, Any]:
    """Build an ``AudioPlayer.Play`` directive.

    Parameters
    ----------
    url:
        HTTPS stream URL for Alexa to fetch.
    token:
        Opaque track token sent back by Alexa in playback events.
    offset_ms:
        Playback offset in milliseconds.
    play_behavior:
        ``REPLACE_ALL`` or ``ENQUEUE``.
    expected_previous_token:
        Required when ``play_behavior`` is ``ENQUEUE``.
    """
    stream: dict[str, Any] = {
        "url": url,
        "token": token,
        "offsetInMilliseconds": offset_ms,
    }
    if expected_previous_token is not None:
        stream["expectedPreviousToken"] = expected_previous_token

    return {
        "type": "AudioPlayer.Play",
        "playBehavior": play_behavior,
        "audioItem": {
            "stream": stream,
        },
    }


def stop_directive() -> dict[str, Any]:
    """Build an ``AudioPlayer.Stop`` directive."""
    return {"type": "AudioPlayer.Stop"}


def clear_queue_directive(
    clear_behavior: str = ALEXA_CLEAR_BEHAVIOR_ALL,
) -> dict[str, Any]:
    """Build an ``AudioPlayer.ClearQueue`` directive.

    Parameters
    ----------
    clear_behavior:
        ``CLEAR_ALL`` removes everything and stops playback.
        ``CLEAR_ENQUEUED`` removes upcoming but keeps current track.
    """
    return {
        "type": "AudioPlayer.ClearQueue",
        "clearBehavior": clear_behavior,
    }


def enqueue_directive(
    url: str,
    token: str,
    expected_previous_token: str,
    *,
    offset_ms: int = 0,
) -> dict[str, Any]:
    """Convenience wrapper: ``play_directive`` with ``ENQUEUE`` behavior."""
    return play_directive(
        url,
        token,
        offset_ms=offset_ms,
        play_behavior=ALEXA_PLAY_BEHAVIOR_ENQUEUE,
        expected_previous_token=expected_previous_token,
    )
