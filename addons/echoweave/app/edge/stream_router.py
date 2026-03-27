from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.service_registry import registry
from app.edge.auth import extract_edge_auth_headers, verify_edge_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/edge", tags=["edge"])


@router.get("/stream/{queue_id}/{queue_item_id}")
async def edge_stream(queue_id: str, queue_item_id: str, request: Request):
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

    stream_ctx = await ma_client.build_stream_context(queue_id=queue_id, queue_item_id=queue_item_id)
    source_url = stream_ctx.get("source_url")
    if not source_url:
        raise HTTPException(status_code=404, detail="Stream source unavailable")

    headers = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    timeout = httpx.Timeout(30.0, connect=10.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    upstream_request = client.build_request("GET", source_url, headers=headers)
    upstream = await client.send(upstream_request, stream=True)

    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Origin stream failed: {upstream.status_code}")

    async def stream_iter():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        "Content-Type": upstream.headers.get("content-type", stream_ctx.get("content_type") or "audio/mpeg"),
        "Accept-Ranges": upstream.headers.get("accept-ranges", "bytes"),
    }
    if upstream.headers.get("content-range"):
        response_headers["Content-Range"] = upstream.headers["content-range"]
    if upstream.headers.get("content-length"):
        response_headers["Content-Length"] = upstream.headers["content-length"]

    return StreamingResponse(
        stream_iter(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=response_headers["Content-Type"],
    )
