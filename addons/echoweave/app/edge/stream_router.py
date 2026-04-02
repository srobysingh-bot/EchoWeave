from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.service_registry import registry
from app.edge.auth import extract_edge_auth_headers, verify_edge_request

logger = logging.getLogger(__name__)

# Stream URL cache: {queue_id}:{queue_item_id} -> (source_url, timestamp)
_stream_url_cache: dict[str, tuple[str, float]] = {}
_STREAM_CACHE_TTL = 300  # 5 minutes

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

router = APIRouter(prefix="/edge", tags=["edge"])


@router.get("/stream/{queue_id}/{queue_item_id}")
async def edge_stream(queue_id: str, queue_item_id: str, request: Request):
    overall_start = time.perf_counter()
    
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

    if not verify_edge_request(
        shared_secret=shared_secret,
        method="GET",
        path=path,
        timestamp=ts,
        signature=sig,
    ):
        raise HTTPException(status_code=401, detail="Invalid edge signature")

    # Try to get source URL from cache first
    origin_source_url = get_cached_stream_url(queue_id, queue_item_id)
    resolve_start = time.perf_counter()
    resolve_elapsed = 0.0
    
    if not origin_source_url:
        # Fallback: resolve from MA (only if not cached)
        logger.warning(f"Stream endpoint: cache miss for {queue_id}/{queue_item_id}, resolving from MA")
        try:
            stream_ctx = await ma_client.build_stream_context(queue_id=queue_id, queue_item_id=queue_item_id)
            origin_source_url = stream_ctx.get("source_url")
            resolve_elapsed = time.perf_counter() - resolve_start
            
            if origin_source_url:
                # Cache for future requests
                cache_stream_url(queue_id, queue_item_id, origin_source_url)
                logger.info(f"Stream resolution took {resolve_elapsed*1000:.1f}ms for item {queue_item_id}")
        except Exception as e:
            logger.error(f"Stream resolution failed: {e}")
            raise HTTPException(status_code=502, detail="Stream resolution failed")
    else:
        logger.info(f"Stream endpoint: using cached source_url for {queue_id}/{queue_item_id} (cache hit)")
    
    if not origin_source_url:
        raise HTTPException(status_code=404, detail="Stream source unavailable")

    headers = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    timeout = httpx.Timeout(30.0, connect=10.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    
    fetch_start = time.perf_counter()
    upstream_request = client.build_request("GET", origin_source_url, headers=headers)
    upstream = await client.send(upstream_request, stream=True)
    first_byte_elapsed = (time.perf_counter() - fetch_start) * 1000

    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        logger.error(f"Stream fetch failed: status={upstream.status_code} from {origin_source_url}, first-byte-ms={first_byte_elapsed:.1f}")
        raise HTTPException(status_code=502, detail=f"Origin stream failed: {upstream.status_code}")

    logger.info(f"Stream response: content-type={upstream.headers.get('content-type', 'unknown')}, accept-ranges={upstream.headers.get('accept-ranges', 'unknown')}, content-length={upstream.headers.get('content-length', 'unknown')}, status={upstream.status_code}, first-byte-ms={first_byte_elapsed:.1f}")

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
    logger.info(f"Stream setup: total={overall_elapsed:.1f}ms, auth+lookup={resolve_elapsed*1000:.1f}ms, first-byte={first_byte_elapsed:.1f}ms, item={queue_item_id}")

    return StreamingResponse(
        stream_iter(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=response_headers["Content-Type"],
    )
