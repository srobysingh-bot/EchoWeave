"""Music Assistant callback router.

Handles inbound requests from Music Assistant, such as push-url notifications.
"""

from __future__ import annotations

import json
import logging
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
    logger.info(
        json.dumps(
            {
                "event": "ma_worker_handoff_response",
                "request_id": request_id,
                "status": response.status_code,
                "ok": response.is_success,
                "body": body_text,
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
    request_id = uuid4().hex

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
    logger.info(
        json.dumps(
            {
                "event": "ma_push_url_received",
                "request_id": request_id,
                "has_stream_url": bool(stream_url),
                "stream_url": stream_url,
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

    final_playback_url = public_playback_url
    worker_handoff_details: dict[str, Any] = {}
    flow_title = str(body.get("title") or body.get("name") or flow.get("item_id", ""))
    if getattr(config_service.settings, "is_edge_mode", False):
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
            }
        )
    )
    ok, message, details = await ma_client.handoff_playback_url(
        player_id=resolved_player_id,
        playback_url=final_playback_url,
        request_id=request_id,
        home_id=str(getattr(config_service.settings, "home_id", "") or ""),
        require_direct_url=bool(getattr(config_service.settings, "is_edge_mode", False)),
    )

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
