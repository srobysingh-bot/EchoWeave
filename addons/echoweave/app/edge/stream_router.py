from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.service_registry import registry
from app.edge.auth import extract_edge_auth_headers, verify_edge_request

logger = logging.getLogger(__name__)

# Stream URL cache: {queue_id}:{queue_item_id} -> (source_url, timestamp)
_stream_url_cache: dict[str, tuple[str, float]] = {}
_STREAM_CACHE_TTL = 300  # 5 minutes

# URI mapping cache: {queue_id}:{queue_item_id} -> provider URI
# Stores the original MA URI (e.g. apple_music://track/123) for synthetic items
# so that stream resolution can use music/item_by_uri as a fallback.
_uri_mapping_cache: dict[str, str] = {}

_ALEXA_SUPPORTED_CONTENT_TYPES = (
    "audio/mpeg",
    "audio/mp3",
    "audio/aac",
    "audio/mp4",
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/x-mpegurl",
)

_TRANSCODE_CHUNK_SIZE = 64 * 1024


def _is_alexa_supported_content_type(content_type: str) -> bool:
    normalized = (content_type or "").lower()
    return any(value in normalized for value in _ALEXA_SUPPORTED_CONTENT_TYPES)


def _replace_path_extension(url: str, target_ext: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or ""
    if "." not in path:
        return url
    base, _dot, _ext = path.rpartition(".")
    if not base:
        return url
    new_path = f"{base}.{target_ext}"
    return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))


def _append_or_replace_query(url: str, key: str, value: str) -> str:
    parsed = urlsplit(url)
    query_pairs = [(k, v) for (k, v) in parse_qsl(parsed.query, keep_blank_values=True) if k != key]
    query_pairs.append((key, value))
    new_query = urlencode(query_pairs)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def _with_query_params(url: str, params: dict[str, str]) -> str:
    updated = url
    for key, value in params.items():
        updated = _append_or_replace_query(updated, key, value)
    return updated


def _build_alexa_source_url_candidates(source_url: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    def _push(url: str, mode: str) -> None:
        if not url:
            return
        if any(existing_url == url for existing_url, _ in candidates):
            return
        candidates.append((url, mode))

    # Prefer explicit codec selection first (MP3 then AAC), with Alexa-safe HTTP profile
    # and ICY metadata disabled to avoid unsupported response behavior.
    mp3_base = _with_query_params(
        source_url,
        {
            "codec": "mp3",
            "format": "mp3",
            "audio_format": "mp3",
            "output_codec": "mp3",
            "http_profile": "alexa",
            "profile": "alexa",
            "icy": "0",
            "metadata": "0",
            "icymeta": "0",
        },
    )
    aac_base = _with_query_params(
        source_url,
        {
            "codec": "aac",
            "format": "aac",
            "audio_format": "aac",
            "output_codec": "aac",
            "http_profile": "alexa",
            "profile": "alexa",
            "icy": "0",
            "metadata": "0",
            "icymeta": "0",
        },
    )

    _push(mp3_base, "query_codec_mp3_profile")
    _push(aac_base, "query_codec_aac_profile")
    _push(_replace_path_extension(mp3_base, "mp3"), "path_ext_mp3")
    _push(_replace_path_extension(aac_base, "aac"), "path_ext_aac")
    _push(_append_or_replace_query(source_url, "codec", "mp3"), "query_codec_mp3")
    _push(_append_or_replace_query(source_url, "codec", "aac"), "query_codec_aac")

    # Keep original as final fallback for ffmpeg transcode path.
    _push(source_url, "origin")
    return candidates

def get_cached_stream_url(queue_id: str, queue_item_id: str) -> Optional[str]:
    """Retrieve cached stream URL if available and not expired."""
    cache_key = f"{queue_id}:{queue_item_id}"
    if cache_key in _stream_url_cache:
        source_url, timestamp = _stream_url_cache[cache_key]
        age = time.time() - timestamp
        if age < _STREAM_CACHE_TTL:
            logger.debug(f"Stream cache hit for {queue_id}/{queue_item_id} (age={age:.1f}s)")
            return source_url
        else:
            logger.debug(f"Stream cache expired for {queue_id}/{queue_item_id} (age={age:.1f}s > {_STREAM_CACHE_TTL}s)")
            del _stream_url_cache[cache_key]
    return None

def cache_stream_url(queue_id: str, queue_item_id: str, source_url: str) -> None:
    """Cache the resolved stream URL."""
    cache_key = f"{queue_id}:{queue_item_id}"
    _stream_url_cache[cache_key] = (source_url, time.time())
    logger.debug(f"Stream URL cached for {queue_id}/{queue_item_id}")


def cache_uri_mapping(queue_id: str, queue_item_id: str, uri: str) -> None:
    """Store the original provider URI for a synthetic queue item."""
    cache_key = f"{queue_id}:{queue_item_id}"
    _uri_mapping_cache[cache_key] = uri
    logger.debug(f"URI mapping cached for {queue_id}/{queue_item_id}")


def get_cached_uri_mapping(queue_id: str, queue_item_id: str) -> Optional[str]:
    """Retrieve the original provider URI for a synthetic queue item."""
    return _uri_mapping_cache.get(f"{queue_id}:{queue_item_id}")

router = APIRouter(prefix="/edge", tags=["edge"])


@router.get("/stream/{queue_id}/{queue_item_id}")
async def edge_stream(queue_id: str, queue_item_id: str, request: Request):
    overall_start = time.perf_counter()
    request_id = request.headers.get("x-request-id", "")
    
    config_svc = registry.get_optional("config_service")
    ma_client = registry.get_optional("ma_client")
    if not config_svc or not ma_client:
        raise HTTPException(status_code=503, detail="Service unavailable")

    settings = config_svc.settings
    if not settings.is_edge_mode:
        raise HTTPException(status_code=404, detail="edge-stream-not-enabled")

    shared_secret = settings.edge_shared_secret
    path = request.url.path
    ts, sig = extract_edge_auth_headers(request.headers)

    if not ts or not sig:
        auth_fail_reason = "missing_signature" if not sig else "missing_timestamp"
        logger.warning(json.dumps({
            "event": "edge_stream_auth_failed",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "reason": auth_fail_reason,
            "has_timestamp": bool(ts),
            "has_signature": bool(sig),
            "has_range": bool(request.headers.get("range")),
        }))
        raise HTTPException(status_code=401, detail="Invalid edge signature")

    if not verify_edge_request(
        shared_secret=shared_secret,
        method="GET",
        path=path,
        timestamp=ts,
        signature=sig,
    ):
        # Determine specific failure reason for operator diagnostics
        auth_fail_reason = "invalid_signature"
        try:
            ts_value = int(ts)
            import time as _time
            if abs(_time.time() - ts_value) > 300:
                auth_fail_reason = "stale_timestamp"
        except ValueError:
            auth_fail_reason = "invalid_timestamp_format"

        logger.warning(json.dumps({
            "event": "edge_stream_auth_failed",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "reason": auth_fail_reason,
            "has_range": bool(request.headers.get("range")),
        }))
        raise HTTPException(status_code=401, detail="Invalid edge signature")

    logger.info(json.dumps({
        "event": "edge_stream_request_start",
        "request_id": request_id,
        "queue_id": queue_id,
        "queue_item_id": queue_item_id,
        "has_range": bool(request.headers.get("range")),
    }))

    client_profile = str(request.headers.get("x-edge-client-profile") or "").strip().lower()
    is_alexa_profile = client_profile == "alexa"

    # Try to get source URL from cache first
    origin_source_url = get_cached_stream_url(queue_id, queue_item_id)
    resolve_start = time.perf_counter()
    resolve_elapsed = 0.0
    
    if not origin_source_url:
        # Fallback: resolve from MA (only if not cached)
        logger.warning(json.dumps({
            "event": "edge_stream_lookup_start",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "cache_hit": False,
        }))
        try:
            stream_ctx = await ma_client.build_stream_context(queue_id=queue_id, queue_item_id=queue_item_id)
            origin_source_url = stream_ctx.get("source_url")
            resolve_elapsed = time.perf_counter() - resolve_start
            
            if origin_source_url:
                # Cache for future requests
                cache_stream_url(queue_id, queue_item_id, origin_source_url)
                logger.info(json.dumps({
                    "event": "edge_stream_lookup_done",
                    "request_id": request_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "cache_hit": False,
                    "lookup_ms": round(resolve_elapsed * 1000, 1),
                }))
        except Exception as e:
            logger.error(json.dumps({
                "event": "edge_stream_lookup_failed",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "error": str(e),
            }))

    if not origin_source_url:
        # Final fallback: check URI mapping for synthetic items and
        # try to resolve via get_stream_url which now has URI-aware
        # resolution logic (music/item_by_uri + enqueue-add).
        cached_uri = get_cached_uri_mapping(queue_id, queue_item_id)
        if cached_uri:
            logger.info(json.dumps({
                "event": "edge_stream_uri_mapping_fallback",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "cached_uri": cached_uri,
            }))
            try:
                origin_source_url = await ma_client.get_stream_url(queue_id, queue_item_id)
                resolve_elapsed = time.perf_counter() - resolve_start
                # Only cache real HTTP URLs — never cache provider URIs.
                if origin_source_url and origin_source_url.startswith(("http://", "https://")):
                    cache_stream_url(queue_id, queue_item_id, origin_source_url)
                    logger.info(json.dumps({
                        "event": "edge_stream_uri_fallback_resolved",
                        "request_id": request_id,
                        "queue_id": queue_id,
                        "queue_item_id": queue_item_id,
                        "lookup_ms": round(resolve_elapsed * 1000, 1),
                    }))
                elif origin_source_url:
                    logger.warning(json.dumps({
                        "event": "edge_stream_uri_fallback_non_http",
                        "request_id": request_id,
                        "queue_id": queue_id,
                        "queue_item_id": queue_item_id,
                        "url": origin_source_url,
                    }))
                    origin_source_url = None  # will be replaced by guard below
            except Exception as e2:
                logger.warning(json.dumps({
                    "event": "edge_stream_uri_fallback_failed",
                    "request_id": request_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "error": str(e2),
                }))
    else:
        logger.info(json.dumps({
            "event": "edge_stream_lookup_done",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "cache_hit": True,
            "lookup_ms": 0.0,
        }))
    
    if not origin_source_url:
        raise HTTPException(status_code=404, detail="Stream source unavailable")

    # Safety guard: if the resolved URL is a provider URI (apple_music://, spotify://, etc.)
    # rather than an HTTP URL, it cannot be fetched. Replace it with MA's HTTP stream proxy.
    if not origin_source_url.startswith(("http://", "https://")):
        ma_base_url = settings.ma_base_url.rstrip("/")
        # Use the real MA player queue ID — the route parameter queue_id may be a logical
        # EchoWeave identifier (e.g. "queue-staging") that MA does not recognise.
        _guard_queue_id = queue_id
        try:
            _real_guard_queue_id = await ma_client._resolve_default_queue_id()
            if _real_guard_queue_id:
                _guard_queue_id = _real_guard_queue_id
        except Exception:
            pass
        fallback_url = f"{ma_base_url}/stream/{_guard_queue_id}/{queue_item_id}"
        logger.warning(json.dumps({
            "event": "edge_stream_non_http_source_replaced",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "original_url": origin_source_url,
            "fallback_url": fallback_url,
            "resolved_ma_queue_id": _guard_queue_id,
        }))
        origin_source_url = fallback_url
        # Clear the bad cached entry so future requests re-resolve correctly.
        cache_key = f"{queue_id}:{queue_item_id}"
        _stream_url_cache.pop(cache_key, None)

    headers = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    timeout = httpx.Timeout(30.0, connect=10.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    selected_source_url = origin_source_url
    selected_mode = "origin"
    upstream: httpx.Response | None = None
    first_byte_elapsed = 0.0

    source_candidates = [(origin_source_url, "origin")]
    transcode_fallback: tuple[str, str, str] | None = None
    if is_alexa_profile:
        source_candidates = _build_alexa_source_url_candidates(origin_source_url)
        logger.info(json.dumps({
            "event": "alexa_stream_format_selected",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "selected_format": "mp3",
            "candidate_count": len(source_candidates),
            "candidate_modes": [mode for _, mode in source_candidates],
        }))

    for candidate_url, candidate_mode in source_candidates:
        if is_alexa_profile and candidate_mode != "origin":
            logger.info(json.dumps({
                "event": "alexa_stream_transcode_started",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "mode": candidate_mode,
                "candidate_url": candidate_url,
            }))
        fetch_start = time.perf_counter()
        try:
            upstream_request = client.build_request("GET", candidate_url, headers=headers)
            candidate_response = await client.send(upstream_request, stream=True)
        except Exception as exc:
            logger.warning(json.dumps({
                "event": "worker_stream_fetch_failed",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "mode": candidate_mode,
                "candidate_url": candidate_url,
                "reason": "upstream_fetch_exception",
                "error": str(exc),
            }))
            continue

        first_byte_elapsed = (time.perf_counter() - fetch_start) * 1000
        content_type = candidate_response.headers.get("content-type", "")
        if candidate_response.status_code not in (200, 206):
            await candidate_response.aclose()
            logger.warning(json.dumps({
                "event": "worker_stream_fetch_failed",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "mode": candidate_mode,
                "candidate_url": candidate_url,
                "reason": "bad_status",
                "upstream_status": candidate_response.status_code,
            }))
            continue

        if is_alexa_profile and not _is_alexa_supported_content_type(content_type):
            if transcode_fallback is None:
                transcode_fallback = (candidate_url, candidate_mode, content_type)
            await candidate_response.aclose()
            logger.warning(json.dumps({
                "event": "worker_stream_fetch_failed",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "mode": candidate_mode,
                "candidate_url": candidate_url,
                "reason": "unsupported_content_type",
                "content_type": content_type,
            }))
            continue

        upstream = candidate_response
        selected_source_url = candidate_url
        selected_mode = candidate_mode
        break

    if upstream is None:
        if is_alexa_profile and transcode_fallback is not None:
            transcode_source_url, transcode_source_mode, transcode_source_content_type = transcode_fallback
            logger.info(json.dumps({
                "event": "alexa_stream_transcode_started",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "mode": "ffmpeg_mp3_fallback",
                "source_mode": transcode_source_mode,
                "source_content_type": transcode_source_content_type,
                "source_url": transcode_source_url,
            }))
            transcode_headers = {}
            if request.headers.get("if-range"):
                transcode_headers["If-Range"] = request.headers["if-range"]

            fetch_start = time.perf_counter()
            transcode_request = client.build_request("GET", transcode_source_url, headers=transcode_headers)
            try:
                upstream = await client.send(transcode_request, stream=True)
            except Exception as exc:
                await client.aclose()
                logger.warning(json.dumps({
                    "event": "worker_stream_fetch_failed",
                    "request_id": request_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "mode": "ffmpeg_mp3_fallback",
                    "reason": "transcode_upstream_fetch_exception",
                    "source_url": transcode_source_url,
                    "error": str(exc),
                }))
                raise HTTPException(status_code=502, detail="No Alexa-compatible stream source available")
            first_byte_elapsed = (time.perf_counter() - fetch_start) * 1000
            if upstream.status_code not in (200, 206):
                await upstream.aclose()
                await client.aclose()
                logger.warning(json.dumps({
                    "event": "worker_stream_fetch_failed",
                    "request_id": request_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "mode": "ffmpeg_mp3_fallback",
                    "reason": "bad_status",
                    "upstream_status": upstream.status_code,
                }))
                raise HTTPException(status_code=502, detail="No Alexa-compatible stream source available")

            try:
                ffmpeg_proc = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-i",
                    "pipe:0",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    "-f",
                    "mp3",
                    "pipe:1",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                await upstream.aclose()
                await client.aclose()
                logger.error(json.dumps({
                    "event": "worker_stream_fetch_failed",
                    "request_id": request_id,
                    "queue_id": queue_id,
                    "queue_item_id": queue_item_id,
                    "mode": "ffmpeg_mp3_fallback",
                    "reason": "ffmpeg_not_available",
                    "error": str(exc),
                }))
                raise HTTPException(status_code=502, detail="ffmpeg unavailable for Alexa transcode")

            selected_source_url = transcode_source_url
            selected_mode = "ffmpeg_mp3_fallback"

            async def _pump_upstream_to_ffmpeg() -> None:
                try:
                    async for chunk in upstream.aiter_bytes(_TRANSCODE_CHUNK_SIZE):
                        if ffmpeg_proc.stdin is None:
                            break
                        ffmpeg_proc.stdin.write(chunk)
                        await ffmpeg_proc.stdin.drain()
                finally:
                    if ffmpeg_proc.stdin is not None:
                        ffmpeg_proc.stdin.close()

            pump_task = asyncio.create_task(_pump_upstream_to_ffmpeg())

            async def stream_iter_transcode():
                try:
                    if ffmpeg_proc.stdout is None:
                        return
                    while True:
                        chunk = await ffmpeg_proc.stdout.read(_TRANSCODE_CHUNK_SIZE)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    await pump_task
                    stderr_text = ""
                    if ffmpeg_proc.stderr is not None:
                        try:
                            stderr_text = (await ffmpeg_proc.stderr.read()).decode("utf-8", errors="replace")[:2000]
                        except Exception:
                            stderr_text = ""
                    return_code = await ffmpeg_proc.wait()
                    if return_code != 0:
                        logger.warning(json.dumps({
                            "event": "worker_stream_fetch_failed",
                            "request_id": request_id,
                            "queue_id": queue_id,
                            "queue_item_id": queue_item_id,
                            "mode": "ffmpeg_mp3_fallback",
                            "reason": "ffmpeg_exit_nonzero",
                            "ffmpeg_exit_code": return_code,
                            "ffmpeg_stderr": stderr_text,
                        }))
                    await upstream.aclose()
                    await client.aclose()

            logger.info(json.dumps({
                "event": "worker_stream_first_byte_sent",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "mode": selected_mode,
                "source_url": selected_source_url,
                "first_byte_ms": round(first_byte_elapsed, 1),
                "upstream_status": upstream.status_code,
            }))

            logger.info(json.dumps({
                "event": "alexa_stream_response_content_type",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "is_alexa_profile": True,
                "source_mode": selected_mode,
                "content_type": "audio/mpeg",
            }))

            overall_elapsed = (time.perf_counter() - overall_start) * 1000
            logger.info(json.dumps({
                "event": "edge_stream_response",
                "request_id": request_id,
                "queue_id": queue_id,
                "queue_item_id": queue_item_id,
                "status": 200,
                "first_byte_ms": round(first_byte_elapsed, 1),
                "lookup_ms": round(resolve_elapsed * 1000, 1),
                "total_ms": round(overall_elapsed, 1),
                "content_type": "audio/mpeg",
                "accept_ranges": "none",
                "content_length": "",
                "content_range": "",
                "transfer_encoding": "chunked",
                "source_mode": selected_mode,
                "selected_source_url": selected_source_url,
            }))

            return StreamingResponse(
                stream_iter_transcode(),
                status_code=200,
                headers={
                    "Content-Type": "audio/mpeg",
                    "Accept-Ranges": "none",
                    "Cache-Control": "no-store",
                },
                media_type="audio/mpeg",
            )

        await client.aclose()
        raise HTTPException(status_code=502, detail="No Alexa-compatible stream source available")

    logger.info(json.dumps({
        "event": "worker_stream_first_byte_sent",
        "request_id": request_id,
        "queue_id": queue_id,
        "queue_item_id": queue_item_id,
        "mode": selected_mode,
        "source_url": selected_source_url,
        "first_byte_ms": round(first_byte_elapsed, 1),
        "upstream_status": upstream.status_code,
    }))

    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        logger.error(json.dumps({
            "event": "edge_stream_response",
            "request_id": request_id,
            "queue_id": queue_id,
            "queue_item_id": queue_item_id,
            "status": 502,
            "origin_status": upstream.status_code,
            "first_byte_ms": round(first_byte_elapsed, 1),
            "content_type": upstream.headers.get("content-type", ""),
            "accept_ranges": upstream.headers.get("accept-ranges", ""),
            "content_length": upstream.headers.get("content-length", ""),
        }))
        raise HTTPException(status_code=502, detail=f"Origin stream failed: {upstream.status_code}")

    logger.info(json.dumps({
        "event": "alexa_stream_response_content_type",
        "request_id": request_id,
        "queue_id": queue_id,
        "queue_item_id": queue_item_id,
        "is_alexa_profile": is_alexa_profile,
        "source_mode": selected_mode,
        "content_type": upstream.headers.get("content-type", ""),
    }))

    async def stream_iter():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        "Content-Type": upstream.headers.get("content-type", "audio/mpeg"),
        "Accept-Ranges": upstream.headers.get("accept-ranges", "bytes"),
    }
    if upstream.headers.get("content-range"):
        response_headers["Content-Range"] = upstream.headers["content-range"]
    if upstream.headers.get("content-length"):
        response_headers["Content-Length"] = upstream.headers["content-length"]

    overall_elapsed = (time.perf_counter() - overall_start) * 1000
    logger.info(json.dumps({
        "event": "edge_stream_response",
        "request_id": request_id,
        "queue_id": queue_id,
        "queue_item_id": queue_item_id,
        "status": upstream.status_code,
        "first_byte_ms": round(first_byte_elapsed, 1),
        "lookup_ms": round(resolve_elapsed * 1000, 1),
        "total_ms": round(overall_elapsed, 1),
        "content_type": upstream.headers.get("content-type", ""),
        "accept_ranges": upstream.headers.get("accept-ranges", ""),
        "content_length": upstream.headers.get("content-length", ""),
        "content_range": upstream.headers.get("content-range", ""),
        "transfer_encoding": upstream.headers.get("transfer-encoding", ""),
        "source_mode": selected_mode,
        "selected_source_url": selected_source_url,
    }))

    return StreamingResponse(
        stream_iter(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=response_headers["Content-Type"],
    )
