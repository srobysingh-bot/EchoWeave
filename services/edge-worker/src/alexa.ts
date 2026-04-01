import {
  issueSignedStreamToken,
  validateAlexaTimestamp,
  verifyAlexaRequestSignature,
} from "./security";
import { createPlaybackSession, recordStreamToken, resolveHomeByAlexaUser } from "./db";
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

  const named = (slots as Record<string, unknown>).query;
  if (named && typeof named === "object") {
    const value = (named as { value?: unknown }).value;
    if (typeof value === "string") return value;
  }

  for (const slot of Object.values(slots)) {
    if (!slot || typeof slot !== "object") continue;
    const value = (slot as { value?: unknown }).value;
    if (typeof value === "string" && value.trim()) return value;
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

function buildAlexaAudioPlayResponse(streamUrl: string, token: string, speech?: string): Record<string, unknown> {
  return {
    version: "1.0",
    response: {
      ...(speech ? { outputSpeech: { type: "PlainText", text: speech } } : {}),
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

function buildAlexaSpeechResponse(text: string): Record<string, unknown> {
  return {
    version: "1.0",
    response: {
      outputSpeech: { type: "PlainText", text },
      shouldEndSession: true,
    },
  };
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

  // Log 4: Request type and intent
  console.info(JSON.stringify({ event: "alexa_envelope_parsed", request_id: requestId, request_type: requestType, intent_name: intentName || undefined }));
  console.info(
    JSON.stringify({
      event: "alexa_intent_query",
      request_id: requestId,
      intent_name: intentName || undefined,
      raw_query: rawQuery,
      normalized_query: normalizedQuery,
    }),
  );

  if (requestType === "LaunchRequest") {
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, request_type: "LaunchRequest", response_status: 200, speech: "Welcome to EchoWeave. Say play to start." }));
    return json(buildAlexaSpeechResponse("Welcome to EchoWeave. Say play to start."));
  }

  if (requestType !== "IntentRequest") {
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, request_type: requestType, response_status: 200, speech: "empty-response" }));
    return json({ version: "1.0", response: {} });
  }

  if (!["PlayIntent", "PlayAudio", "AMAZON.ResumeIntent"].includes(intentName)) {
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, request_type: "IntentRequest", intent_name: intentName, response_status: 200, speech: "That command is not available yet." }));
    return json(buildAlexaSpeechResponse("That command is not available yet."));
  }

  // Log 5: Alexa user ID extraction
  const alexaUserId = extractAlexaUserId(envelope);
  const truncatedUserId = alexaUserId ? `${alexaUserId.slice(0, 20)}...${alexaUserId.slice(-6)}` : "";
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
    console.warn(JSON.stringify({ event: "alexa_home_resolution_failed", request_id: requestId, alexa_user_id_truncated: truncatedUserId }));
    return json(buildAlexaSpeechResponse("Your account is not linked to a home yet."), 200);
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
      const errorPayload = (JSON.parse(doErrorText) as { error?: string }) ?? {};
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
      if ((errorPayload.error ?? "").includes("timeout")) {
        console.warn(JSON.stringify({ event: "connector_dispatch_timeout", request_id: requestId, tenant_id: home.tenant_id, home_id: home.home_id }));
      }
    } catch {
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
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech: "Your home connector is offline. Please try again." }));
    return json(buildAlexaSpeechResponse("Your home connector is offline. Please try again."), 200);
  }

  const prepared = (await doResp.json()) as PreparedPlayContext;
  if (!prepared.queue_id || !prepared.queue_item_id || !prepared.origin_stream_path) {
    console.warn(JSON.stringify({ event: "alexa_prepared_play_incomplete", request_id: requestId, has_queue_id: !!prepared.queue_id, has_queue_item_id: !!prepared.queue_item_id, has_origin_stream_path: !!prepared.origin_stream_path }));
    console.info(JSON.stringify({ event: "alexa_response_sent", request_id: requestId, response_status: 200, speech: "Could not resolve a playable item." }));
    return json(buildAlexaSpeechResponse("Could not resolve a playable item."), 200);
  }

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

  await recordStreamToken(env.ECHOWEAVE_DB, {
    id: tokenId,
    tenant_id: home.tenant_id,
    home_id: home.home_id,
    playback_session_id: playbackSessionId,
    token_signature: signature,
    expires_at_iso: new Date((nowSeconds + ttl) * 1000).toISOString(),
  });

  const streamUrl = `${new URL(request.url).origin}/v1/stream/${encodeURIComponent(streamToken)}`;

  // Log 9: Final success response
  console.info(JSON.stringify({
    event: "alexa_response_sent",
    request_id: requestId,
    response_status: 200,
    response_type: "AudioPlayer.Play",
    title: prepared.title,
    playback_session_id: playbackSessionId,
    stream_token_id: tokenId,
  }));

  return json(buildAlexaAudioPlayResponse(streamUrl, prepared.queue_item_id, `Playing ${prepared.title}`));
}

