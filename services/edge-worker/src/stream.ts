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
  const claims = await verifySignedStreamToken(token, env.STREAM_TOKEN_SIGNING_SECRET);
  if (!claims) {
    return new Response("invalid or expired stream token", { status: 401 });
  }

  const home = await env.ECHOWEAVE_DB
    .prepare("SELECT origin_base_url FROM homes WHERE id = ? AND tenant_id = ? AND is_active = 1 LIMIT 1")
    .bind(claims.home_id, claims.tenant_id)
    .first<{ origin_base_url: string }>();

  if (!home?.origin_base_url) {
    return new Response("home origin unavailable", { status: 404 });
  }

  const path = claims.origin_stream_path.startsWith("/") ? claims.origin_stream_path : `/${claims.origin_stream_path}`;
  const originUrl = `${home.origin_base_url}${path}`;
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
    return new Response(`origin stream error (${upstream.status})`, { status: 502 });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: copyStreamHeaders(upstream),
  });
}
