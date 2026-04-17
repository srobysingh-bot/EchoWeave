import {
  issueSignedStreamToken,
  validateAlexaTimestamp,
  verifyAlexaRequestSignature,
} from "./security";
import {
  createPlaybackSession,
  getPlaybackSessionForStreamToken,
  recordStreamToken,
  resolveHomeByAlexaUser,
} from "./db";
import { AlexaRequestEnvelope, Env, PreparedPlayContext, StreamTokenClaims } from "./types";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function extractAlexaUserId(envelope: AlexaRequestEnvelope): string {
  return (
    envelope.session?.user?.userId ||
    envelope.context?.System?.user?.userId ||
    ""
  );
}

function truncateIdentifier(value: string, head = 20, tail = 6): string {
  if (!value) return "";
  if (value.length <= head + tail + 3) return value;
  return `${value.slice(0, head)}...${value.slice(-tail)}`;
}

function normalizeIntentQuery(rawQuery: string): string {
  return rawQuery
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/^(songs?|music)\s+by\s+/, "")
    .trim();
}

function extractIntentQuery(envelope: AlexaRequestEnvelope): string {
  const slots = envelope.request?.intent?.slots;
  if (!slots || typeof slots !== "object") return "";

  const readSlotValue = (slot: unknown): string => {
    if (!slot || typeof slot !== "object") return "";
    const record = slot as Record<string, unknown>;

    const direct = record.value;
    if (typeof direct === "string" && direct.trim()) return direct;

    const slotValue = record.slotValue;
    if (slotValue && typeof slotValue === "object") {
      const nested = (slotValue as Record<string, unknown>).value;
      if (typeof nested === "string" && nested.trim()) return nested;
    }

    const resolutions = record.resolutions;
    if (resolutions && typeof resolutions === "object") {
      const perAuthority = (resolutions as Record<string, unknown>).resolutionsPerAuthority;
      if (Array.isArray(perAuthority)) {
        for (const authority of perAuthority) {
          if (!authority || typeof authority !== "object") continue;
          const values = (authority as Record<string, unknown>).values;
          if (!Array.isArray(values)) continue;
          for (const item of values) {
            if (!item || typeof item !== "object") continue;
            const valueObj = (item as Record<string, unknown>).value;
            if (!valueObj || typeof valueObj !== "object") continue;
            const name = (valueObj as Record<string, unknown>).name;
            if (typeof name === "string" && name.trim()) return name;
          }
        }
      }
    }

    return "";
  };

  const named = (slots as Record<string, unknown>).query;
  const namedValue = readSlotValue(named);
  if (namedValue) return namedValue;

  for (const slot of Object.values(slots)) {
    const value = readSlotValue(slot);
    if (value) return value;
  }
  return "";
}

function validateEnvelope(envelope: AlexaRequestEnvelope): string | null {
  if (!envelope || typeof envelope !== "object") return "invalid-json";
  if (!envelope.version || !envelope.request?.type) return "invalid-envelope";
  const reqTs = envelope.request.timestamp;
  if (!reqTs) return "stale-or-missing-timestamp";
  const tsValid = validateAlexaTimestamp(reqTs);
  console.info(JSON.stringify({ event: "alexa_timestamp_validation", timestamp: reqTs, is_valid: tsValid }));
  if (!tsValid) {
    return "stale-or-missing-timestamp";
  }
  return null;
}

async function validateAlexaSignature(request: Request, env: Env): Promise<boolean> {
  const enforce = (env.ALEXA_SIGNATURE_ENFORCE ?? "true").toLowerCase() === "true";
  
  const certChainUrl = request.headers.get("SignatureCertChainUrl") ?? "";
  const signature = request.headers.get("Signature") ?? "";
  
  console.info(JSON.stringify({ 
    event: "alexa_signature_headers_check", 
    has_cert_chain_url: !!certChainUrl, 
    has_signature: !!signature,
    enforce_mode: enforce
  }));

  if (!enforce) return true;

  if (!certChainUrl || !signature) {
    console.warn(JSON.stringify({ event: "alexa_signature_rejected", reason: "missing_signature_headers" }));
    return false;
  }

  const rawBody = await request.clone().arrayBuffer();
  const verified = await verifyAlexaRequestSignature(certChainUrl, signature, rawBody);
  
  console.info(JSON.stringify({ 
    event: "alexa_signature_crypto_result", 
    ok: verified.ok, 
    reason: verified.reason 
  }));

  if (!verified.ok) {
    console.warn(JSON.stringify({ event: "alexa_signature_rejected", reason: verified.reason ?? "unknown" }));
    return false;
  }

  return true;
}

function buildAlexaAudioPlayResponse(streamUrl: string, token: string): Record<string, unknown> {
  return {
    version: "1.0",
    response: {
      shouldEndSession: true,
      directives: [
        {
          type: "AudioPlayer.Play",
          playBehavior: "REPLACE_ALL",
          audioItem: {
            stream: {
              url: streamUrl,
              token,
              offsetInMilliseconds: 0,
            },
          },
        },
      ],
    },
  };
}

function buildAlexaSpeechResponse(text: string, shouldEndSession = true): Record<string, unknown> {
  return {
    version: "1.0",
    response: {
      outputSpeech: { type: "PlainText", text },
      shouldEndSession,
    },
  };
}

function summarizeStreamUrl(streamUrl: string): { host: string; path: string } {
  try {
    const parsed = new URL(streamUrl);
    return { host: parsed.host, path: parsed.pathname };
  } catch {
    return { host: "", path: "" };
  }
}

function shouldEndSessionFromPayload(payload: Record<string, unknown>): boolean | null {
  const response = payload.response;
  if (!response || typeof response !== "object") return null;
  const value = (response as Record<string, unknown>).shouldEndSession;
  if (typeof value === "boolean") return value;
  return null;
}

function extractAudioPlayerPlaySummary(payload: Record<string, unknown>): {
  play_behavior: string;
  audio_item_token: string;
} {
  const response = payload.response;
  if (!response || typeof response !== "object") {
    return { play_behavior: "", audio_item_token: "" };
  }

  const directives = (response as Record<string, unknown>).directives;
  if (!Array.isArray(directives)) {
    return { play_behavior: "", audio_item_token: "" };
  }

  const playDirective = directives.find((d) => {
    if (!d || typeof d !== "object") return false;
    return (d as Record<string, unknown>).type === "AudioPlayer.Play";
  }) as Record<string, unknown> | undefined;

  if (!playDirective) {
    return { play_behavior: "", audio_item_token: "" };
  }

  const playBehavior = String(playDirective.playBehavior ?? "");
  const audioItem = playDirective.audioItem;
  let token = "";
  if (audioItem && typeof audioItem === "object") {
    const stream = (audioItem as Record<string, unknown>).stream;
    if (stream && typeof stream === "object") {
      token = String((stream as Record<string, unknown>).token ?? "");
    }
  }

  return {
    play_behavior: playBehavior,
    audio_item_token: token,
  };
}

function hasAudioPlayerDirective(payload: Record<string, unknown>): boolean {
  const response = payload.response;
  if (!response || typeof response !== "object") return false;
  const directives = (response as Record<string, unknown>).directives;
  if (!Array.isArray(directives)) return false;
  return directives.some((d) => {
    if (!d || typeof d !== "object") return false;
    return (d as Record<string, unknown>).type === "AudioPlayer.Play";
  });
}

function validateAlexaPlayResponseContract(payload: Record<string, unknown>): {
  has_audio_player_play: boolean;
  should_end_session: boolean | null;
  directive_behavior: string;
  audio_item_token: string;
  has_output_speech: boolean;
  has_reprompt: boolean;
  has_response_wrapper: boolean;
  has_directives_array: boolean;
  has_stream_url: boolean;
  invalid_reasons: string[];
} {
  const response = payload.response;
  const hasResponseWrapper = !!(response && typeof response === "object");
  const responseNode = hasResponseWrapper ? (response as Record<string, unknown>) : {};
  const directives = responseNode.directives;
  const hasDirectivesArray = Array.isArray(directives);
  const shouldEndSession = shouldEndSessionFromPayload(payload);
  const playSummary = extractAudioPlayerPlaySummary(payload);
  const hasAudioPlayerPlay = hasAudioPlayerDirective(payload);
  const hasOutputSpeech = !!responseNode.outputSpeech;
  const hasReprompt = !!responseNode.reprompt;

  let hasStreamUrl = false;
  if (Array.isArray(directives)) {
    const playDirective = directives.find((d) => {
      if (!d || typeof d !== "object") return false;
      return (d as Record<string, unknown>).type === "AudioPlayer.Play";
    }) as Record<string, unknown> | undefined;
    const audioItem = playDirective?.audioItem;
    const stream =
      audioItem && typeof audioItem === "object"
        ? (audioItem as Record<string, unknown>).stream
        : null;
    const url =
      stream && typeof stream === "object"
        ? String((stream as Record<string, unknown>).url ?? "")
        : "";
    hasStreamUrl = !!url;
  }

  const invalidReasons: string[] = [];
  if (!hasResponseWrapper) invalidReasons.push("missing_response_wrapper");
  if (!hasDirectivesArray) invalidReasons.push("missing_directives_array");
  if (!hasAudioPlayerPlay) invalidReasons.push("missing_audio_player_play");
  if (shouldEndSession !== true) invalidReasons.push("should_end_session_not_true");
  if (hasOutputSpeech) invalidReasons.push("output_speech_conflicts_with_audio_player_play");
  if (hasReprompt) invalidReasons.push("reprompt_conflicts_with_audio_player_play");
  if (!playSummary.play_behavior) invalidReasons.push("missing_play_behavior");
  if (!playSummary.audio_item_token) invalidReasons.push("missing_audio_item_token");
  if (!hasStreamUrl) invalidReasons.push("missing_stream_url");

  return {
    has_audio_player_play: hasAudioPlayerPlay,
    should_end_session: shouldEndSession,
    directive_behavior: playSummary.play_behavior,
    audio_item_token: playSummary.audio_item_token,
    has_output_speech: hasOutputSpeech,
    has_reprompt: hasReprompt,
    has_response_wrapper: hasResponseWrapper,
    has_directives_array: hasDirectivesArray,
    has_stream_url: hasStreamUrl,
    invalid_reasons: invalidReasons,
  };
}

function isQueueUnavailableError(message: string): boolean {
  const normalized = message.toLowerCase();
  return (
    normalized.includes("queue_empty") ||
    normalized.includes("no_resolved_queue_id") ||
    normalized.includes("no active queue available") ||
    normalized.includes("no playable queue item available") ||
    normalized.includes("active speaker queue") ||
    normalized.includes("queue unavailable")
  );
}

function buildTextResponse(text: string): Record<string, unknown> {
  return buildAlexaSpeechResponse(text);
}

export async function handleAlexaWebhook(request: Request, env: Env): Promise<Response> {
  return handleAlexaWebhookWithContext(request, env, request.headers.get("x-request-id") ?? crypto.randomUUID());
}

export async function handleAlexaWebhookWithContext(request: Request, env: Env, requestId: string): Promise<Response> {
  // Log 1: Handler entry — proves request entered the Alexa handler
  console.info(JSON.stringify({ event: "alexa_handler_entry", request_id: requestId, method: request.method }));

  if (request.method !== "POST") {
    console.warn(JSON.stringify({ event: "alexa_handler_rejected", request_id: requestId, reason: "method-not-allowed", method: request.method }));
    return json({ error: "method-not-allowed" }, 405);
  }

  // Log 2: Signature verification
  const sigValid = await validateAlexaSignature(request, env);
  console.info(JSON.stringify({ event: "alexa_signature_result", request_id: requestId, passed: sigValid }));

  if (!sigValid) {
    console.warn(JSON.stringify({ event: "alexa_request_rejected", request_id: requestId, reason: "signature_validation_failed" }));
    return json(buildAlexaSpeechResponse("Request signature validation failed."), 200);
  }

  // Log 3: Envelope parsing
  let envelope: AlexaRequestEnvelope;
  try {
    envelope = (await request.clone().json()) as AlexaRequestEnvelope;
  } catch {
    console.warn(JSON.stringify({ event: "alexa_request_rejected", request_id: requestId, reason: "invalid-json" }));
    return json(buildAlexaSpeechResponse("I could not process that request."), 200);
  }

  const invalidReason = validateEnvelope(envelope);
  if (invalidReason) {
    console.warn(JSON.stringify({ event: "alexa_request_rejected", request_id: requestId, reason: invalidReason }));
    return json(buildAlexaSpeechResponse("I could not process that request."), 200);
  }

  const requestType = envelope.request?.type ?? "";
  const intentName = envelope.request?.intent?.name ?? "";
  const rawQuery = extractIntentQuery(envelope);
  const normalizedQuery = normalizeIntentQuery(rawQuery);
  const requestLocale = String(envelope.request?.locale ?? "");
  const alexaUserId = extractAlexaUserId(envelope);
  const truncatedUserId = truncateIdentifier(alexaUserId);
  const sessionId = String(envelope.session?.sessionId ?? "");
  const sessionIsNew = envelope.session?.new;
  const applicationId = String(
    envelope.session?.application?.applicationId ||
      envelope.context?.System?.application?.applicationId ||
      "",
  );
  const truncatedApplicationId = truncateIdentifier(applicationId, 18, 8);
  const buildId = String(env.BUILD_ID ?? "");
  const deploySha = String(env.DEPLOY_SHA ?? "");

  // Log 4: Request type and intent
  console.info(JSON.stringify({ event: "alexa_envelope_parsed", request_id: requestId, request_type: requestType, intent_name: intentName || undefined }));
  if (sessionId && alexaUserId) {
    console.info(
      JSON.stringify({
        event: "alexa_skill_session_active",
        request_id: requestId,
        request_type: requestType,
        locale: requestLocale,
        session_id: sessionId,
        session_new: sessionIsNew,
        alexa_user_id_truncated: truncatedUserId,
        application_id_truncated: truncatedApplicationId,
        build_id: buildId,
        deploy_sha: deploySha,
      }),
    );
  } else {
    const missingReasons: string[] = [];
    if (!sessionId) missingReasons.push("missing_session_id");
    if (!alexaUserId) missingReasons.push("missing_alexa_user_id");
    console.warn(
      JSON.stringify({
        event: "alexa_skill_session_missing",
        request_id: requestId,
        request_type: requestType,
        locale: requestLocale,
        session_id: sessionId,
        session_new: sessionIsNew,
        alexa_user_id_present: !!alexaUserId,
        application_id_truncated: truncatedApplicationId,
        reason: missingReasons.join(",") || "missing_session_context",
        build_id: buildId,
        deploy_sha: deploySha,
      }),
    );
  }
  console.info(
    JSON.stringify({
      event: "alexa_intent_query",
      request_id: requestId,
      request_type: requestType,
      intent_name: intentName || undefined,
      raw_query: rawQuery,
      normalized_query: normalizedQuery,
    }),
  );
  if (
    requestType === "IntentRequest" &&
    ["PlayIntent", "PlayAudio"].includes(intentName) &&
    !rawQuery
  ) {
    const slots = envelope.request?.intent?.slots;
    const slotKeys = slots && typeof slots === "object" ? Object.keys(slots as Record<string, unknown>) : [];
    console.warn(
      JSON.stringify({
        event: "alexa_intent_slots_debug",
        request_id: requestId,
        intent_name: intentName,
        slot_keys: slotKeys,
        slots: slots ?? {},
      }),
    );
  }

  if (requestType === "LaunchRequest") {
    console.info(
      JSON.stringify({
        event: "alexa_skill_launch_request_received",
        request_id: requestId,
        locale: requestLocale,
        session_id: sessionId,
        session_new: sessionIsNew,
        alexa_user_id_truncated: truncatedUserId,
        application_id_truncated: truncatedApplicationId,
        build_id: buildId,
        deploy_sha: deploySha,
      }),
    );
    const payload = {
      version: "1.0",
      response: {
        outputSpeech: { type: "PlainText", text: "Welcome to EchoWeave. Say play to start." },
        reprompt: {
          outputSpeech: { type: "PlainText", text: "What do you want to hear?" },
        },
        shouldEndSession: false,
      },
    };
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, request_type: "LaunchRequest", response_status: 200, speech: "Welcome to EchoWeave. Say play to start.", has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
    return json(payload);
  }

  if (requestType.startsWith("AudioPlayer.")) {
    const requestNode = envelope.request ?? {};
    const token = String((requestNode as Record<string, unknown>).token ?? "");
    let resolvedPlaybackSessionId = "";
    let resolvedTenantId = "";
    let resolvedHomeId = "";
    let resolvedPlayRequestId = "";

    if (token) {
      const linked = await getPlaybackSessionForStreamToken(env.ECHOWEAVE_DB, token);
      if (linked) {
        resolvedPlaybackSessionId = linked.playback_session_id;
        resolvedTenantId = linked.tenant_id;
        resolvedHomeId = linked.home_id;
        try {
          const doId = env.HOME_SESSION.idFromName(`${linked.tenant_id}:${linked.home_id}`);
          const stub = env.HOME_SESSION.get(doId);
          const markResp = await stub.fetch("https://home-session/playback-start", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              action: "mark_playback_event",
              playback_session_id: linked.playback_session_id,
              event_type: requestType,
              request_id: requestId,
              error: (requestNode as Record<string, unknown>).error ?? null,
            }),
          });
          if (markResp.ok) {
            const markBody = (await markResp.json()) as { play_request_id?: string };
            resolvedPlayRequestId = String(markBody.play_request_id ?? "");
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : "unknown";
          console.warn(
            JSON.stringify({
              event: "alexa_audio_player_event_mark_failed",
              request_id: requestId,
              token,
              playback_session_id: linked.playback_session_id,
              event_type: requestType,
              error: message,
            }),
          );
        }
      }
    }

    if (requestType === "AudioPlayer.PlaybackStarted") {
      console.info(
        JSON.stringify({
          event: "alexa_audio_player_playback_started",
          request_id: requestId,
          play_request_id: resolvedPlayRequestId,
          tenant_id: resolvedTenantId,
          home_id: resolvedHomeId,
          playback_session_id: resolvedPlaybackSessionId,
          token,
          offset_ms: (requestNode as Record<string, unknown>).offsetInMilliseconds ?? 0,
        }),
      );
    } else if (requestType === "AudioPlayer.PlaybackFailed") {
      const error = (requestNode as Record<string, unknown>).error;
      console.warn(
        JSON.stringify({
          event: "alexa_audio_player_playback_failed",
          request_id: requestId,
          play_request_id: resolvedPlayRequestId,
          tenant_id: resolvedTenantId,
          home_id: resolvedHomeId,
          playback_session_id: resolvedPlaybackSessionId,
          token,
          error,
        }),
      );
    }

    const payload = { version: "1.0", response: {} };
    console.info(
      JSON.stringify({
        event: "alexa_response_sent",
        request_id: requestId,
        request_type: requestType,
        response_status: 200,
        speech: "empty-response",
        has_audio_player_play: false,
      }),
    );
    return json(payload);
  }

  if (requestType !== "IntentRequest") {
    const payload = { version: "1.0", response: {} };
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, request_type: requestType, response_status: 200, speech: "empty-response", has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
    return json(payload);
  }

  if (!["PlayIntent", "PlayAudio", "AMAZON.ResumeIntent"].includes(intentName)) {
    const payload = buildAlexaSpeechResponse("That command is not available yet.");
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, request_type: "IntentRequest", intent_name: intentName, response_status: 200, speech: "That command is not available yet.", has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
    return json(payload);
  }

  // Log 5: Alexa user ID extraction
  console.info(JSON.stringify({ event: "alexa_user_resolved", request_id: requestId, alexa_user_id_present: !!alexaUserId, alexa_user_id_truncated: truncatedUserId }));

  if (!alexaUserId) {
    console.warn(JSON.stringify({ event: "alexa_request_rejected", request_id: requestId, reason: "missing-user-id" }));
    return json(buildAlexaSpeechResponse("Your account is not linked to a home yet."), 200);
  }

  // Log 6: Home lookup
  const home = await resolveHomeByAlexaUser(env.ECHOWEAVE_DB, alexaUserId);
  console.info(JSON.stringify({
    event: "alexa_home_lookup",
    request_id: requestId,
    found: !!home,
    tenant_id: home?.tenant_id ?? "",
    home_id: home?.home_id ?? "",
  }));

  if (!home) {
    console.warn(JSON.stringify({ event: "alexa_home_resolution_failed", request_id: requestId, alexa_user_id: alexaUserId }));
    try {
      await env.ECHOWEAVE_DB.prepare("INSERT OR REPLACE INTO recent_alexa_users (alexa_user_id) VALUES (?)").bind(alexaUserId).run();
    } catch {}
    return json(buildAlexaSpeechResponse("Your account is not linked to a home yet."), 200);
  }

  // Ensure the Alexa user has an alexa_accounts entry so that downstream
  // foreign-key references (playback_sessions.alexa_user_id) do not fail.
  // This handles the case where resolveHomeByAlexaUser used the
  // sole-active-home fallback and the user ID is not yet in alexa_accounts.
  try {
    // alexa_accounts.user_id → users.id FK: ensure a users row exists first.
    await env.ECHOWEAVE_DB.prepare(
      `INSERT OR IGNORE INTO users (id, tenant_id) VALUES (?, ?)`
    ).bind(alexaUserId, home.tenant_id).run();
    await env.ECHOWEAVE_DB.prepare(
      `INSERT OR IGNORE INTO alexa_accounts (alexa_user_id, user_id, tenant_id, home_id)
       VALUES (?, ?, ?, ?)`
    ).bind(alexaUserId, alexaUserId, home.tenant_id, home.home_id).run();
  } catch (linkErr) {
    console.warn(JSON.stringify({
      event: "alexa_auto_link_failed",
      request_id: requestId,
      alexa_user_id: alexaUserId,
      tenant_id: home.tenant_id,
      home_id: home.home_id,
      error: linkErr instanceof Error ? linkErr.message : "unknown",
    }));
  }

  // Log 7: DO command dispatch
  console.info(JSON.stringify({
    event: "alexa_do_dispatch",
    request_id: requestId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    command_type: "prepare_play",
    intent_name: intentName,
    queue_id: home.alexa_source_queue_id ?? "",
  }));

  const doId = env.HOME_SESSION.idFromName(`${home.tenant_id}:${home.home_id}`);
  const sessionStub = env.HOME_SESSION.get(doId);
  const doResp = await sessionStub.fetch("https://home-session/command", {
    method: "POST",
    headers: { "content-type": "application/json", "x-request-id": requestId },
    body: JSON.stringify({
      command_type: "prepare_play",
      payload: {
        request_id: requestId,
        tenant_id: home.tenant_id,
        home_id: home.home_id,
        queue_id: home.alexa_source_queue_id ?? undefined,
        intent_name: intentName,
        query: rawQuery || undefined,
      },
      timeout_ms: 8000,
    }),
  });

  // Log 8: DO response
  console.info(JSON.stringify({ event: "alexa_do_result", request_id: requestId, do_status: doResp.status, do_ok: doResp.ok }));

  if (!doResp.ok) {
    let doErrorText = "";
    try {
      doErrorText = await doResp.clone().text();
      const errorPayload = (JSON.parse(doErrorText) as { error?: unknown }) ?? {};
      const rawError = typeof errorPayload.error === "string" ? errorPayload.error : JSON.stringify(errorPayload.error ?? "");
      let parsedConnectorError = rawError;
      try {
        const nested = JSON.parse(rawError) as { code?: string; message?: string };
        parsedConnectorError = String(nested.code ?? nested.message ?? rawError);
      } catch {
        // keep raw connector error text
      }
      const connectorErrorBlob = [doErrorText, rawError, parsedConnectorError].filter(Boolean).join("\n");
      console.warn(
        JSON.stringify({
          event: "connector_dispatch_failed",
          request_id: requestId,
          tenant_id: home.tenant_id,
          home_id: home.home_id,
          do_status: doResp.status,
          do_error_body: doErrorText,
          do_error: errorPayload.error ?? "",
        }),
      );
      if (parsedConnectorError.includes("play_start_failed")) {
        const speech = "I found the track, but playback could not be started.";
        const payload = buildTextResponse(speech);
        console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech, has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
        return json(payload, 200);
      }
      if (parsedConnectorError.includes("query_no_match")) {
        const speech = "I could not find a playable result for that request.";
        const payload = buildTextResponse(speech);
        console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech, has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
        return json(payload, 200);
      }
      if (isQueueUnavailableError(connectorErrorBlob)) {
        const speech = "I could not find an active speaker queue in Music Assistant to play this on.";
        const payload = buildTextResponse(speech);
        console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech, has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
        return json(payload, 200);
      }
      if (connectorErrorBlob.includes("timeout")) {
        console.warn(JSON.stringify({ event: "connector_dispatch_timeout", request_id: requestId, tenant_id: home.tenant_id, home_id: home.home_id }));
      }
    } catch {
      if (isQueueUnavailableError(doErrorText)) {
        const speech = "I could not find an active speaker queue in Music Assistant to play this on.";
        const payload = buildTextResponse(speech);
        console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech, has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
        return json(payload, 200);
      }
      console.warn(
        JSON.stringify({
          event: "connector_dispatch_failed",
          request_id: requestId,
          tenant_id: home.tenant_id,
          home_id: home.home_id,
          do_status: doResp.status,
          do_error_body: doErrorText,
          parse_error: "failed-to-parse-do-error-body",
        }),
      );
    }
    const payload = buildAlexaSpeechResponse("Your home connector is offline. Please try again.");
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech: "Your home connector is offline. Please try again.", has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
    return json(payload, 200);
  }

  const prepared = (await doResp.json()) as PreparedPlayContext;
  if (!prepared.queue_id || !prepared.queue_item_id || !prepared.origin_stream_path) {
    console.warn(JSON.stringify({ event: "alexa_prepared_play_incomplete", request_id: requestId, has_queue_id: !!prepared.queue_id, has_queue_item_id: !!prepared.queue_item_id, has_origin_stream_path: !!prepared.origin_stream_path }));
    const payload = buildAlexaSpeechResponse("Could not resolve a playable item.");
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech: "Could not resolve a playable item.", has_audio_player_play: hasAudioPlayerDirective(payload), response_payload: payload }));
    return json(payload, 200);
  }

  // Wrap token generation, D1 session/token writes, and response building
  // in a try/catch so that failures (e.g. foreign-key violations, D1 errors)
  // return a valid Alexa speech response instead of a raw 500 error which
  // Alexa cannot parse ("There was a problem with the requested skill's response").
  try {

  const nowSeconds = Math.floor(Date.now() / 1000);
  const ttl = Number(env.STREAM_TOKEN_TTL_SECONDS ?? "300");
  const playbackSessionId = crypto.randomUUID();
  const tokenId = crypto.randomUUID();
  const claims: StreamTokenClaims = {
    token_id: tokenId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    playback_session_id: playbackSessionId,
    queue_id: prepared.queue_id,
    queue_item_id: prepared.queue_item_id,
    origin_stream_path: prepared.origin_stream_path,
    client_profile: "alexa",
    play_request_id: requestId,
    exp: nowSeconds + ttl,
  };

  const streamToken = await issueSignedStreamToken(claims, env.STREAM_TOKEN_SIGNING_SECRET);
  const signature = streamToken.split(".")[1] ?? "";

  await createPlaybackSession(env.ECHOWEAVE_DB, {
    id: playbackSessionId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    alexa_user_id: alexaUserId,
    queue_id: prepared.queue_id,
    queue_item_id: prepared.queue_item_id,
    metadata_json: JSON.stringify({
      title: prepared.title,
      subtitle: prepared.subtitle ?? "",
      image_url: prepared.image_url ?? "",
    }),
  });

  console.info(JSON.stringify({
    event: "alexa_playback_session_created",
    request_id: requestId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    playback_session_id: playbackSessionId,
    queue_id: prepared.queue_id,
    queue_item_id: prepared.queue_item_id,
  }));

  await recordStreamToken(env.ECHOWEAVE_DB, {
    id: tokenId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    playback_session_id: playbackSessionId,
    token_signature: signature,
    expires_at_iso: new Date((nowSeconds + ttl) * 1000).toISOString(),
  });

  console.info(JSON.stringify({
    event: "alexa_stream_token_issued",
    request_id: requestId,
    token_id: tokenId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    playback_session_id: playbackSessionId,
    origin_stream_path: prepared.origin_stream_path,
  }));

  const streamUrl = `${new URL(request.url).origin}/v1/stream/${encodeURIComponent(streamToken)}`;
  const streamSummary = summarizeStreamUrl(streamUrl);

  // Build and validate the actual AudioPlayer.Play response contract.
  const payload = buildAlexaAudioPlayResponse(streamUrl, tokenId);
  const contract = validateAlexaPlayResponseContract(payload);
  console.info(
    JSON.stringify({
      event: "alexa_audio_player_play_response_built",
      request_id: requestId,
      play_request_id: requestId,
      playback_session_id: playbackSessionId,
      stream_token_id: tokenId,
      has_audio_player_play: contract.has_audio_player_play,
      should_end_session: contract.should_end_session,
      directive_behavior: contract.directive_behavior,
      audio_item_token: contract.audio_item_token,
      stream_url_host: streamSummary.host,
      stream_url_path: streamSummary.path,
      invalid_reasons: contract.invalid_reasons,
    }),
  );

  console.info(
    JSON.stringify({
      event: "alexa_audio_player_play_response_payload",
      request_id: requestId,
      play_request_id: requestId,
      playback_session_id: playbackSessionId,
      stream_token_id: tokenId,
      stream_url_host: streamSummary.host,
      stream_url_path: streamSummary.path,
    }),
  );

  if (contract.invalid_reasons.length > 0) {
    console.warn(
      JSON.stringify({
        event: "prototype_skill_play_response_invalid",
        request_id: requestId,
        play_request_id: requestId,
        playback_session_id: playbackSessionId,
        stream_token_id: tokenId,
        has_audio_player_play: contract.has_audio_player_play,
        should_end_session: contract.should_end_session,
        directive_behavior: contract.directive_behavior,
        audio_item_token: contract.audio_item_token,
        invalid_reasons: contract.invalid_reasons,
      }),
    );
    const invalidPayload = buildAlexaSpeechResponse("Playback response invalid.");
    return json(invalidPayload, 200);
  }

  // Log 9: Final success response
  console.info(
    JSON.stringify({
      event: "alexa_audio_player_play_response_sent",
      request_id: requestId,
      play_request_id: requestId,
      playback_session_id: playbackSessionId,
      stream_token_id: tokenId,
      has_audio_player_play: contract.has_audio_player_play,
      should_end_session: contract.should_end_session,
      directive_behavior: contract.directive_behavior,
      audio_item_token: contract.audio_item_token,
      stream_url_host: streamSummary.host,
      stream_url_path: streamSummary.path,
    }),
  );
  console.info(JSON.stringify({
    event: "alexa_response_sent",
    request_id: requestId,
    response_status: 200,
    response_type: "AudioPlayer.Play",
    title: prepared.title,
    playback_session_id: playbackSessionId,
    stream_token_id: tokenId,
    stream_url_host: streamSummary.host,
    stream_url_path: streamSummary.path,
    origin_stream_path: prepared.origin_stream_path,
    has_audio_player_play: hasAudioPlayerDirective(payload),
  }));

  return json(payload);
  } catch (sessionError) {
    const errorMessage = sessionError instanceof Error ? sessionError.message : "unknown";
    console.warn(JSON.stringify({
      event: "alexa_play_session_creation_failed",
      request_id: requestId,
      tenant_id: home.tenant_id,
      home_id: home.home_id,
      queue_id: prepared.queue_id,
      queue_item_id: prepared.queue_item_id,
      error: errorMessage,
    }));
    const fallbackPayload = buildAlexaSpeechResponse("I found the track but could not start playback. Please try again.");
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech: "session-creation-failed", has_audio_player_play: false }));
    return json(fallbackPayload, 200);
  }
}

