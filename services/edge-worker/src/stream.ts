import { resolveHomeByAlexaUser } from "./db";
import { signPayload, verifySignedStreamToken } from "./security";
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
  const claims = await verifySignedStreamToken(token, env.STREAM_TOKEN_SIGNING_SECRET);
  if (!claims) {
    console.warn(JSON.stringify({ event: "stream_proxy_failed", request_id: requestId, reason: "invalid_or_expired_token" }));
    return new Response("invalid or expired stream token", { status: 401 });
  }

  const home = await env.ECHOWEAVE_DB
    .prepare("SELECT origin_base_url FROM homes WHERE id = ? AND tenant_id = ? AND is_active = 1 LIMIT 1")
    .bind(claims.home_id, claims.tenant_id)
    .first<{ origin_base_url: string }>();

  if (!home?.origin_base_url) {
    console.warn(JSON.stringify({ event: "stream_proxy_failed", request_id: requestId, reason: "home_origin_unavailable" }));
    return new Response("home origin unavailable", { status: 404 });
  }

  const path = claims.origin_stream_path.startsWith("/") ? claims.origin_stream_path : `/${claims.origin_stream_path}`;
  const originUrl = `${home.origin_base_url}${path}`;
  console.info(JSON.stringify({ event: "stream_proxy_started", request_id: requestId, tenant_id: claims.tenant_id, home_id: claims.home_id, path }));
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signaturePayload = `${timestamp}:GET:${path}`;
  const signature = await signPayload(signaturePayload, env.EDGE_ORIGIN_SHARED_SECRET);

  const upstream = await fetch(originUrl, {
    method: "GET",
    headers: {
      "x-edge-timestamp": timestamp,
      "x-edge-signature": signature,
      ...(request.headers.get("range") ? { range: request.headers.get("range") as string } : {}),
    },
  });

  if (!upstream.ok && upstream.status !== 206) {
    console.warn(
      JSON.stringify({
        event: "stream_proxy_failed",
        request_id: requestId,
        reason: "origin_stream_error",
        origin_status: upstream.status,
      }),
    );
    return new Response(`origin stream error (${upstream.status})`, { status: 502 });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: copyStreamHeaders(upstream),
  });
}
