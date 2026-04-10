import { createPlaybackSession, getConnectorRecord, recordStreamToken, upsertConnectorRegistration } from "./db";
import { hashConnectorSecret, issueSignedStreamToken, safeEqual } from "./security";
import { ConnectorRegistrationPayload, Env } from "./types";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function badRequest(message: string): Response {
  return json({ error: message }, 400);
}

async function authenticateConnector(
  args: {
    env: Env;
    connectorId: string;
    connectorSecret: string;
    tenantId: string;
    homeId: string;
  },
): Promise<{ ok: true } | { ok: false; status: number; error: string }> {
  const { env, connectorId, connectorSecret, tenantId, homeId } = args;
  if (!connectorId || !connectorSecret || !tenantId || !homeId) {
    return { ok: false, status: 400, error: "connector_id, connector_secret, tenant_id, home_id are required" };
  }

  const record = await getConnectorRecord(env.ECHOWEAVE_DB, connectorId);
  if (!record) return { ok: false, status: 401, error: "connector-not-registered" };

  const suppliedHash = await hashConnectorSecret(connectorSecret);
  if (
    !safeEqual(record.connector_secret_hash, suppliedHash) ||
    !safeEqual(record.tenant_id, tenantId) ||
    !safeEqual(record.home_id, homeId)
  ) {
    return { ok: false, status: 401, error: "connector-auth-failed" };
  }

  return { ok: true };
}

export async function handleConnectorRegister(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return json({ error: "method-not-allowed" }, 405);

  const bootstrapSecret = env.CONNECTOR_BOOTSTRAP_SECRET;
  if (bootstrapSecret) {
    const supplied = request.headers.get("x-connector-bootstrap-secret") ?? "";
    if (!safeEqual(supplied, bootstrapSecret)) {
      return json({ error: "unauthorized" }, 401);
    }
  }

  const payload = (await request.json()) as ConnectorRegistrationPayload;
  if (!payload.connector_id || !payload.connector_secret || !payload.tenant_id || !payload.home_id) {
    return badRequest("connector_id, connector_secret, tenant_id, home_id are required");
  }
  if (payload.origin_base_url) {
    try {
      const parsed = new URL(payload.origin_base_url);
      if (!parsed.protocol.startsWith("http")) {
        return badRequest("origin_base_url must be an http(s) URL");
      }
    } catch {
      return badRequest("origin_base_url must be an absolute URL");
    }
  }

  const homeExists = await env.ECHOWEAVE_DB
    .prepare("SELECT id, tenant_id FROM homes WHERE id = ? LIMIT 1")
    .bind(payload.home_id)
    .first<{ id: string; tenant_id: string }>();
  if (homeExists && homeExists.tenant_id !== payload.tenant_id) {
    return json({ error: "cross-tenant home mismatch" }, 409);
  }
  if (!homeExists && !payload.origin_base_url) {
    return badRequest("origin_base_url is required when creating a home");
  }

  const secretHash = await hashConnectorSecret(payload.connector_secret);
  const existing = await getConnectorRecord(env.ECHOWEAVE_DB, payload.connector_id);
  if (
    existing &&
    (!safeEqual(existing.tenant_id, payload.tenant_id) || !safeEqual(existing.home_id, payload.home_id))
  ) {
    return json({ error: "connector-id-already-bound" }, 409);
  }

  await upsertConnectorRegistration(env.ECHOWEAVE_DB, payload, secretHash);
  return json({ ok: true, connector_id: payload.connector_id, tenant_id: payload.tenant_id, home_id: payload.home_id });
}

export async function handleConnectorWebSocket(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET") return json({ error: "method-not-allowed" }, 405);
  if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
    return json({ error: "upgrade-required" }, 426);
  }

  const url = new URL(request.url);
  const connectorId = url.searchParams.get("connector_id") ?? "";
  const connectorSecret = url.searchParams.get("connector_secret") ?? "";
  const tenantId = url.searchParams.get("tenant_id") ?? "";
  const homeId = url.searchParams.get("home_id") ?? "";

  if (!connectorId || !connectorSecret || !tenantId || !homeId) {
    return badRequest("connector_id, connector_secret, tenant_id, home_id query params required");
  }

  const auth = await authenticateConnector({
    env,
    connectorId,
    connectorSecret,
    tenantId,
    homeId,
  });
  if (!auth.ok) return json({ error: auth.error }, auth.status);

  const doId = env.HOME_SESSION.idFromName(`${tenantId}:${homeId}`);
  const stub = env.HOME_SESSION.get(doId);

  const forwardUrl = `https://home-session/attach?connector_id=${encodeURIComponent(connectorId)}&tenant_id=${encodeURIComponent(tenantId)}&home_id=${encodeURIComponent(homeId)}`;
  return stub.fetch(forwardUrl, {
    method: "GET",
    headers: request.headers,
  });
}

export async function handleConnectorPlaybackHandoff(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return json({ error: "method-not-allowed" }, 405);

  const body = (await request.json()) as {
    connector_id?: string;
    connector_secret?: string;
    tenant_id?: string;
    home_id?: string;
    queue_id?: string;
    queue_item_id?: string;
    origin_stream_path?: string;
    title?: string;
    subtitle?: string;
    image_url?: string;
    request_id?: string;
    player_id?: string;
  };

  const connectorId = String(body.connector_id ?? "").trim();
  const connectorSecret = String(body.connector_secret ?? "").trim();
  const tenantId = String(body.tenant_id ?? "").trim();
  const homeId = String(body.home_id ?? "").trim();
  const queueId = String(body.queue_id ?? "").trim();
  const queueItemId = String(body.queue_item_id ?? "").trim();
  const originStreamPath = String(body.origin_stream_path ?? "").trim();

  if (!queueId || !queueItemId || !originStreamPath) {
    return badRequest("queue_id, queue_item_id, origin_stream_path are required");
  }

  const auth = await authenticateConnector({
    env,
    connectorId,
    connectorSecret,
    tenantId,
    homeId,
  });
  if (!auth.ok) return json({ error: auth.error }, auth.status);

  const nowSeconds = Math.floor(Date.now() / 1000);
  const ttl = Number(env.STREAM_TOKEN_TTL_SECONDS ?? "300");
  const playbackSessionId = crypto.randomUUID();
  const tokenId = crypto.randomUUID();
  const claims = {
    token_id: tokenId,
    tenant_id: tenantId,
    home_id: homeId,
    playback_session_id: playbackSessionId,
    queue_id: queueId,
    queue_item_id: queueItemId,
    origin_stream_path: originStreamPath,
    exp: nowSeconds + ttl,
  };

  const streamToken = await issueSignedStreamToken(claims, env.STREAM_TOKEN_SIGNING_SECRET);
  const signature = streamToken.split(".")[1] ?? "";

  await createPlaybackSession(env.ECHOWEAVE_DB, {
    id: playbackSessionId,
    tenant_id: tenantId,
    home_id: homeId,
    alexa_user_id: "ma_push_url",
    queue_id: queueId,
    queue_item_id: queueItemId,
    metadata_json: JSON.stringify({
      title: String(body.title ?? ""),
      subtitle: String(body.subtitle ?? ""),
      image_url: String(body.image_url ?? ""),
      source: "ma_push_url",
      player_id: String(body.player_id ?? ""),
    }),
  });

  await recordStreamToken(env.ECHOWEAVE_DB, {
    id: tokenId,
    tenant_id: tenantId,
    home_id: homeId,
    playback_session_id: playbackSessionId,
    token_signature: signature,
    expires_at_iso: new Date((nowSeconds + ttl) * 1000).toISOString(),
  });

  const streamUrl = `${new URL(request.url).origin}/v1/stream/${encodeURIComponent(streamToken)}`;

  console.info(
    JSON.stringify({
      event: "connector_playback_handoff_created",
      request_id: String(body.request_id ?? ""),
      connector_id: connectorId,
      tenant_id: tenantId,
      home_id: homeId,
      player_id: String(body.player_id ?? ""),
      queue_id: queueId,
      queue_item_id: queueItemId,
      playback_session_id: playbackSessionId,
      stream_token_id: tokenId,
      stream_url: streamUrl,
    }),
  );

  return json({
    ok: true,
    playback_session_id: playbackSessionId,
    stream_token_id: tokenId,
    stream_url: streamUrl,
  });
}
