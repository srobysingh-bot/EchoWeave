"""Handle Alexa PlaybackController events (physical button presses).

PlaybackController commands arrive when the user presses play/pause/next/prev
buttons on the Alexa device or companion app.  Unlike intents, these carry no
session and must respond with AudioPlayer directives only (no speech).
"""

from __future__ import annotations

import logging
from typing import Any

from app.alexa.directives import play_directive, stop_directive
from app.alexa.response_builder import build_response
from app.alexa.token_mapper import decode_token
from app.alexa.validators import extract_device_id
from app.core.service_registry import registry
from app.ma.queue_mapper import QueueMapper
from app.ma.stream_resolver import StreamResolver
from app.storage.models import PlayState

logger = logging.getLogger(__name__)


def _get_deps() -> tuple[Any, Any, Any] | None:
    ma_client = registry.get_optional("ma_client")
    config_svc = registry.get_optional("config_service")
    session_store = registry.get_optional("session_store")
    if not ma_client or not config_svc:
        return None
    return ma_client, config_svc, session_store


def _build_mapper(ma_client: Any, config_svc: Any) -> QueueMapper:
    s = config_svc.settings
    return QueueMapper(ma_client, StreamResolver(s.stream_base_url, s.allow_insecure_local_test))


async def handle_playback_controller(body: dict[str, Any]) -> dict[str, Any]:
    """Route a PlaybackController.* request to the matching handler."""
    request_type = body.get("request", {}).get("type", "")
    handler = _CONTROLLER_MAP.get(request_type, _handle_unknown_controller)
    return await handler(body)


async def _handle_play_command(body: dict[str, Any]) -> dict[str, Any]:
    """PlaybackController.PlayCommandIssued — resume or start playback."""
    deps = _get_deps()
    if deps is None:
        return build_response()

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)

    audio_player = body.get("context", {}).get("AudioPlayer", {})
    token = audio_player.get("token", "")
    offset = int(audio_player.get("offsetInMilliseconds", 0))
    queue_id = config_svc.settings.alexa_source_queue_id

    if session_store:
        session = session_store.get(device_id)
        if session and session.queue_id:
            queue_id = session.queue_id

    if token:
        parts = decode_token(token)
        if parts:
            queue_id = parts.queue_id

    try:
        mapper = _build_mapper(ma_client, config_svc)
        track = None
        if queue_id:
            track = await mapper.get_current_track_for_alexa(queue_id)
        if track is None:
            discovered = await ma_client._resolve_default_queue_id()
            if discovered:
                track = await mapper.get_current_track_for_alexa(discovered)

        if track is None:
            return build_response()

        # Forward play to MA
        try:
            await ma_client.execute_play_command(queue_id)
        except Exception:
            logger.warning("PlaybackController.Play: MA forward failed", exc_info=True)

        if session_store:
            session_store.update_session(
                device_id=device_id, play_state=PlayState.PLAYING,
                current_track_token=track["token"],
                last_event_type="PlaybackController.PlayCommandIssued",
            )

        return build_response(
            directives=[play_directive(url=track["url"], token=track["token"], offset_ms=offset)],
        )
    except Exception:
        logger.exception("PlaybackController.Play failed device=%s", device_id)
        return build_response()


async def _handle_pause_command(body: dict[str, Any]) -> dict[str, Any]:
    """PlaybackController.PauseCommandIssued — pause playback."""
    deps = _get_deps()
    device_id = extract_device_id(body)

    if deps:
        ma_client, config_svc, session_store = deps
        queue_id = config_svc.settings.alexa_source_queue_id
        if session_store:
            session = session_store.get(device_id)
            if session and session.queue_id:
                queue_id = session.queue_id
        try:
            if queue_id:
                await ma_client._post_command_with_fallback(
                    ["player_queues/pause", "playerqueues/pause", "players/cmd/pause"],
                    queue_id=queue_id,
                )
        except Exception:
            logger.warning("PlaybackController.Pause: MA forward failed", exc_info=True)

        if session_store:
            session_store.update_session(
                device_id=device_id, play_state=PlayState.PAUSED,
                last_event_type="PlaybackController.PauseCommandIssued",
            )

    return build_response(directives=[stop_directive()])


async def _handle_next_command(body: dict[str, Any]) -> dict[str, Any]:
    """PlaybackController.NextCommandIssued — skip to next track."""
    deps = _get_deps()
    if deps is None:
        return build_response()

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)
    queue_id = config_svc.settings.alexa_source_queue_id
    if session_store:
        session = session_store.get(device_id)
        if session and session.queue_id:
            queue_id = session.queue_id

    try:
        if queue_id:
            try:
                await ma_client._post_command_with_fallback(
                    ["player_queues/next", "playerqueues/next"],
                    queue_id=queue_id,
                )
            except Exception:
                logger.warning("PlaybackController.Next: MA forward failed", exc_info=True)

        mapper = _build_mapper(ma_client, config_svc)
        track = None
        if queue_id:
            track = await mapper.get_next_track_for_alexa(queue_id)
            if track is None:
                track = await mapper.get_current_track_for_alexa(queue_id)
        if track is None:
            return build_response()

        if session_store:
            session_store.update_session(
                device_id=device_id, play_state=PlayState.PLAYING,
                current_track_token=track["token"],
                last_event_type="PlaybackController.NextCommandIssued",
            )

        return build_response(
            directives=[play_directive(url=track["url"], token=track["token"])],
        )
    except Exception:
        logger.exception("PlaybackController.Next failed device=%s", device_id)
        return build_response()


async def _handle_previous_command(body: dict[str, Any]) -> dict[str, Any]:
    """PlaybackController.PreviousCommandIssued — go to previous track."""
    deps = _get_deps()
    if deps is None:
        return build_response()

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)
    queue_id = config_svc.settings.alexa_source_queue_id
    if session_store:
        session = session_store.get(device_id)
        if session and session.queue_id:
            queue_id = session.queue_id

    try:
        if queue_id:
            try:
                await ma_client._post_command_with_fallback(
                    ["player_queues/previous", "playerqueues/previous"],
                    queue_id=queue_id,
                )
            except Exception:
                logger.warning("PlaybackController.Previous: MA forward failed", exc_info=True)

        mapper = _build_mapper(ma_client, config_svc)
        track = None
        if queue_id:
            track = await mapper.get_current_track_for_alexa(queue_id)
        if track is None:
            return build_response()

        if session_store:
            session_store.update_session(
                device_id=device_id, play_state=PlayState.PLAYING,
                current_track_token=track["token"],
                last_event_type="PlaybackController.PreviousCommandIssued",
            )

        return build_response(
            directives=[play_directive(url=track["url"], token=track["token"])],
        )
    except Exception:
        logger.exception("PlaybackController.Previous failed device=%s", device_id)
        return build_response()


async def _handle_unknown_controller(body: dict[str, Any]) -> dict[str, Any]:
    request_type = body.get("request", {}).get("type", "")
    logger.warning("Unhandled PlaybackController command: %s", request_type)
    return build_response()


_CONTROLLER_MAP: dict[str, Any] = {
    "PlaybackController.PlayCommandIssued": _handle_play_command,
    "PlaybackController.PauseCommandIssued": _handle_pause_command,
    "PlaybackController.NextCommandIssued": _handle_next_command,
    "PlaybackController.PreviousCommandIssued": _handle_previous_command,
}
