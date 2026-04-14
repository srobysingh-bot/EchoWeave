import {
  createPlaybackSession,
  getConnectorRecord,
  recordStreamToken,
  resolveAlexaUserForHome,
  upsertConnectorRegistration,
} from "./db";
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

async function getPlaybackStartStatusFromSession(
  env: Env,
  tenantId: string,
  homeId: string,
  playbackSessionId: string,
): Promise<{
  known_session: boolean;
  stream_fetch_started: boolean;
  playback_started: boolean;
  playback_failed: boolean;
  play_request_id?: string;
  created_at_iso?: string;
  fetched_at_iso?: string;
  playback_started_at_iso?: string;
  playback_failed_at_iso?: string;
  playback_failed_error?: unknown;
  last_event_type?: string;
  age_ms?: number;
}>
{
  const doId = env.HOME_SESSION.idFromName(`${tenantId}:${homeId}`);
  const stub = env.HOME_SESSION.get(doId);
  const statusResp = await stub.fetch("https://home-session/playback-start", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      action: "status",
      playback_session_id: playbackSessionId,
    }),
  });

  if (!statusResp.ok) {
    throw new Error(`playback-start-status-do-failed:${statusResp.status}`);
  }
  const statusBody = (await statusResp.json()) as {
    known_session?: boolean;
    stream_fetch_started?: boolean;
    playback_started?: boolean;
    playback_failed?: boolean;
    play_request_id?: string;
    created_at_iso?: string;
    fetched_at_iso?: string;
    playback_started_at_iso?: string;
    playback_failed_at_iso?: string;
    playback_failed_error?: unknown;
    last_event_type?: string;
    age_ms?: number;
  };
  return {
    known_session: !!statusBody.known_session,
    stream_fetch_started: !!statusBody.stream_fetch_started,
    playback_started: !!statusBody.playback_started,
    playback_failed: !!statusBody.playback_failed,
    play_request_id: statusBody.play_request_id,
    created_at_iso: statusBody.created_at_iso,
    fetched_at_iso: statusBody.fetched_at_iso,
    playback_started_at_iso: statusBody.playback_started_at_iso,
    playback_failed_at_iso: statusBody.playback_failed_at_iso,
    playback_failed_error: statusBody.playback_failed_error,
    last_event_type: statusBody.last_event_type,
    age_ms: statusBody.age_ms,
  };
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
  const startedAt = Date.now();
  try {
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
    const requestId = String(body.request_id ?? "");
    const playerId = String(body.player_id ?? "");
    const runtime = {
      build_id: env.BUILD_ID ?? "unknown",
      deploy_sha: env.DEPLOY_SHA ?? "unknown",
      deploy_env: env.DEPLOY_ENV ?? "unknown",
      worker_name: env.WORKER_NAME ?? "unknown",
      db_id: env.ECHOWEAVE_DB_ID ?? "unknown",
    };

    const sourceFormatHint = (() => {
      const path = originStreamPath.toLowerCase();
      const idx = path.lastIndexOf(".");
      if (idx === -1) return "";
      const ext = path.slice(idx + 1).split("?")[0].trim();
      return ext;
    })();

    const logStep = (step: string, extra: Record<string, unknown> = {}) => {
      console.info(
        JSON.stringify({
          event: "playback_handoff_step",
          request_id: requestId,
          step,
          elapsed_ms: Date.now() - startedAt,
          connector_id: connectorId,
          tenant_id: tenantId,
          home_id: homeId,
          player_id: playerId,
          queue_id: queueId,
          queue_item_id: queueItemId,
          source_format_hint: sourceFormatHint,
          runtime,
          ...extra,
        }),
      );
    };

    console.info(
      JSON.stringify({
        event: "playback_handoff_request_received",
        request_id: requestId,
        connector_id: connectorId,
        tenant_id: tenantId,
        home_id: homeId,
        player_id: playerId,
        queue_id: queueId,
        queue_item_id: queueItemId,
        origin_stream_path: originStreamPath,
        runtime,
      }),
    );
    logStep("request_received");

    if (!queueId || !queueItemId || !originStreamPath) {
      logStep("validation_failed_missing_identifiers", {
        has_queue_id: !!queueId,
        has_queue_item_id: !!queueItemId,
        has_origin_stream_path: !!originStreamPath,
      });
      console.warn(
        JSON.stringify({
          event: "playback_handoff_failed",
          request_id: requestId,
          reason: "missing_required_identifiers",
          runtime,
        }),
      );
      return json({ error: "queue_id, queue_item_id, origin_stream_path are required", runtime }, 400);
    }
    logStep("validation_ok");

    logStep("connector_auth_started");
    const auth = await authenticateConnector({
      env,
      connectorId,
      connectorSecret,
      tenantId,
      homeId,
    });
    if (!auth.ok) {
      console.warn(
        JSON.stringify({
          event: "playback_handoff_failed",
          request_id: requestId,
          reason: auth.error,
          status: auth.status,
          connector_id: connectorId,
          tenant_id: tenantId,
          home_id: homeId,
          runtime,
        }),
      );
      return json({ error: auth.error, runtime }, auth.status);
    }
    logStep("connector_auth_ok");

    console.info(
      JSON.stringify({
        event: "playback_handoff_home_resolved",
        request_id: requestId,
        connector_id: connectorId,
        tenant_id: tenantId,
        home_id: homeId,
        player_id: playerId,
        queue_id: queueId,
        queue_item_id: queueItemId,
        runtime,
      }),
    );
    logStep("home_context_resolved");

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
      client_profile: "alexa",
      exp: nowSeconds + ttl,
    };
    logStep("token_claims_prepared", {
      stream_token_id: tokenId,
      playback_session_id: playbackSessionId,
      token_ttl_seconds: ttl,
      token_exp: claims.exp,
      client_profile: claims.client_profile,
    });

    const streamToken = await issueSignedStreamToken(claims, env.STREAM_TOKEN_SIGNING_SECRET);
    const signature = streamToken.split(".")[1] ?? "";
    logStep("token_signed", {
      stream_token_id: tokenId,
      token_signature_length: signature.length,
    });

    logStep("alexa_user_lookup_started");
    const alexaUserId = await resolveAlexaUserForHome(env.ECHOWEAVE_DB, tenantId, homeId);
    if (!alexaUserId) {
      logStep("alexa_user_lookup_failed_not_linked");
      console.warn(
        JSON.stringify({
          event: "playback_handoff_failed",
          request_id: requestId,
          reason: "alexa_user_not_found_for_home",
          tenant_id: tenantId,
          home_id: homeId,
          runtime,
        }),
      );
      return json({ error: "alexa-user-not-linked", runtime }, 409);
    }
    logStep("alexa_user_lookup_ok", {
      alexa_user_id_truncated: `${alexaUserId.slice(0, 12)}...${alexaUserId.slice(-6)}`,
    });

    const alexaAccountExists = await env.ECHOWEAVE_DB.prepare(
      `
      SELECT 1 AS ok
      FROM alexa_accounts
      WHERE alexa_user_id = ? AND tenant_id = ? AND home_id = ?
      LIMIT 1
      `,
    )
      .bind(alexaUserId, tenantId, homeId)
      .first<{ ok: number }>();

    if (!alexaAccountExists || alexaAccountExists.ok !== 1) {
      console.warn(
        JSON.stringify({
          event: "playback_handoff_failed",
          request_id: requestId,
          reason: "alexa_user_fk_verification_failed",
          tenant_id: tenantId,
          home_id: homeId,
          chosen_alexa_user_id: alexaUserId,
          runtime,
        }),
      );
      return json({ error: "alexa-user-fk-verification-failed", runtime }, 409);
    }
    logStep("alexa_user_fk_verified");

    console.info(
      JSON.stringify({
        event: "playback_handoff_alexa_user_verified",
        request_id: requestId,
        tenant_id: tenantId,
        home_id: homeId,
        chosen_alexa_user_id: alexaUserId,
        exists: true,
        runtime,
      }),
    );

    console.info(
      JSON.stringify({
        event: "playback_session_insert_attempt",
        request_id: requestId,
        tenant_id: tenantId,
        home_id: homeId,
        chosen_alexa_user_id: alexaUserId,
        queue_id: queueId,
        queue_item_id: queueItemId,
        runtime,
      }),
    );

    try {
      await createPlaybackSession(env.ECHOWEAVE_DB, {
        id: playbackSessionId,
        tenant_id: tenantId,
        home_id: homeId,
        alexa_user_id: alexaUserId,
        queue_id: queueId,
        queue_item_id: queueItemId,
        metadata_json: JSON.stringify({
          title: String(body.title ?? ""),
          subtitle: String(body.subtitle ?? ""),
          image_url: String(body.image_url ?? ""),
          source: "ma_push_url",
          player_id: playerId,
        }),
      });
      logStep("playback_session_inserted", {
        playback_session_id: playbackSessionId,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(
        JSON.stringify({
          event: "playback_session_insert_failed",
          request_id: requestId,
          tenant_id: tenantId,
          home_id: homeId,
          chosen_alexa_user_id: alexaUserId,
          queue_id: queueId,
          queue_item_id: queueItemId,
          error: message,
          runtime,
        }),
      );
      if (message.toLowerCase().includes("foreign key constraint failed")) {
        return json(
          {
            error: "alexa-user-not-linked",
            reason: "playback_session_fk_failed",
            chosen_alexa_user_id: alexaUserId,
            runtime,
          },
          409,
        );
      }
      throw error;
    }

    try {
      await recordStreamToken(env.ECHOWEAVE_DB, {
        id: tokenId,
        tenant_id: tenantId,
        home_id: homeId,
        playback_session_id: playbackSessionId,
        token_signature: signature,
        expires_at_iso: new Date((nowSeconds + ttl) * 1000).toISOString(),
      });
      logStep("stream_token_recorded", {
        stream_token_id: tokenId,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(
        JSON.stringify({
          event: "stream_token_insert_failed",
          request_id: requestId,
          tenant_id: tenantId,
          home_id: homeId,
          playback_session_id: playbackSessionId,
          stream_token_id: tokenId,
          error: message,
          runtime,
        }),
      );
      throw error;
    }

    try {
      const doId = env.HOME_SESSION.idFromName(`${tenantId}:${homeId}`);
      const stub = env.HOME_SESSION.get(doId);
      const registerResp = await stub.fetch("https://home-session/playback-start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "register",
          playback_session_id: playbackSessionId,
          token_id: tokenId,
          request_id: requestId,
        }),
      });

      if (!registerResp.ok) {
        const registerText = await registerResp.text();
        logStep("playback_start_watch_register_failed", {
          playback_session_id: playbackSessionId,
          stream_token_id: tokenId,
          status: registerResp.status,
          body: registerText,
        });
      } else {
        logStep("playback_start_watch_registered", {
          playback_session_id: playbackSessionId,
          stream_token_id: tokenId,
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logStep("playback_start_watch_register_failed", {
        playback_session_id: playbackSessionId,
        stream_token_id: tokenId,
        error: message,
      });
    }

    const streamUrl = `${new URL(request.url).origin}/v1/stream/${encodeURIComponent(streamToken)}`;
    logStep("stream_url_built", {
      stream_url: streamUrl,
    });

    console.info(
      JSON.stringify({
        event: "playback_handoff_token_created",
        request_id: requestId,
        connector_id: connectorId,
        tenant_id: tenantId,
        home_id: homeId,
        playback_session_id: playbackSessionId,
        stream_token_id: tokenId,
        stream_url: streamUrl,
        runtime,
      }),
    );

    const payload = {
      ok: true,
      playback_session_id: playbackSessionId,
      stream_token_id: tokenId,
      stream_url: streamUrl,
      runtime,
    };
    logStep("response_ready", {
      ok: true,
      playback_session_id: playbackSessionId,
      stream_token_id: tokenId,
    });
    console.info(
      JSON.stringify({
        event: "playback_handoff_response_sent",
        request_id: requestId,
        ok: true,
        playback_session_id: playbackSessionId,
        stream_token_id: tokenId,
        runtime,
      }),
    );
    return json(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "internal-error";
    const runtime = {
      build_id: env.BUILD_ID ?? "unknown",
      deploy_sha: env.DEPLOY_SHA ?? "unknown",
      deploy_env: env.DEPLOY_ENV ?? "unknown",
      worker_name: env.WORKER_NAME ?? "unknown",
      db_id: env.ECHOWEAVE_DB_ID ?? "unknown",
    };
    console.error(
      JSON.stringify({
        event: "playback_handoff_failed",
        reason: "unhandled_exception",
        error: message,
        runtime,
      }),
    );
    return json({ error: message, runtime }, 500);
  }
}

export async function handleConnectorPlaybackStartStatus(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") return json({ error: "method-not-allowed" }, 405);

  const body = (await request.json()) as {
    connector_id?: string;
    connector_secret?: string;
    tenant_id?: string;
    home_id?: string;
    playback_session_id?: string;
    request_id?: string;
  };

  const connectorId = String(body.connector_id ?? "").trim();
  const connectorSecret = String(body.connector_secret ?? "").trim();
  const tenantId = String(body.tenant_id ?? "").trim();
  const homeId = String(body.home_id ?? "").trim();
  const playbackSessionId = String(body.playback_session_id ?? "").trim();
  const requestId = String(body.request_id ?? "").trim();

  if (!playbackSessionId) {
    return badRequest("playback_session_id is required");
  }

  const auth = await authenticateConnector({
    env,
    connectorId,
    connectorSecret,
    tenantId,
    homeId,
  });
  if (!auth.ok) {
    return json({ error: auth.error }, auth.status);
  }

  try {
    const status = await getPlaybackStartStatusFromSession(env, tenantId, homeId, playbackSessionId);
    console.info(
      JSON.stringify({
        event: "playback_start_status_checked",
        request_id: requestId,
        connector_id: connectorId,
        tenant_id: tenantId,
        home_id: homeId,
        playback_session_id: playbackSessionId,
        stream_fetch_started: status.stream_fetch_started,
        playback_started: status.playback_started,
        playback_failed: status.playback_failed,
        play_request_id: status.play_request_id ?? "",
        known_session: status.known_session,
        last_event_type: status.last_event_type ?? "",
        age_ms: status.age_ms ?? null,
      }),
    );
    return json({
      ok: true,
      playback_session_id: playbackSessionId,
      stream_fetch_started: status.stream_fetch_started,
      playback_started: status.playback_started,
      playback_failed: status.playback_failed,
      play_request_id: status.play_request_id,
      known_session: status.known_session,
      created_at_iso: status.created_at_iso,
      fetched_at_iso: status.fetched_at_iso,
      playback_started_at_iso: status.playback_started_at_iso,
      playback_failed_at_iso: status.playback_failed_at_iso,
      playback_failed_error: status.playback_failed_error,
      last_event_type: status.last_event_type,
      age_ms: status.age_ms,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.warn(
      JSON.stringify({
        event: "playback_start_status_failed",
        request_id: requestId,
        connector_id: connectorId,
        tenant_id: tenantId,
        home_id: homeId,
        playback_session_id: playbackSessionId,
        error: message,
      }),
    );
    return json({ error: "playback-start-status-unavailable" }, 502);
  }
}
