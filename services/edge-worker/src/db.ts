import { ConnectorRegistrationPayload, HomeMapping } from "./types";

interface AlexaAccountRow {
  tenant_id: string;
  home_id: string;
  origin_base_url: string;
  alexa_source_queue_id: string | null;
}

export async function resolveHomeByAlexaUser(db: D1Database, alexaUserId: string): Promise<HomeMapping | null> {
  const stmt = db
    .prepare(
      `
      SELECT aa.tenant_id, aa.home_id, h.origin_base_url, h.alexa_source_queue_id
      FROM alexa_accounts aa
      INNER JOIN homes h ON h.id = aa.home_id
      WHERE aa.alexa_user_id = ? AND h.is_active = 1
      LIMIT 1
      `,
    )
    .bind(alexaUserId);

  const row = await stmt.first<AlexaAccountRow>();
  if (row) {
    return {
      tenant_id: row.tenant_id,
      home_id: row.home_id,
      origin_base_url: row.origin_base_url,
      alexa_source_queue_id: row.alexa_source_queue_id,
    };
  }

  const provisionedHomeCount = await db
    .prepare(
      `
      SELECT COUNT(*) as count
      FROM homes
      WHERE is_active = 1
        AND origin_base_url IS NOT NULL
        AND alexa_source_queue_id IS NOT NULL
      `,
    )
    .first<{ count: number }>();

  let fallbackHome: AlexaAccountRow | null = null;

  if (Number(provisionedHomeCount?.count ?? 0) === 1) {
    fallbackHome = await db
      .prepare(
        `
        SELECT tenant_id, id as home_id, origin_base_url, alexa_source_queue_id
        FROM homes
        WHERE is_active = 1
          AND origin_base_url IS NOT NULL
          AND alexa_source_queue_id IS NOT NULL
        LIMIT 1
        `,
      )
      .first<AlexaAccountRow>();
  }

  if (!fallbackHome) {
    const activeHomeCount = await db
      .prepare(
        `
        SELECT COUNT(*) as count
        FROM homes
        WHERE is_active = 1
        `,
      )
      .first<{ count: number }>();

    if (Number(activeHomeCount?.count ?? 0) !== 1) return null;

    fallbackHome = await db
      .prepare(
        `
        SELECT tenant_id, id as home_id, origin_base_url, alexa_source_queue_id
        FROM homes
        WHERE is_active = 1
        LIMIT 1
        `,
      )
      .first<AlexaAccountRow>();
  }

  if (!fallbackHome) return null;

  console.info(
    JSON.stringify({
      event: "alexa_home_fallback_resolved",
      reason: "sole-active-home",
      tenant_id: fallbackHome.tenant_id,
      home_id: fallbackHome.home_id,
    }),
  );

  return {
    tenant_id: fallbackHome.tenant_id,
    home_id: fallbackHome.home_id,
    origin_base_url: fallbackHome.origin_base_url,
    alexa_source_queue_id: fallbackHome.alexa_source_queue_id,
  };
}

export async function getConnectorRecord(
  db: D1Database,
  connectorId: string,
): Promise<{ connector_secret_hash: string; tenant_id: string; home_id: string } | null> {
  const row = await db
    .prepare(
      `
      SELECT connector_secret_hash, tenant_id, home_id
      FROM home_connectors
      WHERE connector_id = ?
      LIMIT 1
      `,
    )
    .bind(connectorId)
    .first<{ connector_secret_hash: string; tenant_id: string; home_id: string }>();
  return row ?? null;
}

export async function resolveAlexaUserForHome(
  db: D1Database,
  tenantId: string,
  homeId: string,
): Promise<string | null> {
  const row = await db
    .prepare(
      `
      SELECT aa.alexa_user_id
      FROM alexa_accounts aa
      WHERE aa.tenant_id = ?
        AND aa.home_id = ?
      ORDER BY aa.updated_at DESC
      LIMIT 1
      `,
    )
    .bind(tenantId, homeId)
    .first<{ alexa_user_id: string }>();

  return row?.alexa_user_id ?? null;
}

export async function upsertConnectorRegistration(
  db: D1Database,
  payload: ConnectorRegistrationPayload,
  connectorSecretHash: string,
): Promise<void> {
  const originBaseUrl = (payload.origin_base_url ?? "").trim();
  const queueId = (payload.alexa_source_queue_id ?? "").trim();

  await db
    .prepare(
      `
      INSERT INTO home_connectors (connector_id, tenant_id, home_id, connector_secret_hash, capabilities_json, registration_status)
      VALUES (?, ?, ?, ?, ?, 'registered')
      ON CONFLICT(connector_id) DO UPDATE SET
        tenant_id = excluded.tenant_id,
        home_id = excluded.home_id,
        connector_secret_hash = excluded.connector_secret_hash,
        capabilities_json = excluded.capabilities_json,
        registration_status = 'registered',
        updated_at = CURRENT_TIMESTAMP
      `,
    )
    .bind(
      payload.connector_id,
      payload.tenant_id,
      payload.home_id,
      connectorSecretHash,
      JSON.stringify(payload.capabilities ?? {}),
    )
    .run();

  await db
    .prepare(
      `
      INSERT INTO homes (id, tenant_id, name, origin_base_url, alexa_source_queue_id, connector_id, is_active)
      VALUES (?, ?, NULL, ?, ?, ?, 1)
      ON CONFLICT(id) DO UPDATE SET
        tenant_id = excluded.tenant_id,
        connector_id = excluded.connector_id,
        origin_base_url = COALESCE(NULLIF(excluded.origin_base_url, ''), origin_base_url),
        alexa_source_queue_id = COALESCE(NULLIF(excluded.alexa_source_queue_id, ''), alexa_source_queue_id),
        is_active = 1,
        updated_at = CURRENT_TIMESTAMP
      `,
    )
    .bind(
      payload.home_id,
      payload.tenant_id,
      originBaseUrl,
      queueId || null,
      payload.connector_id,
    )
    .run();
}

export async function createPlaybackSession(
  db: D1Database,
  input: {
    id: string;
    tenant_id: string;
    home_id: string;
    alexa_user_id: string;
    queue_id: string;
    queue_item_id: string;
    metadata_json: string;
  },
): Promise<void> {
  await db
    .prepare(
      `
      INSERT INTO playback_sessions
      (id, tenant_id, home_id, alexa_user_id, queue_id, queue_item_id, metadata_json, state)
      VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared')
      `,
    )
    .bind(
      input.id,
      input.tenant_id,
      input.home_id,
      input.alexa_user_id,
      input.queue_id,
      input.queue_item_id,
      input.metadata_json,
    )
    .run();
}

export async function recordStreamToken(
  db: D1Database,
  input: {
    id: string;
    tenant_id: string;
    home_id: string;
    playback_session_id: string;
    token_signature: string;
    expires_at_iso: string;
  },
): Promise<void> {
  await db
    .prepare(
      `
      INSERT INTO stream_tokens (id, tenant_id, home_id, playback_session_id, token_signature, expires_at)
      VALUES (?, ?, ?, ?, ?, ?)
      `,
    )
    .bind(
      input.id,
      input.tenant_id,
      input.home_id,
      input.playback_session_id,
      input.token_signature,
      input.expires_at_iso,
    )
    .run();

  await db
    .prepare(
      `
      UPDATE playback_sessions
      SET stream_token_id = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
      `,
    )
    .bind(input.id, input.playback_session_id)
    .run();
}

export async function getRecordedStreamToken(
  db: D1Database,
  input: {
    id: string;
    tenant_id: string;
    home_id: string;
    playback_session_id: string;
    token_signature: string;
  },
): Promise<{ id: string; expires_at: string } | null> {
  const row = await db
    .prepare(
      `
      SELECT id, expires_at
      FROM stream_tokens
      WHERE id = ?
        AND tenant_id = ?
        AND home_id = ?
        AND playback_session_id = ?
        AND token_signature = ?
      LIMIT 1
      `,
    )
    .bind(
      input.id,
      input.tenant_id,
      input.home_id,
      input.playback_session_id,
      input.token_signature,
    )
    .first<{ id: string; expires_at: string }>();

  return row ?? null;
}

export async function getPlaybackSessionForStreamToken(
  db: D1Database,
  tokenId: string,
): Promise<{ tenant_id: string; home_id: string; playback_session_id: string } | null> {
  const row = await db
    .prepare(
      `
      SELECT tenant_id, home_id, playback_session_id
      FROM stream_tokens
      WHERE id = ?
      LIMIT 1
      `,
    )
    .bind(tokenId)
    .first<{ tenant_id: string; home_id: string; playback_session_id: string }>();

  return row ?? null;
}

export async function getOriginBaseUrl(
  db: D1Database,
  homeId: string,
  tenantId: string,
): Promise<string | null> {
  const row = await db
    .prepare(
      `
      SELECT origin_base_url
      FROM homes
      WHERE id = ? AND tenant_id = ? AND is_active = 1
      LIMIT 1
      `,
    )
    .bind(homeId, tenantId)
    .first<{ origin_base_url: string }>();

  return row?.origin_base_url || null;
}
