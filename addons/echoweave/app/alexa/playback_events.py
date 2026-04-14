"""Handle Alexa AudioPlayer lifecycle events.

These events are sent by the Alexa service to notify the skill about
changes in playback state on the device.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.alexa.response_builder import build_response
from app.alexa.session_store import get_session_store
from app.storage.models import PlayState

logger = logging.getLogger(__name__)


async def handle_playback_event(body: dict[str, Any]) -> dict[str, Any]:
    """Route an AudioPlayer.* event to the appropriate handler."""
    request_type = body.get("request", {}).get("type", "")
    handler = _EVENT_MAP.get(request_type, _handle_unknown_event)
    return await handler(body)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_event_context(body: dict[str, Any]) -> dict[str, str]:
    """Pull common fields from an AudioPlayer event."""
    request = body.get("request", {})
    context = body.get("context", {})
    audio_player = context.get("AudioPlayer", {})
    return {
        "token": request.get("token", audio_player.get("token", "")),
        "offset_ms": str(request.get("offsetInMilliseconds", audio_player.get("offsetInMilliseconds", 0))),
        "device_id": (
            context.get("System", {})
            .get("device", {})
            .get("deviceId", "unknown")
        ),
    }


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def _handle_playback_started(body: dict[str, Any]) -> dict[str, Any]:
    ctx = _extract_event_context(body)
    logger.info("PlaybackStarted — device=%s token=%s", ctx["device_id"], ctx["token"])
    logger.info(
        json.dumps(
            {
                "event": "alexa_playback_started",
                "device_id": ctx["device_id"],
                "token": ctx["token"],
                "offset_ms": ctx["offset_ms"],
            }
        )
    )

    store = get_session_store()
    store.update_session(
        device_id=ctx["device_id"],
        play_state=PlayState.PLAYING,
        current_track_token=ctx["token"],
        last_event_type="PlaybackStarted",
    )
    return build_response()


async def _handle_playback_stopped(body: dict[str, Any]) -> dict[str, Any]:
    ctx = _extract_event_context(body)
    logger.info("PlaybackStopped — device=%s token=%s offset=%s", ctx["device_id"], ctx["token"], ctx["offset_ms"])
    logger.info(
        json.dumps(
            {
                "event": "alexa_playback_stopped",
                "device_id": ctx["device_id"],
                "token": ctx["token"],
                "offset_ms": ctx["offset_ms"],
            }
        )
    )

    store = get_session_store()
    store.update_session(
        device_id=ctx["device_id"],
        play_state=PlayState.STOPPED,
        last_event_type="PlaybackStopped",
    )
    return build_response()


async def _handle_playback_finished(body: dict[str, Any]) -> dict[str, Any]:
    ctx = _extract_event_context(body)
    logger.info("PlaybackFinished — device=%s token=%s", ctx["device_id"], ctx["token"])

    store = get_session_store()
    store.update_session(
        device_id=ctx["device_id"],
        play_state=PlayState.FINISHED,
        last_event_type="PlaybackFinished",
    )
    return build_response()


async def _handle_playback_failed(body: dict[str, Any]) -> dict[str, Any]:
    ctx = _extract_event_context(body)
    error = body.get("request", {}).get("error", {})
    logger.error(
        "PlaybackFailed — device=%s token=%s error_type=%s message=%s",
        ctx["device_id"],
        ctx["token"],
        error.get("type", ""),
        error.get("message", ""),
    )
    logger.error(
        json.dumps(
            {
                "event": "alexa_playback_failed",
                "device_id": ctx["device_id"],
                "token": ctx["token"],
                "offset_ms": ctx["offset_ms"],
                "error_type": error.get("type", ""),
                "error_message": error.get("message", ""),
            }
        )
    )

    store = get_session_store()
    store.update_session(
        device_id=ctx["device_id"],
        play_state=PlayState.FAILED,
        last_event_type="PlaybackFailed",
    )
    return build_response()


async def _handle_playback_nearly_finished(body: dict[str, Any]) -> dict[str, Any]:
    """Critical event: Alexa tells us the current track is about to end.

    We must respond with the next track (ENQUEUE directive) so playback
    continues seamlessly.

    TODO: Wire up to QueueMapper.get_next_track_for_alexa() and return
    an enqueue directive with the resolved stream URL.
    """
    ctx = _extract_event_context(body)
    logger.info("PlaybackNearlyFinished — device=%s token=%s", ctx["device_id"], ctx["token"])

    store = get_session_store()
    store.update_session(
        device_id=ctx["device_id"],
        last_event_type="PlaybackNearlyFinished",
    )

    token = ctx["token"]
    if not token.startswith("ma:"):
        logger.debug("PlaybackNearlyFinished: Token does not start with 'ma:', ignoring.")
        return build_response()

    parts = token.split(":")
    if len(parts) < 3:
        logger.warning("PlaybackNearlyFinished: Malformed token '%s'", token)
        return build_response()

    queue_id = parts[1]

    from app.core.service_registry import registry
    from app.ma.queue_mapper import QueueMapper
    from app.ma.stream_resolver import StreamResolver
    from app.alexa.directives import enqueue_directive

    client = registry.get("ma_client")
    cfg = registry.get("config_service")
    if not client or not cfg:
        logger.error("PlaybackNearlyFinished: Missing dependencies in registry!")
        return build_response()

    resolver = StreamResolver(cfg.settings.stream_base_url, cfg.settings.allow_insecure_local_test)
    mapper = QueueMapper(client, resolver)

    try:
        next_track = await mapper.get_next_track_for_alexa(queue_id)
    except Exception as exc:
        logger.exception("PlaybackNearlyFinished: Failed to fetch next track.")
        return build_response()

    if not next_track:
        logger.info("PlaybackNearlyFinished: No next track in queue %s", queue_id)
        store.update_session(
            device_id=ctx["device_id"],
            expected_next_token="",
        )
        return build_response()

    logger.info("PlaybackNearlyFinished: Enqueueing next track %s", next_track["token"])
    store.update_session(
        device_id=ctx["device_id"],
        expected_next_token=next_track["token"],
    )

    directive = enqueue_directive(
        url=next_track["url"],
        token=next_track["token"],
        expected_previous_token=token,
    )
    return build_response(directives=[directive])


async def _handle_unknown_event(body: dict[str, Any]) -> dict[str, Any]:
    request_type = body.get("request", {}).get("type", "")
    logger.warning("Unhandled AudioPlayer event: %s", request_type)
    return build_response()


# ---------------------------------------------------------------------------
# Event dispatch map
# ---------------------------------------------------------------------------

_EVENT_MAP: dict[str, Any] = {
    "AudioPlayer.PlaybackStarted": _handle_playback_started,
    "AudioPlayer.PlaybackStopped": _handle_playback_stopped,
    "AudioPlayer.PlaybackFinished": _handle_playback_finished,
    "AudioPlayer.PlaybackFailed": _handle_playback_failed,
    "AudioPlayer.PlaybackNearlyFinished": _handle_playback_nearly_finished,
}
