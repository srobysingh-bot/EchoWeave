"""Handle simple Alexa intents for MVP playback control.

Scope is intentionally narrow — only basic playback interactions are
implemented.  More complex intents (search, library browse, etc.) will
be added in later phases.
"""

from __future__ import annotations

import logging
from typing import Any

from app.alexa.directives import play_directive, stop_directive
from app.alexa.response_builder import build_response

logger = logging.getLogger(__name__)


async def handle_intent(body: dict[str, Any]) -> dict[str, Any]:
    """Dispatch an IntentRequest to the matching handler."""
    intent_name = body.get("request", {}).get("intent", {}).get("name", "")
    logger.info("Handling intent: %s", intent_name)

    handler = _INTENT_MAP.get(intent_name, _handle_unknown)
    return await handler(body)


# ---------------------------------------------------------------------------
# Individual intent handlers
# ---------------------------------------------------------------------------

async def _handle_play(body: dict[str, Any]) -> dict[str, Any]:
    """Handle PlayIntent — start or resume playback.

    TODO: Wire up to QueueMapper to fetch the current track from MA and
    respond with a Play directive containing the resolved stream URL.
    """
    logger.info("PlayIntent received — stub: no MA integration yet.")
    return build_response(
        speech="Playback will start once Music Assistant integration is complete.",
        should_end_session=True,
    )


async def _handle_pause(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.PauseIntent — pause current playback."""
    return build_response(directives=[stop_directive()], should_end_session=True)


async def _handle_resume(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.ResumeIntent — resume playback.

    TODO: Look up the paused session, resolve stream URL, send Play directive
    with saved offset.
    """
    logger.info("ResumeIntent received — stub.")
    return build_response(
        speech="Resume is not yet implemented.",
        should_end_session=True,
    )


async def _handle_next(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.NextIntent — skip to next track.

    TODO: Fetch next queue item from MA, resolve stream, send Play directive.
    """
    logger.info("NextIntent received — stub.")
    return build_response(
        speech="Next track is not yet implemented.",
        should_end_session=True,
    )


async def _handle_previous(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.PreviousIntent — go to previous track."""
    logger.info("PreviousIntent received — stub.")
    return build_response(
        speech="Previous track is not yet implemented.",
        should_end_session=True,
    )


async def _handle_stop(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.StopIntent / AMAZON.CancelIntent — stop playback."""
    return build_response(directives=[stop_directive()], should_end_session=True)


async def _handle_help(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.HelpIntent."""
    return build_response(
        speech=(
            "EchoWeave bridges Music Assistant to your Alexa device. "
            "Say 'play' to start music, 'pause' to pause, "
            "'next' or 'previous' to skip tracks, and 'stop' to end playback."
        ),
        should_end_session=False,
    )


async def _handle_unknown(body: dict[str, Any]) -> dict[str, Any]:
    """Fallback for unrecognised intents."""
    intent_name = body.get("request", {}).get("intent", {}).get("name", "")
    logger.warning("Unknown intent: %s", intent_name)
    return build_response(
        speech="Sorry, I don't understand that command.",
        should_end_session=False,
    )


# ---------------------------------------------------------------------------
# Intent dispatch map
# ---------------------------------------------------------------------------

_INTENT_MAP: dict[str, Any] = {
    "PlayIntent": _handle_play,
    "PlayAudio": _handle_play,
    "AMAZON.PauseIntent": _handle_pause,
    "AMAZON.ResumeIntent": _handle_resume,
    "AMAZON.NextIntent": _handle_next,
    "AMAZON.PreviousIntent": _handle_previous,
    "AMAZON.StopIntent": _handle_stop,
    "AMAZON.CancelIntent": _handle_stop,
    "AMAZON.HelpIntent": _handle_help,
}
