import { Env } from "../src/types";

type Row = Record<string, unknown>;

class MockStmt {
  private db: MockD1Database;
  private sql: string;
  private args: unknown[] = [];

  constructor(db: MockD1Database, sql: string) {
    this.db = db;
    this.sql = sql;
  }

  bind(...args: unknown[]): MockStmt {
    this.args = args;
    return this;
  }

  async first<T>(): Promise<T | null> {
    return this.db.first(this.sql, this.args) as T | null;
  }

  async run(): Promise<{ success: boolean }> {
    this.db.run(this.sql, this.args);
    return { success: true };
  }
}

export class MockD1Database {
  homes = new Map<string, Row>();
  users = new Map<string, Row>();
  alexaAccounts = new Map<string, Row>();
  connectors = new Map<string, Row>();
  playbackSessions = new Map<string, Row>();
  streamTokens = new Map<string, Row>();

  prepare(sql: string): MockStmt {
    return new MockStmt(this, sql);
  }

  first(sqlRaw: string, args: unknown[]): Row | null {
    const sql = this.normalize(sqlRaw);

    if (sql.includes("from homes where id = ? and tenant_id = ? limit 1")) {
      const [homeId, tenantId] = args as [string, string];
      const home = this.homes.get(homeId);
      if (!home || home.tenant_id !== tenantId) return null;
      return { ...home };
    }

    if (sql.includes("select id, tenant_id, name, origin_base_url, alexa_source_queue_id from homes where id = ? limit 1")) {
      const [homeId] = args as [string];
      const home = this.homes.get(homeId);
      return home ? { ...home } : null;
    }

    if (sql.includes("select id, tenant_id, email from users where id = ? limit 1")) {
      const [userId] = args as [string];
      const user = this.users.get(userId);
      return user ? { ...user } : null;
    }

    if (sql.includes("select id, tenant_id from users where id = ? limit 1")) {
      const [userId] = args as [string];
      const user = this.users.get(userId);
      return user ? { id: user.id, tenant_id: user.tenant_id } : null;
    }

    if (sql.includes("select id, tenant_id from homes where id = ? limit 1")) {
      const [homeId] = args as [string];
      const home = this.homes.get(homeId);
      return home ? { id: home.id, tenant_id: home.tenant_id } : null;
    }

    if (sql.includes("from alexa_accounts where alexa_user_id = ? limit 1")) {
      const [alexaUserId] = args as [string];
      const row = this.alexaAccounts.get(alexaUserId);
      return row ? { ...row } : null;
    }

    if (sql.includes("select connector_id, tenant_id, home_id from home_connectors where connector_id = ? limit 1")) {
      const [connectorId] = args as [string];
      const row = this.connectors.get(connectorId);
      return row ? { connector_id: row.connector_id, tenant_id: row.tenant_id, home_id: row.home_id } : null;
    }

    if (sql.includes("select connector_id, registration_status, updated_at from home_connectors where connector_id = ? limit 1")) {
      const [connectorId] = args as [string];
      const row = this.connectors.get(connectorId);
      return row ? { connector_id: row.connector_id, registration_status: row.registration_status, updated_at: row.updated_at } : null;
    }

    if (sql.includes("select count(*) as count from alexa_accounts where tenant_id = ? and home_id = ?")) {
      const [tenantId, homeId] = args as [string, string];
      const count = Array.from(this.alexaAccounts.values()).filter((r) => r.tenant_id === tenantId && r.home_id === homeId)
        .length;
      return { count };
    }

    if (sql.includes("select aa.tenant_id, aa.home_id, h.origin_base_url, h.alexa_source_queue_id from alexa_accounts aa")) {
      const [alexaUserId] = args as [string];
      const mapping = this.alexaAccounts.get(alexaUserId);
      if (!mapping) return null;
      const home = this.homes.get(mapping.home_id as string);
      if (!home || home.is_active !== 1) return null;
      return {
        tenant_id: mapping.tenant_id,
        home_id: mapping.home_id,
        origin_base_url: home.origin_base_url,
        alexa_source_queue_id: home.alexa_source_queue_id ?? null,
      };
    }

    if (sql.includes("select origin_base_url from homes where id = ? and tenant_id = ? and is_active = 1 limit 1")) {
      const [homeId, tenantId] = args as [string, string];
      const home = this.homes.get(homeId);
      if (!home || home.tenant_id !== tenantId || home.is_active !== 1) return null;
      return { origin_base_url: home.origin_base_url };
    }

    return null;
  }

  run(sqlRaw: string, args: unknown[]): void {
    const sql = this.normalize(sqlRaw);

    if (sql.startsWith("insert into homes (id, tenant_id, name, origin_base_url, alexa_source_queue_id, is_active)")) {
      const [id, tenantId, name, originBaseUrl, queueId] = args as [string, string, string | null, string | null, string | null];
      this.homes.set(id, {
        id,
        tenant_id: tenantId,
        name: name ?? null,
        origin_base_url: originBaseUrl ?? null,
        alexa_source_queue_id: queueId ?? null,
        connector_id: null,
        is_active: 1,
      });
      return;
    }

    if (sql.startsWith("update homes set name = ?, origin_base_url = ?, alexa_source_queue_id = ?, updated_at = current_timestamp")) {
      const [name, origin, queue, homeId, tenantId] = args as [string | null, string | null, string | null, string, string];
      const home = this.homes.get(homeId);
      if (home && home.tenant_id === tenantId) {
        home.name = name;
        home.origin_base_url = origin;
        home.alexa_source_queue_id = queue;
      }
      return;
    }

    if (sql.startsWith("insert into users (id, tenant_id, email) values (?, ?, ?)")) {
      const [id, tenantId, email] = args as [string, string, string | null];
      this.users.set(id, { id, tenant_id: tenantId, email });
      return;
    }

    if (sql.startsWith("update users set email = ?, updated_at = current_timestamp where id = ? and tenant_id = ?")) {
      const [email, id, tenantId] = args as [string | null, string, string];
      const user = this.users.get(id);
      if (user && user.tenant_id === tenantId) user.email = email;
      return;
    }

    if (sql.startsWith("insert into alexa_accounts (alexa_user_id, user_id, tenant_id, home_id)")) {
      const [alexaUserId, userId, tenantId, homeId] = args as [string, string, string, string];
      this.alexaAccounts.set(alexaUserId, {
        alexa_user_id: alexaUserId,
        user_id: userId,
        tenant_id: tenantId,
        home_id: homeId,
      });
      return;
    }

    if (sql.startsWith("insert into home_connectors (connector_id, tenant_id, home_id, connector_secret_hash, capabilities_json, registration_status)")) {
      const [connectorId, tenantId, homeId, secretHash] = args as [string, string, string, string];
      this.connectors.set(connectorId, {
        connector_id: connectorId,
        tenant_id: tenantId,
        home_id: homeId,
        connector_secret_hash: secretHash,
        registration_status: sql.includes("'bootstrapped'") ? "bootstrapped" : "registered",
        updated_at: new Date().toISOString(),
      });
      return;
    }

    if (sql.startsWith("update homes set connector_id = ?, updated_at = current_timestamp where id = ? and tenant_id = ?")) {
      const [connectorId, homeId, tenantId] = args as [string, string, string];
      const home = this.homes.get(homeId);
      if (home && home.tenant_id === tenantId) home.connector_id = connectorId;
      return;
    }

    if (sql.startsWith("insert into connector_bootstraps")) {
      return;
    }

    if (sql.startsWith("insert into playback_sessions")) {
      const [id, tenantId, homeId, alexaUserId, queueId, queueItemId, metadataJson] = args as [string, string, string, string, string, string, string];
      this.playbackSessions.set(id, {
        id,
        tenant_id: tenantId,
        home_id: homeId,
        alexa_user_id: alexaUserId,
        queue_id: queueId,
        queue_item_id: queueItemId,
        metadata_json: metadataJson,
      });
      return;
    }

    if (sql.startsWith("insert into stream_tokens")) {
      const [id, tenantId, homeId, playbackSessionId, tokenSignature, expiresAt] = args as [string, string, string, string, string, string];
      this.streamTokens.set(id, {
        id,
        tenant_id: tenantId,
        home_id: homeId,
        playback_session_id: playbackSessionId,
        token_signature: tokenSignature,
        expires_at: expiresAt,
      });
      return;
    }

    if (sql.startsWith("update playback_sessions set stream_token_id = ?, updated_at = current_timestamp where id = ?")) {
      return;
    }
  }

  private normalize(sql: string): string {
    return sql.replace(/\s+/g, " ").trim().toLowerCase();
  }
}

export function createEnv(overrides?: Partial<Env>): Env {
  const db = new MockD1Database();
  const homeSessionNamespace = {
    idFromName(name: string): string {
      return name;
    },
    get(_id: string): { fetch: (request: Request | string, init?: RequestInit) => Promise<Response> } {
      return {
        async fetch(request: Request | string, init?: RequestInit): Promise<Response> {
          const url = typeof request === "string" ? request : request.url;
          if (url.endsWith("/status")) {
            return new Response(JSON.stringify({ online: false }), { status: 200, headers: { "content-type": "application/json" } });
          }
          if (url.endsWith("/command")) {
            return new Response(
              JSON.stringify({
                queue_id: "q1",
                queue_item_id: "i1",
                title: "Song",
                origin_stream_path: "/edge/stream/q1/i1",
                content_type: "audio/mpeg",
              }),
              { status: 200, headers: { "content-type": "application/json" } },
            );
          }
          return new Response(JSON.stringify({ error: "not-found" }), { status: 404 });
        },
      };
    },
  } as unknown as DurableObjectNamespace<any>;

  return {
    ECHOWEAVE_DB: db as unknown as D1Database,
    HOME_SESSION: homeSessionNamespace,
    STREAM_TOKEN_SIGNING_SECRET: "stream-secret",
    EDGE_ORIGIN_SHARED_SECRET: "edge-origin-secret",
    ADMIN_API_KEY: "test-admin-key",
    ALEXA_SIGNATURE_ENFORCE: "false",
    STREAM_TOKEN_TTL_SECONDS: "300",
    ...overrides,
  };
}
