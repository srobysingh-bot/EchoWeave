import { hashConnectorSecret } from "./security";
import { Env } from "./types";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/;

export class ProvisioningError extends Error {
  status: number;

  constructor(message: string, status = 400) {
    super(message);
    this.status = status;
  }
}

export interface CreateHomeInput {
  tenant_id: string;
  home_id: string;
  name?: string;
  origin_base_url?: string;
  alexa_source_queue_id?: string;
}

export interface CreateUserInput {
  user_id: string;
  tenant_id: string;
  email?: string;
}

export interface BootstrapConnectorInput {
  tenant_id: string;
  home_id: string;
  connector_id?: string;
  ttl_seconds?: number;
}

function validateId(value: string, field: string): string {
  const trimmed = (value ?? "").trim();
  if (!trimmed) throw new ProvisioningError(`${field} is required`, 400);
  if (!ID_PATTERN.test(trimmed)) {
    throw new ProvisioningError(`${field} contains invalid characters`, 400);
  }
  return trimmed;
}

function validateOptionalUrl(value: string | undefined, field: string): string {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return "";
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new ProvisioningError(`${field} must be an absolute URL`, 400);
  }
  if (!parsed.protocol.startsWith("http")) {
    throw new ProvisioningError(`${field} must use http(s)`, 400);
  }
  return trimmed.replace(/\/$/, "");
}

export async function createOrUpdateHome(db: D1Database, input: CreateHomeInput): Promise<Record<string, unknown>> {
  const tenantId = validateId(input.tenant_id, "tenant_id");
  const homeId = validateId(input.home_id, "home_id");
  const name = (input.name ?? "").trim();
  const originBaseUrl = validateOptionalUrl(input.origin_base_url, "origin_base_url");
  const queueId = (input.alexa_source_queue_id ?? "").trim();

  const existing = await db
    .prepare("SELECT id, tenant_id, name, origin_base_url, alexa_source_queue_id FROM homes WHERE id = ? LIMIT 1")
    .bind(homeId)
    .first<{ id: string; tenant_id: string; name: string | null; origin_base_url: string | null; alexa_source_queue_id: string | null }>();

  if (existing && existing.tenant_id !== tenantId) {
    throw new ProvisioningError("home_id already belongs to a different tenant", 409);
  }

  if (!existing) {
    await db
      .prepare(
        `
        INSERT INTO homes (id, tenant_id, name, origin_base_url, alexa_source_queue_id, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        `,
      )
      .bind(homeId, tenantId, name || null, originBaseUrl || null, queueId || null)
      .run();

    return {
      created: true,
      tenant_id: tenantId,
      home_id: homeId,
      name,
      origin_base_url: originBaseUrl,
      alexa_source_queue_id: queueId,
    };
  }

  const mergedName = name || existing.name || "";
  const mergedOrigin = originBaseUrl || existing.origin_base_url || "";
  const mergedQueue = queueId || existing.alexa_source_queue_id || "";

  await db
    .prepare(
      `
      UPDATE homes
      SET name = ?, origin_base_url = ?, alexa_source_queue_id = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND tenant_id = ?
      `,
    )
    .bind(mergedName || null, mergedOrigin || null, mergedQueue || null, homeId, tenantId)
    .run();

  return {
    created: false,
    tenant_id: tenantId,
    home_id: homeId,
    name: mergedName,
    origin_base_url: mergedOrigin,
    alexa_source_queue_id: mergedQueue,
  };
}

export async function createOrUpdateUser(db: D1Database, input: CreateUserInput): Promise<Record<string, unknown>> {
  const userId = validateId(input.user_id, "user_id");
  const tenantId = validateId(input.tenant_id, "tenant_id");
  const email = (input.email ?? "").trim();

  const existing = await db
    .prepare("SELECT id, tenant_id, email FROM users WHERE id = ? LIMIT 1")
    .bind(userId)
    .first<{ id: string; tenant_id: string; email: string | null }>();

  if (existing && existing.tenant_id !== tenantId) {
    throw new ProvisioningError("user_id already belongs to a different tenant", 409);
  }

  if (!existing) {
    await db
      .prepare("INSERT INTO users (id, tenant_id, email) VALUES (?, ?, ?)")
      .bind(userId, tenantId, email || null)
      .run();
    return {
      created: true,
      user_id: userId,
      tenant_id: tenantId,
      email,
    };
  }

  const mergedEmail = email || existing.email || "";
  await db
    .prepare("UPDATE users SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND tenant_id = ?")
    .bind(mergedEmail || null, userId, tenantId)
    .run();

  return {
    created: false,
    user_id: userId,
    tenant_id: tenantId,
    email: mergedEmail,
  };
}

function randomSecret(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export async function bootstrapConnector(db: D1Database, input: BootstrapConnectorInput): Promise<Record<string, unknown>> {
  const tenantId = validateId(input.tenant_id, "tenant_id");
  const homeId = validateId(input.home_id, "home_id");
  const connectorId = validateId(input.connector_id || `conn-${homeId}`, "connector_id");

  const home = await db
    .prepare("SELECT id, tenant_id FROM homes WHERE id = ? AND tenant_id = ? LIMIT 1")
    .bind(homeId, tenantId)
    .first<{ id: string; tenant_id: string }>();
  if (!home) throw new ProvisioningError("home-not-found", 404);

  const existingConnector = await db
    .prepare("SELECT connector_id, tenant_id, home_id FROM home_connectors WHERE connector_id = ? LIMIT 1")
    .bind(connectorId)
    .first<{ connector_id: string; tenant_id: string; home_id: string }>();

  if (existingConnector && (existingConnector.tenant_id !== tenantId || existingConnector.home_id !== homeId)) {
    throw new ProvisioningError("connector_id already bound to a different tenant/home", 409);
  }

  const secret = randomSecret();
  const secretHash = await hashConnectorSecret(secret);
  const ttlSeconds = Math.max(300, Math.min(Number(input.ttl_seconds ?? 3600), 86400));
  const expiresAtIso = new Date(Date.now() + ttlSeconds * 1000).toISOString();

  await db
    .prepare(
      `
      INSERT INTO home_connectors (connector_id, tenant_id, home_id, connector_secret_hash, capabilities_json, registration_status)
      VALUES (?, ?, ?, ?, ?, 'bootstrapped')
      ON CONFLICT(connector_id) DO UPDATE SET
        tenant_id = excluded.tenant_id,
        home_id = excluded.home_id,
        connector_secret_hash = excluded.connector_secret_hash,
        capabilities_json = excluded.capabilities_json,
        registration_status = 'bootstrapped',
        updated_at = CURRENT_TIMESTAMP
      `,
    )
    .bind(connectorId, tenantId, homeId, secretHash, JSON.stringify({ bootstrap_expires_at: expiresAtIso }))
    .run();

  await db
    .prepare("UPDATE homes SET connector_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND tenant_id = ?")
    .bind(connectorId, homeId, tenantId)
    .run();

  await db
    .prepare(
      `
      INSERT INTO connector_bootstraps (id, tenant_id, home_id, connector_id, connector_secret_hash, expires_at, status)
      VALUES (?, ?, ?, ?, ?, ?, 'active')
      `,
    )
    .bind(crypto.randomUUID(), tenantId, homeId, connectorId, secretHash, expiresAtIso)
    .run();

  return {
    tenant_id: tenantId,
    home_id: homeId,
    connector_id: connectorId,
    connector_secret: secret,
    expires_at: expiresAtIso,
  };
}

export async function getHomeStatus(env: Env, tenantIdRaw: string, homeIdRaw: string): Promise<Record<string, unknown>> {
  const tenantId = validateId(tenantIdRaw, "tenant_id");
  const homeId = validateId(homeIdRaw, "home_id");

  const home = await env.ECHOWEAVE_DB
    .prepare(
      `
      SELECT id, tenant_id, name, origin_base_url, connector_id, alexa_source_queue_id, is_active
      FROM homes
      WHERE id = ? AND tenant_id = ?
      LIMIT 1
      `,
    )
    .bind(homeId, tenantId)
    .first<{
      id: string;
      tenant_id: string;
      name: string | null;
      origin_base_url: string | null;
      connector_id: string | null;
      alexa_source_queue_id: string | null;
      is_active: number;
    }>();
  if (!home) throw new ProvisioningError("home-not-found", 404);

  const connector = await env.ECHOWEAVE_DB
    .prepare(
      `
      SELECT connector_id, registration_status, updated_at
      FROM home_connectors
      WHERE connector_id = ?
      LIMIT 1
      `,
    )
    .bind(home.connector_id || "")
    .first<{ connector_id: string; registration_status: string; updated_at: string }>();

  const mappings = await env.ECHOWEAVE_DB
    .prepare("SELECT COUNT(*) as count FROM alexa_accounts WHERE tenant_id = ? AND home_id = ?")
    .bind(tenantId, homeId)
    .first<{ count: number }>();

  let connectorOnline = false;
  try {
    const doId = env.HOME_SESSION.idFromName(`${tenantId}:${homeId}`);
    const stub = env.HOME_SESSION.get(doId);
    const resp = await stub.fetch("https://home-session/status");
    if (resp.ok) {
      const body = (await resp.json()) as { online?: boolean };
      connectorOnline = Boolean(body.online);
    }
  } catch {
    connectorOnline = false;
  }

  return {
    tenant_id: tenantId,
    home_id: homeId,
    name: home.name ?? "",
    is_active: home.is_active === 1,
    origin_base_url: home.origin_base_url ?? "",
    queue_binding: home.alexa_source_queue_id ?? "",
    connector: {
      connector_id: home.connector_id ?? "",
      registration_status: connector?.registration_status ?? "not-registered",
      online: connectorOnline,
      updated_at: connector?.updated_at ?? "",
    },
    alexa_account_linked: Number(mappings?.count ?? 0) > 0,
    alexa_mapping_count: Number(mappings?.count ?? 0),
  };
}