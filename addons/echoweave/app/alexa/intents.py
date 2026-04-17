"""Handle Alexa intents for playback control.

Each intent handler integrates with Music Assistant through the service
registry, resolving real tracks and issuing AudioPlayer directives so
Alexa actually plays audio.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.alexa.directives import play_directive, stop_directive, clear_queue_directive
from app.alexa.response_builder import build_response
from app.alexa.token_mapper import decode_token, encode_token
from app.alexa.validators import extract_device_id
from app.core.service_registry import registry
from app.ma.queue_mapper import QueueMapper
from app.ma.stream_resolver import StreamResolver
from app.storage.models import PlayState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_dependencies() -> tuple[Any, Any, Any] | None:
    """Return (ma_client, config_service, session_store) or None."""
    ma_client = registry.get_optional("ma_client")
    config_svc = registry.get_optional("config_service")
    session_store = registry.get_optional("session_store")
    if not ma_client or not config_svc:
        logger.error("Intent handler: missing ma_client or config_service in registry.")
        return None
    return ma_client, config_svc, session_store


def _build_mapper(ma_client: Any, config_svc: Any) -> QueueMapper:
    settings = config_svc.settings
    resolver = StreamResolver(
        settings.stream_base_url,
        settings.allow_insecure_local_test,
    )
    return QueueMapper(ma_client, resolver)


def _extract_query(body: dict[str, Any]) -> str:
    """Pull a search query from the intent slots (covers common slot names)."""
    slots = body.get("request", {}).get("intent", {}).get("slots", {})
    for slot_name in ("query", "searchQuery", "SearchQuery", "musicQuery", "phrase"):
        slot = slots.get(slot_name, {})
        value = slot.get("value", "")
        if value and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _get_queue_id_from_session(body: dict[str, Any], session_store: Any) -> str:
    """Try to recover the queue_id from the device's previous session."""
    if session_store is None:
        return ""
    device_id = extract_device_id(body)
    session = session_store.get(device_id)
    if session and session.queue_id:
        return session.queue_id
    if session and session.current_track_token:
        parts = decode_token(session.current_track_token)
        if parts:
            return parts.queue_id
    return ""


def _get_offset_from_session(body: dict[str, Any], session_store: Any) -> int:
    """Return saved playback offset from the AudioPlayer context, in ms."""
    audio_player = body.get("context", {}).get("AudioPlayer", {})
    offset = audio_player.get("offsetInMilliseconds", 0)
    if isinstance(offset, (int, float)) and offset > 0:
        return int(offset)
    return 0


async def handle_intent(body: dict[str, Any]) -> dict[str, Any]:
    """Dispatch an IntentRequest to the matching handler."""
    intent_name = body.get("request", {}).get("intent", {}).get("name", "")
    logger.info("Handling intent: %s", intent_name)

    handler = _INTENT_MAP.get(intent_name, _handle_unknown)
    logger.info("Intent '%s' mapped to handler '%s'", intent_name, handler.__name__)
    return await handler(body)


# ---------------------------------------------------------------------------
# Individual intent handlers
# ---------------------------------------------------------------------------

async def _handle_play(body: dict[str, Any]) -> dict[str, Any]:
    """Handle PlayIntent / PlayAudio — start playback from MA queue.

    Resolves the current track from Music Assistant, builds a public
    stream URL, and returns an AudioPlayer.Play directive to Alexa.
    """
    deps = _get_dependencies()
    if deps is None:
        return build_response(
            speech="Music Assistant is not connected yet. Please check your EchoWeave setup.",
            should_end_session=True,
        )

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)
    query = _extract_query(body)
    queue_id = _get_queue_id_from_session(body, session_store) or config_svc.settings.alexa_source_queue_id

    try:
        if query:
            logger.info("PlayIntent: search query=%s device=%s", query, device_id)
            resolved = await ma_client.resolve_play_request(
                queue_id=queue_id or None,
                query=query,
                intent_name="PlayIntent",
                request_id="",
                home_id=config_svc.settings.home_id,
                player_id="",
            )
            if not resolved:
                return build_response(
                    speech=f"I couldn't find anything matching '{query}' in Music Assistant.",
                    should_end_session=True,
                )
            # Build stream URL from resolved item
            mapper = _build_mapper(ma_client, config_svc)
            item_queue_id = resolved.get("queue_id", queue_id)
            item_queue_item_id = resolved.get("queue_item_id", "")
            token = encode_token(item_queue_id, item_queue_item_id)
            origin_path = resolved.get("origin_stream_path", "")
            # Resolve a public stream URL
            resolver = StreamResolver(
                config_svc.settings.stream_base_url,
                config_svc.settings.allow_insecure_local_test,
            )
            from app.ma.models import MAQueueItem
            fake_item = MAQueueItem(
                queue_id=item_queue_id,
                queue_item_id=item_queue_item_id,
                uri=resolved.get("uri", ""),
            )
            stream_url = resolver.resolve(fake_item)
        else:
            mapper = _build_mapper(ma_client, config_svc)
            track = await mapper.get_current_track_for_alexa(queue_id) if queue_id else None
            if track is None:
                # Auto-discover active queue
                discovered_queue_id = await ma_client._resolve_default_queue_id()
                if discovered_queue_id:
                    track = await mapper.get_current_track_for_alexa(discovered_queue_id)
                    queue_id = discovered_queue_id

            if track is None:
                return build_response(
                    speech="There's nothing in the Music Assistant queue right now. Add some music first.",
                    should_end_session=True,
                )

            token = track["token"]
            stream_url = track["url"]

        logger.info("PlayIntent: sending Play directive token=%s url=%s device=%s", token, stream_url, device_id)

        if session_store:
            parts = decode_token(token)
            session_store.update_session(
                device_id=device_id,
                queue_id=parts.queue_id if parts else queue_id,
                play_state=PlayState.PLAYING,
                current_track_token=token,
                last_event_type="PlayIntent",
            )

        return build_response(
            directives=[play_directive(url=stream_url, token=token)],
            should_end_session=True,
        )

    except Exception:
        logger.exception("PlayIntent failed for device=%s", device_id)
        return build_response(
            speech="Sorry, I couldn't start playback from Music Assistant right now.",
            should_end_session=True,
        )


async def _handle_pause(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.PauseIntent — pause current playback on Alexa and MA."""
    device_id = extract_device_id(body)
    logger.info("PauseIntent: device=%s", device_id)

    # Forward pause to MA so both sides stay in sync
    deps = _get_dependencies()
    if deps:
        ma_client, config_svc, session_store = deps
        queue_id = _get_queue_id_from_session(body, session_store) or config_svc.settings.alexa_source_queue_id
        try:
            if queue_id:
                await ma_client._post_command_with_fallback(
                    ["player_queues/pause", "playerqueues/pause", "players/cmd/pause"],
                    queue_id=queue_id,
                )
            else:
                players = await ma_client.get_players()
                for player in players:
                    pid = str(player.get("player_id") or "").strip()
                    if pid:
                        try:
                            await ma_client._post_command("players/cmd/pause", player_id=pid)
                            break
                        except Exception:
                            continue
            logger.info("PauseIntent: forwarded pause to MA for device=%s", device_id)
        except Exception:
            logger.warning("PauseIntent: failed to forward pause to MA", exc_info=True)

        if session_store:
            session_store.update_session(
                device_id=device_id,
                play_state=PlayState.PAUSED,
                last_event_type="PauseIntent",
            )

    return build_response(directives=[stop_directive()], should_end_session=True)


async def _handle_resume(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.ResumeIntent — resume playback from saved position."""
    deps = _get_dependencies()
    if deps is None:
        return build_response(
            speech="Music Assistant is not connected.",
            should_end_session=True,
        )

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)
    offset_ms = _get_offset_from_session(body, session_store)
    queue_id = _get_queue_id_from_session(body, session_store) or config_svc.settings.alexa_source_queue_id

    # Try to get the token from AudioPlayer context first
    audio_player = body.get("context", {}).get("AudioPlayer", {})
    current_token = audio_player.get("token", "")

    try:
        mapper = _build_mapper(ma_client, config_svc)

        # If we have a valid token from the paused state, resolve that track
        if current_token:
            parts = decode_token(current_token)
            if parts:
                track = await mapper.get_current_track_for_alexa(parts.queue_id)
                if track:
                    logger.info(
                        "ResumeIntent: resuming token=%s offset=%d device=%s",
                        track["token"], offset_ms, device_id,
                    )

                    # Forward resume to MA
                    try:
                        await ma_client.execute_play_command(parts.queue_id)
                    except Exception:
                        logger.warning("ResumeIntent: failed to forward resume to MA", exc_info=True)

                    if session_store:
                        session_store.update_session(
                            device_id=device_id,
                            queue_id=parts.queue_id,
                            play_state=PlayState.PLAYING,
                            current_track_token=track["token"],
                            last_event_type="ResumeIntent",
                        )

                    return build_response(
                        directives=[play_directive(
                            url=track["url"],
                            token=track["token"],
                            offset_ms=offset_ms,
                        )],
                        should_end_session=True,
                    )

        # Fallback: get current track from queue
        track = None
        if queue_id:
            track = await mapper.get_current_track_for_alexa(queue_id)
        if track is None:
            discovered = await ma_client._resolve_default_queue_id()
            if discovered:
                track = await mapper.get_current_track_for_alexa(discovered)
                queue_id = discovered

        if track is None:
            return build_response(
                speech="There's nothing to resume. Try saying 'play' to start.",
                should_end_session=True,
            )

        # Forward resume to MA
        try:
            await ma_client.execute_play_command(queue_id)
        except Exception:
            logger.warning("ResumeIntent: failed to forward resume to MA", exc_info=True)

        logger.info("ResumeIntent: playing token=%s offset=%d device=%s", track["token"], offset_ms, device_id)

        if session_store:
            parsed = decode_token(track["token"])
            session_store.update_session(
                device_id=device_id,
                queue_id=parsed.queue_id if parsed else queue_id,
                play_state=PlayState.PLAYING,
                current_track_token=track["token"],
                last_event_type="ResumeIntent",
            )

        return build_response(
            directives=[play_directive(
                url=track["url"],
                token=track["token"],
                offset_ms=offset_ms,
            )],
            should_end_session=True,
        )

    except Exception:
        logger.exception("ResumeIntent failed for device=%s", device_id)
        return build_response(
            speech="Sorry, I couldn't resume playback right now.",
            should_end_session=True,
        )


async def _handle_next(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.NextIntent — skip to next track."""
    deps = _get_dependencies()
    if deps is None:
        return build_response(
            speech="Music Assistant is not connected.",
            should_end_session=True,
        )

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)
    queue_id = _get_queue_id_from_session(body, session_store) or config_svc.settings.alexa_source_queue_id

    try:
        # Send next command to MA first
        if queue_id:
            try:
                await ma_client._post_command_with_fallback(
                    ["player_queues/next", "playerqueues/next"],
                    queue_id=queue_id,
                )
            except Exception:
                logger.warning("NextIntent: queue next command failed, trying player cmd", exc_info=True)

        mapper = _build_mapper(ma_client, config_svc)

        track = None
        if queue_id:
            track = await mapper.get_next_track_for_alexa(queue_id)
            if track is None:
                # After sending next to MA, current may have advanced
                track = await mapper.get_current_track_for_alexa(queue_id)
        if track is None:
            discovered = await ma_client._resolve_default_queue_id()
            if discovered:
                track = await mapper.get_current_track_for_alexa(discovered)
                queue_id = discovered

        if track is None:
            return build_response(
                speech="There are no more tracks in the queue.",
                should_end_session=True,
            )

        logger.info("NextIntent: playing next token=%s device=%s", track["token"], device_id)

        if session_store:
            parsed = decode_token(track["token"])
            session_store.update_session(
                device_id=device_id,
                queue_id=parsed.queue_id if parsed else queue_id,
                play_state=PlayState.PLAYING,
                current_track_token=track["token"],
                last_event_type="NextIntent",
            )

        return build_response(
            directives=[play_directive(url=track["url"], token=track["token"])],
            should_end_session=True,
        )

    except Exception:
        logger.exception("NextIntent failed for device=%s", device_id)
        return build_response(
            speech="Sorry, I couldn't skip to the next track.",
            should_end_session=True,
        )


async def _handle_previous(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.PreviousIntent — go to previous track."""
    deps = _get_dependencies()
    if deps is None:
        return build_response(
            speech="Music Assistant is not connected.",
            should_end_session=True,
        )

    ma_client, config_svc, session_store = deps
    device_id = extract_device_id(body)
    queue_id = _get_queue_id_from_session(body, session_store) or config_svc.settings.alexa_source_queue_id

    try:
        # Send previous command to MA
        if queue_id:
            try:
                await ma_client._post_command_with_fallback(
                    ["player_queues/previous", "playerqueues/previous"],
                    queue_id=queue_id,
                )
            except Exception:
                logger.warning("PreviousIntent: queue previous command failed", exc_info=True)

        # After MA advances, fetch the (now-current) track
        mapper = _build_mapper(ma_client, config_svc)
        track = None
        if queue_id:
            track = await mapper.get_current_track_for_alexa(queue_id)
        if track is None:
            discovered = await ma_client._resolve_default_queue_id()
            if discovered:
                track = await mapper.get_current_track_for_alexa(discovered)
                queue_id = discovered

        if track is None:
            return build_response(
                speech="There's no previous track available.",
                should_end_session=True,
            )

        logger.info("PreviousIntent: playing token=%s device=%s", track["token"], device_id)

        if session_store:
            parsed = decode_token(track["token"])
            session_store.update_session(
                device_id=device_id,
                queue_id=parsed.queue_id if parsed else queue_id,
                play_state=PlayState.PLAYING,
                current_track_token=track["token"],
                last_event_type="PreviousIntent",
            )

        return build_response(
            directives=[play_directive(url=track["url"], token=track["token"])],
            should_end_session=True,
        )

    except Exception:
        logger.exception("PreviousIntent failed for device=%s", device_id)
        return build_response(
            speech="Sorry, I couldn't go to the previous track.",
            should_end_session=True,
        )


async def _handle_stop(body: dict[str, Any]) -> dict[str, Any]:
    """Handle AMAZON.StopIntent / AMAZON.CancelIntent — stop playback on Alexa and MA."""
    device_id = extract_device_id(body)
    logger.info("StopIntent: device=%s", device_id)

    # Forward stop to MA
    deps = _get_dependencies()
    if deps:
        ma_client, config_svc, session_store = deps
        queue_id = _get_queue_id_from_session(body, session_store) or config_svc.settings.alexa_source_queue_id
        try:
            if queue_id:
                await ma_client._post_command_with_fallback(
                    ["player_queues/stop", "playerqueues/stop", "players/cmd/stop"],
                    queue_id=queue_id,
                )
            else:
                players = await ma_client.get_players()
                for player in players:
                    pid = str(player.get("player_id") or "").strip()
                    if pid:
                        try:
                            await ma_client._post_command("players/cmd/stop", player_id=pid)
                            break
                        except Exception:
                            continue
            logger.info("StopIntent: forwarded stop to MA for device=%s", device_id)
        except Exception:
            logger.warning("StopIntent: failed to forward stop to MA", exc_info=True)

        if session_store:
            session_store.update_session(
                device_id=device_id,
                play_state=PlayState.STOPPED,
                last_event_type="StopIntent",
            )

    return build_response(
        directives=[stop_directive(), clear_queue_directive()],
        should_end_session=True,
    )


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
