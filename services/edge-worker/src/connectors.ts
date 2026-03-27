import { getConnectorRecord, upsertConnectorRegistration } from "./db";
import { hashConnectorSecret, safeEqual } from "./security";
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
    .prepare("SELECT id FROM homes WHERE id = ? AND tenant_id = ? AND is_active = 1 LIMIT 1")
    .bind(payload.home_id, payload.tenant_id)
    .first<{ id: string }>();
  if (!homeExists) return json({ error: "unknown-home" }, 404);

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

  const record = await getConnectorRecord(env.ECHOWEAVE_DB, connectorId);
  if (!record) return json({ error: "connector-not-registered" }, 401);

  const suppliedHash = await hashConnectorSecret(connectorSecret);
  if (
    !safeEqual(record.connector_secret_hash, suppliedHash) ||
    !safeEqual(record.tenant_id, tenantId) ||
    !safeEqual(record.home_id, homeId)
  ) {
    return json({ error: "connector-auth-failed" }, 401);
  }

  const doId = env.HOME_SESSION.idFromName(`${tenantId}:${homeId}`);
  const stub = env.HOME_SESSION.get(doId);

  const forwardUrl = `https://home-session/attach?connector_id=${encodeURIComponent(connectorId)}&tenant_id=${encodeURIComponent(tenantId)}&home_id=${encodeURIComponent(homeId)}`;
  return stub.fetch(forwardUrl, {
    method: "GET",
    headers: request.headers,
  });
}
