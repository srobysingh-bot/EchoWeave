"""Music Assistant callback router.

Handles inbound requests from Music Assistant, such as push-url notifications.
"""

from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.constants import APP_BUILD_ID, APP_QUERY_RESOLUTION_REV, APP_VERSION
from app.core.service_registry import registry
from app.ma.stream_resolver import is_valid_alexa_stream_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ma", tags=["ma"])

_PUSH_URL_COALESCE_WINDOW_SEC = 8.0
_PUSH_URL_PLAYER_LOCKS: dict[str, asyncio.Lock] = {}
_PUSH_URL_SESSION_CACHE: dict[str, dict[str, Any]] = {}


def _get_push_url_player_lock(coalesce_key: str) -> asyncio.Lock:
    lock = _PUSH_URL_PLAYER_LOCKS.get(coalesce_key)
    if lock is None:
        lock = asyncio.Lock()
        _PUSH_URL_PLAYER_LOCKS[coalesce_key] = lock
    return lock


def _is_alexa_like_player(player: dict[str, Any] | None) -> bool:
    if not isinstance(player, dict):
        return False
    fields = [
        str(player.get("provider") or ""),
        str(player.get("source") or ""),
        str(player.get("platform") or ""),
        str(player.get("player_id") or ""),
        str(player.get("name") or ""),
    ]
    blob = " ".join(fields).lower()
    return ("alexa" in blob) or ("echo" in blob)


def _is_alexa_request(body: dict[str, Any], matched_player: dict[str, Any] | None) -> bool:
    provider_hint = str(
        body.get("provider")
        or body.get("source")
        or body.get("integration")
        or ""
    ).strip().lower()
    if provider_hint == "alexa":
        return True
    return _is_alexa_like_player(matched_player)


async def _readback_player_state(
    *,
    ma_client: Any,
    player_id: str,
    preferred_queue_id: str,
    request_id: str,
    home_id: str,
    reused_session: bool,
) -> dict[str, Any]:
    playback_state = ""
    current_media_title = ""
    queue_length = 0
    queue_id = ""
    queue_readback_error = ""

    players = await ma_client.get_players()
    target_player = next(
        (
            player
            for player in players
            if str(player.get("player_id") or player.get("id") or "").strip() == player_id
        ),
        {},
    )

    playback_state = str(target_player.get("state") or "")
    current_media = target_player.get("current_media") or {}
    if isinstance(current_media, dict):
        current_media_title = str(current_media.get("title") or current_media.get("name") or "")

    queue_candidates = [
        preferred_queue_id,
        str(target_player.get("active_queue") or ""),
        str(target_player.get("active_source") or ""),
        str(target_player.get("queue_id") or ""),
    ]
    for candidate in queue_candidates:
        candidate_value = str(candidate or "").strip()
        if candidate_value:
            queue_id = candidate_value
            break

    if queue_id:
        try:
            queue_items = await ma_client.get_queue_items(
                queue_id,
                request_id=request_id,
                home_id=home_id,
                player_id=player_id,
            )
            queue_length = len(queue_items)
        except Exception as exc:
            queue_readback_error = str(exc)

    snapshot = {
        "player_id": player_id,
        "playback_state": playback_state,
        "current_media_title": current_media_title,
        "queue_length": queue_length,
        "queue_id": queue_id,
        "queue_readback_error": queue_readback_error,
        "reused_session": reused_session,
    }

    logger.info(
        json.dumps(
            {
                "event": "ma_push_url_session_start_final",
                "request_id": request_id,
                "home_id": home_id,
                **snapshot,
            }
        )
    )
    return snapshot


def _extract_flow_parts(stream_url: str) -> dict[str, str]:
    parsed = urlparse(stream_url)
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[0] != "flow":
        return {}
    # /flow/<session_id>/<player_id_or_name>/<item_id>/...
    return {
        "session_id": parts[1],
        "player_hint": parts[2],
        "item_id": parts[3],
        "path": parsed.path,
        "query": parsed.query,
    }


def _build_public_playback_url(stream_url: str, settings: Any) -> str:
    parsed = urlparse(stream_url)
    if not parsed.path:
        raise ValueError("missing-stream-path")

    if is_valid_alexa_stream_url(stream_url, allow_insecure=False):
        return stream_url

    base_url = (
        getattr(settings, "stream_base_url", "")
        or getattr(settings, "tunnel_base_url", "")
        or getattr(settings, "public_base_url", "")
    )
    if not base_url:
        raise ValueError("missing-public-base-url")

    base_parsed = urlparse(base_url)
    path = "/" + "/".join(quote(unquote(seg), safe="") for seg in parsed.path.split("/") if seg)
    playback_url = urlunparse(
        (
            base_parsed.scheme,
            base_parsed.netloc,
            path,
            "",
            parsed.query,
            "",
        )
    )
    if not is_valid_alexa_stream_url(playback_url, allow_insecure=False):
        raise ValueError("public-url-not-alexa-compatible")
    return playback_url


async def _request_worker_handoff(
    *,
    request_id: str,
    settings: Any,
    flow: dict[str, str],
    player_id: str,
    title: str,
) -> dict[str, Any]:
    worker_base_url = str(getattr(settings, "worker_base_url", "") or "").rstrip("/")
    connector_id = str(getattr(settings, "connector_id", "") or "")
    connector_secret = str(getattr(settings, "connector_secret", "") or "")
    tenant_id = str(getattr(settings, "tenant_id", "") or "")
    home_id = str(getattr(settings, "home_id", "") or "")

    if not worker_base_url:
        raise ValueError("missing-worker-base-url")
    if not connector_id or not connector_secret or not tenant_id or not home_id:
        raise ValueError("missing-connector-auth")

    queue_id = str(flow.get("session_id") or "").strip()
    queue_item_id = str(flow.get("item_id") or "").strip()
    origin_stream_path = str(flow.get("path") or "").strip()
    if not queue_id or not queue_item_id or not origin_stream_path:
        raise ValueError("missing-flow-identifiers")

    endpoint = f"{worker_base_url}/v1/connectors/playback-handoff"
    payload = {
        "request_id": request_id,
        "connector_id": connector_id,
        "connector_secret": connector_secret,
        "tenant_id": tenant_id,
        "home_id": home_id,
        "player_id": player_id,
        "queue_id": queue_id,
        "queue_item_id": queue_item_id,
        "origin_stream_path": origin_stream_path,
        "title": title,
    }

    logger.info(
        json.dumps(
            {
                "event": "ma_worker_handoff_request_sent",
                "request_id": request_id,
                "worker_endpoint": endpoint,
                "tenant_id": tenant_id,
                "home_id": home_id,
                "player_id": player_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "origin_stream_path": origin_stream_path,
            }
        )
    )

    timeout = httpx.Timeout(12.0, connect=6.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload)

    body_text = (response.text or "")[:4000]
    runtime: dict[str, Any] = {}
    if body_text:
        try:
            parsed_body = response.json()
            if isinstance(parsed_body, dict):
                maybe_runtime = parsed_body.get("runtime")
                if isinstance(maybe_runtime, dict):
                    runtime = maybe_runtime
        except Exception:
            runtime = {}

    logger.info(
        json.dumps(
            {
                "event": "ma_worker_handoff_response",
                "request_id": request_id,
                "status": response.status_code,
                "ok": response.is_success,
                "body": body_text,
                "worker_runtime": runtime,
            }
        )
    )

    if not response.is_success:
        raise ValueError(f"worker-handoff-failed:{response.status_code}")

    data = response.json() if body_text else {}
    stream_url = str((data or {}).get("stream_url") or "").strip()
    if not stream_url:
        raise ValueError("worker-handoff-missing-stream-url")

    logger.info(
        json.dumps(
            {
                "event": "ma_worker_handoff_tokenized_url_created",
                "request_id": request_id,
                "stream_url": stream_url,
                "playback_session_id": (data or {}).get("playback_session_id", ""),
                "stream_token_id": (data or {}).get("stream_token_id", ""),
            }
        )
    )
    return data or {}


async def _fetch_worker_playback_start_status(
    *,
    request_id: str,
    settings: Any,
    playback_session_id: str,
) -> dict[str, Any]:
    worker_base_url = str(getattr(settings, "worker_base_url", "") or "").rstrip("/")
    connector_id = str(getattr(settings, "connector_id", "") or "")
    connector_secret = str(getattr(settings, "connector_secret", "") or "")
    tenant_id = str(getattr(settings, "tenant_id", "") or "")
    home_id = str(getattr(settings, "home_id", "") or "")

    if not worker_base_url:
        raise ValueError("missing-worker-base-url")
    if not connector_id or not connector_secret or not tenant_id or not home_id:
        raise ValueError("missing-connector-auth")
    if not playback_session_id:
        raise ValueError("missing-playback-session-id")

    endpoint = f"{worker_base_url}/v1/connectors/playback-start-status"
    payload = {
        "request_id": request_id,
        "connector_id": connector_id,
        "connector_secret": connector_secret,
        "tenant_id": tenant_id,
        "home_id": home_id,
        "playback_session_id": playback_session_id,
    }

    timeout = httpx.Timeout(6.0, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload)

    if not response.is_success:
        raise ValueError(f"worker-playback-start-status-failed:{response.status_code}")
    parsed = response.json()
    if isinstance(parsed, dict):
        return parsed
    return {}


async def _wait_for_worker_stream_fetch_start(
    *,
    request_id: str,
    settings: Any,
    playback_session_id: str,
    wait_seconds: float = 5.0,
    poll_interval_seconds: float = 1.0,
) -> tuple[bool, dict[str, Any]]:
    started_at = monotonic()
    last_status: dict[str, Any] = {}

    while monotonic() - started_at < wait_seconds:
        status = await _fetch_worker_playback_start_status(
            request_id=request_id,
            settings=settings,
            playback_session_id=playback_session_id,
        )
        if isinstance(status, dict):
            last_status = status

        stream_fetch_started = bool((status or {}).get("stream_fetch_started"))
        logger.info(
            json.dumps(
                {
                    "event": "ma_push_url_device_start_probe",
                    "request_id": request_id,
                    "playback_session_id": playback_session_id,
                    "stream_fetch_started": stream_fetch_started,
                    "known_session": bool((status or {}).get("known_session")),
                    "age_ms": (status or {}).get("age_ms"),
                }
            )
        )
        if stream_fetch_started:
            return True, status

        await asyncio.sleep(poll_interval_seconds)

    return False, last_status


def _resolve_player_id(player_hint: str, players: list[dict[str, Any]]) -> str:
    hint = (player_hint or "").strip()
    if not hint:
        return ""
    hint_lower = hint.lower()
    for player in players:
        player_id = str(player.get("player_id") or player.get("id") or "").strip()
        name = str(player.get("name") or "").strip()
        if player_id and (player_id == hint or player_id.lower() == hint_lower):
            return player_id
        if name and name.lower() == hint_lower:
            # Friendly name is only a lookup hint; return internal id only.
            return player_id
    return ""


@router.post("/push-url")
async def ma_push_url(request: Request) -> JSONResponse:
    """Handle Music Assistant push-url callback and trigger playback handoff."""
    inbound_request_id = (request.headers.get("x-request-id") or "").strip()
    request_id = inbound_request_id or uuid4().hex

    try:
        body = await request.json()
    except Exception:
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": "invalid_json",
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": "invalid_json"}, status_code=400)

    stream_url = str(body.get("streamUrl") or body.get("stream_url") or "").strip()
    probe_state = registry.get_optional("alexa_probe_state") or {}
    logger.info(
        json.dumps(
            {
                "event": "ma_push_url_received",
                "request_id": request_id,
                "inbound_request_id": inbound_request_id,
                "has_stream_url": bool(stream_url),
                "stream_url": stream_url,
                "last_alexa_probe": {
                    "probe_id": probe_state.get("probe_id", ""),
                    "probe_time": probe_state.get("probe_time", ""),
                },
                "app_version": APP_VERSION,
                "build_id": APP_BUILD_ID,
                "query_resolution_rev": APP_QUERY_RESOLUTION_REV,
            }
        )
    )

    if not stream_url:
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": "missing_stream_url",
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": "missing_stream_url"}, status_code=400)

    flow = _extract_flow_parts(stream_url)
    player_hint = str(
        body.get("player_id")
        or body.get("playerId")
        or body.get("player")
        or flow.get("player_hint", "")
    ).strip()

    config_service = registry.get_optional("config_service")
    ma_client = registry.get_optional("ma_client")
    if not config_service or not ma_client:
        logger.error(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": "service_unavailable",
                    "has_config_service": bool(config_service),
                    "has_ma_client": bool(ma_client),
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": "service_unavailable"}, status_code=503)

    public_playback_url = ""

    try:
        players = await ma_client.get_players()
        resolved_player_id = _resolve_player_id(player_hint, players)
        matched_player = next(
            (
                player
                for player in players
                if str(player.get("player_id") or player.get("id") or "").strip() == resolved_player_id
            ),
            None,
        )
        logger.info(
            json.dumps(
                {
                    "event": "ma_push_url_player_resolved",
                    "request_id": request_id,
                    "player_hint": player_hint,
                    "player_id": resolved_player_id,
                    "matched_player": matched_player,
                }
            ,
                default=str,
            )
        )
    except Exception as exc:
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": "player_resolution_failed",
                    "details": str(exc),
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": "player_resolution_failed"}, status_code=502)

    if not resolved_player_id:
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": "player_not_found",
                    "player_hint": player_hint,
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": "player_not_found"}, status_code=404)

    home_id = str(getattr(config_service.settings, "home_id", "") or "")
    preferred_queue_id = str(flow.get("session_id") or "")
    is_edge_mode = bool(getattr(config_service.settings, "is_edge_mode", False))
    alexa_request = _is_alexa_request(body, matched_player)

    final_playback_url = ""
    worker_handoff_details: dict[str, Any] = {}
    flow_title = str(body.get("title") or body.get("name") or flow.get("item_id", ""))

    if alexa_request:
        if not is_edge_mode:
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_push_url_failure",
                        "request_id": request_id,
                        "reason": "worker_handoff_required_for_alexa",
                        "player_id": resolved_player_id,
                    }
                )
            )
            return JSONResponse(
                content={"status": "error", "reason": "worker_handoff_required_for_alexa"},
                status_code=502,
            )

        coalesce_key = f"{home_id}:{resolved_player_id}"
        coalesce_lock = _get_push_url_player_lock(coalesce_key)
        async with coalesce_lock:
            cache_entry = _PUSH_URL_SESSION_CACHE.get(coalesce_key) or {}
            age = monotonic() - float(cache_entry.get("updated_at", 0.0) or 0.0)
            if (
                cache_entry.get("status") == "succeeded"
                and age <= _PUSH_URL_COALESCE_WINDOW_SEC
            ):
                logger.info(
                    json.dumps(
                        {
                            "event": "ma_push_url_duplicate_coalesced",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id,
                            "coalesce_key": coalesce_key,
                            "age_seconds": round(age, 3),
                        }
                    )
                )
                logger.info(
                    json.dumps(
                        {
                            "event": "ma_push_url_existing_session_reused",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id,
                            "playback_session_id": cache_entry.get("playback_session_id", ""),
                            "stream_token_id": cache_entry.get("stream_token_id", ""),
                        }
                    )
                )

                reused_snapshot = await _readback_player_state(
                    ma_client=ma_client,
                    player_id=resolved_player_id,
                    preferred_queue_id=preferred_queue_id,
                    request_id=request_id,
                    home_id=home_id,
                    reused_session=True,
                )
                result = {
                    **(cache_entry.get("result") or {}),
                    "reused_session": True,
                    "player_snapshot": reused_snapshot,
                }
                logger.info(
                    json.dumps(
                        {
                            "event": "ma_push_url_session_start_accepted",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id,
                            "reused_session": True,
                            "status_code": 202,
                        }
                    )
                )
                return JSONResponse(
                    content={
                        "status": "accepted",
                        "request_id": request_id,
                        "player_id": resolved_player_id,
                        "result": result,
                    },
                    status_code=202,
                )

            _PUSH_URL_SESSION_CACHE[coalesce_key] = {
                "status": "running",
                "updated_at": monotonic(),
                "request_id": request_id,
            }

            try:
                worker_handoff_details = await _request_worker_handoff(
                    request_id=request_id,
                    settings=config_service.settings,
                    flow=flow,
                    player_id=resolved_player_id,
                    title=flow_title,
                )
            except Exception as exc:
                _PUSH_URL_SESSION_CACHE[coalesce_key] = {
                    "status": "failed",
                    "updated_at": monotonic(),
                    "request_id": request_id,
                    "error": str(exc),
                }
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_push_url_failure",
                            "request_id": request_id,
                            "reason": "worker_handoff_failed",
                            "details": str(exc),
                        }
                    )
                )
                return JSONResponse(content={"status": "error", "reason": "worker_handoff_failed"}, status_code=502)

            final_playback_url = str(worker_handoff_details.get("stream_url") or "").strip()
            logger.info(
                json.dumps(
                    {
                        "event": "ma_push_url_legacy_fallback_suppressed",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": resolved_player_id,
                        "suppressed_commands": [
                            "player_queues/play_media",
                            "players/play_media",
                            "public_flow_fallback",
                        ],
                        "worker_stream_url": final_playback_url,
                    }
                )
            )

            result = {
                "mode": "worker_handoff_only",
                "player_id": resolved_player_id,
                "queue_id": preferred_queue_id,
                "playback_url": final_playback_url,
                "playback_session_id": str(worker_handoff_details.get("playback_session_id") or ""),
                "stream_token_id": str(worker_handoff_details.get("stream_token_id") or ""),
                "reused_session": False,
            }

            logger.info(
                json.dumps(
                    {
                        "event": "alexa_play_directive_sent",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": resolved_player_id,
                        "playback_session_id": result["playback_session_id"],
                        "stream_token_id": result["stream_token_id"],
                        "playback_url": final_playback_url,
                    }
                )
            )

            ok, message, details = await ma_client.handoff_playback_url(
                player_id=resolved_player_id,
                playback_url=final_playback_url,
                preferred_queue_id=preferred_queue_id,
                request_id=request_id,
                home_id=home_id,
                require_direct_url=True,
            )

            logger.info(
                json.dumps(
                    {
                        "event": "alexa_play_directive_result",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": resolved_player_id,
                        "playback_session_id": result["playback_session_id"],
                        "ok": ok,
                        "message": message,
                        "details": details,
                    },
                    default=str,
                )
            )

            if not ok:
                _PUSH_URL_SESSION_CACHE[coalesce_key] = {
                    "status": "failed",
                    "updated_at": monotonic(),
                    "request_id": request_id,
                    "error": message,
                }
                logger.warning(
                    json.dumps(
                        {
                            "event": "ma_push_url_failure",
                            "request_id": request_id,
                            "reason": "device_start_failed",
                            "details": message,
                            "playback_session_id": result["playback_session_id"],
                        }
                    )
                )
                return JSONResponse(content={"status": "error", "reason": "device_start_failed"}, status_code=502)

            stream_started = False
            stream_start_status: dict[str, Any] = {}
            try:
                stream_started, stream_start_status = await _wait_for_worker_stream_fetch_start(
                    request_id=request_id,
                    settings=config_service.settings,
                    playback_session_id=result["playback_session_id"],
                    wait_seconds=5.0,
                    poll_interval_seconds=1.0,
                )
            except Exception as exc:
                stream_started = False
                stream_start_status = {"error": str(exc)}

            if not stream_started:
                _PUSH_URL_SESSION_CACHE[coalesce_key] = {
                    "status": "failed",
                    "updated_at": monotonic(),
                    "request_id": request_id,
                    "error": "device_start_failed",
                }
                logger.warning(
                    json.dumps(
                        {
                            "event": "device_start_failed",
                            "request_id": request_id,
                            "home_id": home_id,
                            "player_id": resolved_player_id,
                            "playback_session_id": result["playback_session_id"],
                            "stream_start_status": stream_start_status,
                        },
                        default=str,
                    )
                )
                return JSONResponse(content={"status": "error", "reason": "device_start_failed"}, status_code=502)

            result["stream_start_status"] = stream_start_status

            logger.info(
                json.dumps(
                    {
                        "event": "ma_push_url_session_start_accepted",
                        "request_id": request_id,
                        "home_id": home_id,
                        "player_id": resolved_player_id,
                        "reused_session": False,
                        "status_code": 200,
                        "device_start_verified": True,
                    }
                )
            )

            snapshot = await _readback_player_state(
                ma_client=ma_client,
                player_id=resolved_player_id,
                preferred_queue_id=preferred_queue_id,
                request_id=request_id,
                home_id=home_id,
                reused_session=False,
            )
            result["player_snapshot"] = snapshot

            _PUSH_URL_SESSION_CACHE[coalesce_key] = {
                "status": "succeeded",
                "updated_at": monotonic(),
                "request_id": request_id,
                "playback_session_id": result["playback_session_id"],
                "stream_token_id": result["stream_token_id"],
                "result": result,
            }

            return JSONResponse(
                content={
                    "status": "ok",
                    "request_id": request_id,
                    "player_id": resolved_player_id,
                    "public_playback_url": final_playback_url,
                    "result": result,
                },
                status_code=200,
            )

    try:
        public_playback_url = _build_public_playback_url(stream_url, config_service.settings)
        logger.info(
            json.dumps(
                {
                    "event": "ma_push_url_public_url_built",
                    "request_id": request_id,
                    "public_playback_url": public_playback_url,
                }
            )
        )
    except Exception as exc:
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": "public_url_build_failed",
                    "details": str(exc),
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": "public_url_build_failed"}, status_code=422)

    final_playback_url = public_playback_url

    if is_edge_mode:
        try:
            worker_handoff_details = await _request_worker_handoff(
                request_id=request_id,
                settings=config_service.settings,
                flow=flow,
                player_id=resolved_player_id,
                title=flow_title,
            )
            final_playback_url = str(worker_handoff_details.get("stream_url") or "").strip() or final_playback_url
        except Exception as exc:
            logger.warning(
                json.dumps(
                    {
                        "event": "ma_push_url_failure",
                        "request_id": request_id,
                        "reason": "worker_handoff_failed",
                        "details": str(exc),
                    }
                )
            )
            return JSONResponse(content={"status": "error", "reason": "worker_handoff_failed"}, status_code=502)

    logger.info(
        json.dumps(
            {
                "event": "ma_push_url_alexa_playback_request_sent",
                "request_id": request_id,
                "player_id": resolved_player_id,
                "public_playback_url": public_playback_url,
                "final_playback_url": final_playback_url,
                "preferred_queue_id": preferred_queue_id,
            }
        )
    )
    ok, message, details = await ma_client.handoff_playback_url(
        player_id=resolved_player_id,
        playback_url=final_playback_url,
        preferred_queue_id=preferred_queue_id,
        request_id=request_id,
        home_id=home_id,
        require_direct_url=is_edge_mode,
    )

    if (
        not ok
        and message == "direct-url-play-failed"
        and final_playback_url != public_playback_url
    ):
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_retry_with_public_url",
                    "request_id": request_id,
                    "player_id": resolved_player_id,
                    "failed_playback_url": final_playback_url,
                    "retry_playback_url": public_playback_url,
                }
            )
        )
        retry_ok, retry_message, retry_details = await ma_client.handoff_playback_url(
            player_id=resolved_player_id,
            playback_url=public_playback_url,
            preferred_queue_id=preferred_queue_id,
            request_id=request_id,
            home_id=home_id,
            require_direct_url=is_edge_mode,
        )
        logger.info(
            json.dumps(
                {
                    "event": "ma_push_url_retry_with_public_url_result",
                    "request_id": request_id,
                    "ok": retry_ok,
                    "message": retry_message,
                    "details": retry_details,
                }
            )
        )
        if retry_ok:
            ok, message, details = retry_ok, retry_message, retry_details

    logger.info(
        json.dumps(
            {
                "event": "ma_push_url_alexa_playback_session_start_result",
                "request_id": request_id,
                "ok": ok,
                "message": message,
                "details": details,
                "worker_handoff": worker_handoff_details,
            }
        )
    )
    logger.info(
        json.dumps(
            {
                "event": "ma_push_url_alexa_playback_request_result",
                "request_id": request_id,
                "ok": ok,
                "message": message,
                "details": details,
                "worker_handoff": worker_handoff_details,
            }
        )
    )

    if not ok:
        logger.warning(
            json.dumps(
                {
                    "event": "ma_push_url_failure",
                    "request_id": request_id,
                    "reason": message,
                    "player_id": resolved_player_id,
                }
            )
        )
        return JSONResponse(content={"status": "error", "reason": message}, status_code=502)

    return JSONResponse(
        content={
            "status": "ok",
            "request_id": request_id,
            "player_id": resolved_player_id,
            "public_playback_url": public_playback_url,
            "result": details,
        },
        status_code=200,
    )
