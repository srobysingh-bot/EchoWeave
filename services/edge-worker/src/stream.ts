import { getOriginBaseUrl, getRecordedStreamToken } from "./db";
import { signEdgeRequest, verifySignedStreamToken } from "./security";
import { Env } from "./types";

function copyStreamHeaders(upstream: Response): Headers {
  const headers = new Headers();
  const passthrough = [
    "content-type",
    "content-length",
    "accept-ranges",
    "content-range",
    "cache-control",
    "etag",
  ];
  for (const key of passthrough) {
    const value = upstream.headers.get(key);
    if (value) headers.set(key, value);
  }
  return headers;
}

export async function handleStreamRequest(request: Request, env: Env, token: string): Promise<Response> {
  return handleStreamRequestWithContext(request, env, token, request.headers.get("x-request-id") ?? crypto.randomUUID());
}

export async function handleStreamRequestWithContext(
  request: Request,
  env: Env,
  token: string,
  requestId: string,
): Promise<Response> {
  const startedAt = Date.now();
  const tokenSignature = token.split(".")[1] ?? "";
  const claims = await verifySignedStreamToken(token, env.STREAM_TOKEN_SIGNING_SECRET);
  if (!claims) {
    console.warn(JSON.stringify({ event: "stream_proxy_failed", request_id: requestId, reason: "invalid_or_expired_token" }));
    return new Response("invalid or expired stream token", { status: 401 });
  }

  console.info(JSON.stringify({
    event: "stream_proxy_token_verified",
    request_id: requestId,
    token_id: claims.token_id,
    tenant_id: claims.tenant_id,
    home_id: claims.home_id,
    playback_session_id: claims.playback_session_id,
    queue_id: claims.queue_id,
    queue_item_id: claims.queue_item_id,
    origin_stream_path: claims.origin_stream_path,
  }));

  const tokenRecord = await getRecordedStreamToken(env.ECHOWEAVE_DB, {
    id: claims.token_id,
    tenant_id: claims.tenant_id,
    home_id: claims.home_id,
    playback_session_id: claims.playback_session_id,
    token_signature: tokenSignature,
  });
  if (!tokenRecord) {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "unknown_stream_token",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      playback_session_id: claims.playback_session_id,
    }));
    return new Response("unknown stream token", { status: 401 });
  }

  console.info(JSON.stringify({
    event: "stream_proxy_token_record_found",
    request_id: requestId,
    token_id: claims.token_id,
    expires_at: tokenRecord.expires_at,
  }));

  const recordExpiry = Date.parse(tokenRecord.expires_at);
  if (Number.isFinite(recordExpiry) && recordExpiry < Date.now()) {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "expired_stream_token_record",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      playback_session_id: claims.playback_session_id,
    }));
    return new Response("expired stream token", { status: 401 });
  }

  const doId = env.HOME_SESSION.idFromName(`${claims.tenant_id}:${claims.home_id}`);
  const sessionStub = env.HOME_SESSION.get(doId);
  console.info(JSON.stringify({
    event: "stream_proxy_started",
    request_id: requestId,
    tenant_id: claims.tenant_id,
    home_id: claims.home_id,
    token_id: claims.token_id,
    playback_session_id: claims.playback_session_id,
    queue_id: claims.queue_id,
    queue_item_id: claims.queue_item_id,
    origin_stream_path: claims.origin_stream_path,
    has_range: !!request.headers.get("range"),
  }));

  // --- Resolve stream via connector DO ---
  console.info(JSON.stringify({
    event: "stream_proxy_resolve_started",
    request_id: requestId,
    token_id: claims.token_id,
    queue_id: claims.queue_id,
    queue_item_id: claims.queue_item_id,
  }));

  const resolveStart = Date.now();
  const resolveResp = await sessionStub.fetch("https://home-session/command", {
    method: "POST",
    headers: { "content-type": "application/json", "x-request-id": requestId },
    body: JSON.stringify({
      command_type: "resolve_stream",
      payload: {
        request_id: requestId,
        token_id: claims.token_id,
        playback_session_id: claims.playback_session_id,
        queue_id: claims.queue_id,
        queue_item_id: claims.queue_item_id,
      },
      timeout_ms: 8000,
    }),
  });

  if (!resolveResp.ok) {
    const errorBody = await resolveResp.text();
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "connector_stream_resolve_failed",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      queue_id: claims.queue_id,
      queue_item_id: claims.queue_item_id,
      playback_session_id: claims.playback_session_id,
      do_status: resolveResp.status,
      do_error_body: errorBody,
    }));
    return new Response("stream resolve failed", { status: 502 });
  }

  const resolvePayload = (await resolveResp.json()) as { source_url?: string; origin_stream_path?: string };
  const resolveMs = Date.now() - resolveStart;

  console.info(JSON.stringify({
    event: "stream_proxy_resolve_done",
    request_id: requestId,
    token_id: claims.token_id,
    has_source_url: !!resolvePayload.source_url,
    has_origin_stream_path: !!resolvePayload.origin_stream_path,
    resolve_ms: resolveMs,
  }));

  // --- Determine origin_stream_path (canonical upstream path) ---
  const originStreamPath = (resolvePayload.origin_stream_path && resolvePayload.origin_stream_path.startsWith("/"))
    ? resolvePayload.origin_stream_path
    : claims.origin_stream_path.startsWith("/")
      ? claims.origin_stream_path
      : `/${claims.origin_stream_path}`;

  if (!originStreamPath || originStreamPath === "/") {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "missing_origin_stream_path",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      queue_id: claims.queue_id,
      queue_item_id: claims.queue_item_id,
      playback_session_id: claims.playback_session_id,
      resolve_origin_stream_path: resolvePayload.origin_stream_path ?? "",
      claims_origin_stream_path: claims.origin_stream_path ?? "",
    }));
    return new Response("missing origin stream path", { status: 502 });
  }

  // --- Look up reachable add-on origin base URL ---
  const originBaseUrl = await getOriginBaseUrl(env.ECHOWEAVE_DB, claims.home_id, claims.tenant_id);
  if (!originBaseUrl) {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "missing_origin_base_url",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      queue_id: claims.queue_id,
      queue_item_id: claims.queue_item_id,
      playback_session_id: claims.playback_session_id,
    }));
    return new Response("missing origin base url for home", { status: 502 });
  }

  // --- Build upstream URL from origin base + origin_stream_path ---
  let upstreamUrl: URL;
  try {
    upstreamUrl = new URL(originStreamPath, originBaseUrl);
  } catch {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "invalid_upstream_url",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      queue_id: claims.queue_id,
      queue_item_id: claims.queue_item_id,
      playback_session_id: claims.playback_session_id,
      origin_base_url: originBaseUrl,
      origin_stream_path: originStreamPath,
    }));
    return new Response("invalid upstream url", { status: 502 });
  }

  // --- Sign request for add-on edge auth ---
  const edgeSig = await signEdgeRequest(env.EDGE_ORIGIN_SHARED_SECRET, "GET", upstreamUrl.pathname);

  // --- Build upstream request headers ---
  const upstreamHeaders: Record<string, string> = {
    "x-edge-timestamp": edgeSig.timestamp,
    "x-edge-signature": edgeSig.signature,
    "x-edge-token-id": claims.token_id,
    "x-edge-playback-session-id": claims.playback_session_id,
    "x-request-id": requestId,
  };
  const rangeHeader = request.headers.get("range");
  if (rangeHeader) upstreamHeaders["range"] = rangeHeader;
  const ifRangeHeader = request.headers.get("if-range");
  if (ifRangeHeader) upstreamHeaders["if-range"] = ifRangeHeader;

  console.info(JSON.stringify({
    event: "stream_proxy_upstream_target",
    request_id: requestId,
    token_id: claims.token_id,
    tenant_id: claims.tenant_id,
    home_id: claims.home_id,
    queue_id: claims.queue_id,
    queue_item_id: claims.queue_item_id,
    upstream_host: upstreamUrl.hostname,
    upstream_path: upstreamUrl.pathname,
    upstream_origin: upstreamUrl.origin,
    source_url_for_diag: resolvePayload.source_url ?? "(none)",
    target_source: "origin_stream_path",
    has_edge_signature: true,
    has_range: !!rangeHeader,
    has_if_range: !!ifRangeHeader,
  }));

  // --- Fetch from add-on edge stream route ---
  const upstreamStart = Date.now();
  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl.toString(), {
      method: "GET",
      headers: upstreamHeaders,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown";
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "edge_upstream_fetch_error",
      token_id: claims.token_id,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      queue_id: claims.queue_id,
      queue_item_id: claims.queue_item_id,
      playback_session_id: claims.playback_session_id,
      upstream_url: upstreamUrl.toString(),
      error: message,
    }));
    return new Response("edge upstream fetch error", { status: 502 });
  }
  const firstByteMs = Date.now() - upstreamStart;

  console.info(JSON.stringify({
    event: "stream_proxy_upstream_request",
    request_id: requestId,
    token_id: claims.token_id,
    upstream_status: upstream.status,
    first_byte_ms: firstByteMs,
  }));

  if (!upstream.ok && upstream.status !== 206) {
    console.warn(
      JSON.stringify({
        event: "stream_proxy_failed",
        request_id: requestId,
        reason: "origin_stream_error",
        token_id: claims.token_id,
        tenant_id: claims.tenant_id,
        home_id: claims.home_id,
        queue_id: claims.queue_id,
        queue_item_id: claims.queue_item_id,
        playback_session_id: claims.playback_session_id,
        origin_status: upstream.status,
        upstream_url_host: upstreamUrl.hostname,
        upstream_url_path: upstreamUrl.pathname,
        resolve_ms: resolveMs,
        first_byte_ms: firstByteMs,
      }),
    );
    return new Response(`origin stream error (${upstream.status})`, { status: 502 });
  }

  console.info(
    JSON.stringify({
      event: "stream_proxy_response",
      request_id: requestId,
      tenant_id: claims.tenant_id,
      home_id: claims.home_id,
      token_id: claims.token_id,
      playback_session_id: claims.playback_session_id,
      queue_id: claims.queue_id,
      queue_item_id: claims.queue_item_id,
      status: upstream.status,
      resolve_ms: resolveMs,
      first_byte_ms: firstByteMs,
      total_ms: Date.now() - startedAt,
      upstream_host: upstreamUrl.hostname,
      upstream_path: upstreamUrl.pathname,
      target_source: "origin_stream_path",
      content_type: upstream.headers.get("content-type") ?? "",
      accept_ranges: upstream.headers.get("accept-ranges") ?? "",
      content_length: upstream.headers.get("content-length") ?? "",
      content_range: upstream.headers.get("content-range") ?? "",
      transfer_encoding: upstream.headers.get("transfer-encoding") ?? "",
    }),
  );

  return new Response(upstream.body, {
    status: upstream.status,
    headers: copyStreamHeaders(upstream),
  });
}
