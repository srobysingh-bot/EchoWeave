import { getRecordedStreamToken } from "./db";
import { verifySignedStreamToken } from "./security";
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
      playback_session_id: claims.playback_session_id,
    }));
    return new Response("unknown stream token", { status: 401 });
  }

  const recordExpiry = Date.parse(tokenRecord.expires_at);
  if (Number.isFinite(recordExpiry) && recordExpiry < Date.now()) {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "expired_stream_token_record",
      token_id: claims.token_id,
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
    origin_stream_path: claims.origin_stream_path,
    has_range: !!request.headers.get("range"),
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
      playback_session_id: claims.playback_session_id,
      do_status: resolveResp.status,
      do_error_body: errorBody,
    }));
    return new Response("stream resolve failed", { status: 502 });
  }

  const resolvePayload = (await resolveResp.json()) as { source_url?: string; origin_stream_path?: string };
  const sourceUrl = String(resolvePayload.source_url ?? "");
  if (!sourceUrl) {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "missing_source_url",
      token_id: claims.token_id,
      playback_session_id: claims.playback_session_id,
    }));
    return new Response("missing source url", { status: 502 });
  }

  let originUrl: URL;
  try {
    originUrl = new URL(sourceUrl);
  } catch {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "invalid_source_url",
      token_id: claims.token_id,
      playback_session_id: claims.playback_session_id,
      source_url: sourceUrl,
    }));
    return new Response("invalid source url", { status: 502 });
  }
  if (!originUrl.protocol.startsWith("http")) {
    console.warn(JSON.stringify({
      event: "stream_proxy_failed",
      request_id: requestId,
      reason: "unsupported_source_protocol",
      token_id: claims.token_id,
      playback_session_id: claims.playback_session_id,
      source_url: sourceUrl,
    }));
    return new Response("unsupported source url", { status: 502 });
  }

  const path = resolvePayload.origin_stream_path && resolvePayload.origin_stream_path.startsWith("/")
    ? resolvePayload.origin_stream_path
    : claims.origin_stream_path.startsWith("/")
      ? claims.origin_stream_path
      : `/${claims.origin_stream_path}`;

  const upstreamStart = Date.now();
  const upstream = await fetch(originUrl.toString(), {
    method: "GET",
    headers: {
      "x-edge-token-id": claims.token_id,
      "x-edge-playback-session-id": claims.playback_session_id,
      ...(request.headers.get("range") ? { range: request.headers.get("range") as string } : {}),
    },
  });
  const firstByteMs = Date.now() - upstreamStart;

  if (!upstream.ok && upstream.status !== 206) {
    console.warn(
      JSON.stringify({
        event: "stream_proxy_failed",
        request_id: requestId,
        reason: "origin_stream_error",
        origin_status: upstream.status,
        origin_url: originUrl.toString(),
        origin_private_path: path,
        source: "connector_resolve_stream",
        resolve_ms: Date.now() - resolveStart,
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
      status: upstream.status,
      resolve_ms: Date.now() - resolveStart,
      first_byte_ms: firstByteMs,
      total_ms: Date.now() - startedAt,
      origin_private_path: path,
      source: "connector_resolve_stream",
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
