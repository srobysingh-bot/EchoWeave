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

function validateEnvelope(envelope: AlexaRequestEnvelope): string | null {
  if (!envelope || typeof envelope !== "object") return "invalid-json";
  if (!envelope.version || !envelope.request?.type) return "invalid-envelope";
  if (!envelope.request.timestamp || !validateAlexaTimestamp(envelope.request.timestamp)) {
    return "stale-or-missing-timestamp";
  }
  return null;
}

async function validateAlexaSignature(request: Request, env: Env): Promise<boolean> {
  const enforce = (env.ALEXA_SIGNATURE_ENFORCE ?? "true").toLowerCase() === "true";
  if (!enforce) return true;

  const certChainUrl = request.headers.get("SignatureCertChainUrl") ?? "";
  const signature = request.headers.get("Signature") ?? "";
  if (!certChainUrl || !signature) {
    console.warn(JSON.stringify({ event: "alexa_signature_rejected", reason: "missing_signature_headers" }));
    return false;
  }

  const rawBody = await request.clone().arrayBuffer();
  const verified = await verifyAlexaRequestSignature(certChainUrl, signature, rawBody);
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
  if (request.method !== "POST") return json({ error: "method-not-allowed" }, 405);

  if (!(await validateAlexaSignature(request, env))) {
    console.warn(JSON.stringify({ event: "alexa_request_rejected", request_id: requestId, reason: "signature_validation_failed" }));
    return json(buildAlexaSpeechResponse("Request signature validation failed."), 401);
  }

  const envelope = (await request.clone().json()) as AlexaRequestEnvelope;
  const invalidReason = validateEnvelope(envelope);
  if (invalidReason) {
    console.warn(JSON.stringify({ event: "alexa_request_rejected", request_id: requestId, reason: invalidReason }));
    return json({ error: invalidReason }, 400);
  }

  const requestType = envelope.request?.type ?? "";
  if (requestType === "LaunchRequest") {
    return json(buildAlexaSpeechResponse("Welcome to EchoWeave. Say play to start."));
  }

  if (requestType !== "IntentRequest") {
    return json({ version: "1.0", response: {} });
  }

  const intentName = envelope.request?.intent?.name ?? "";
  if (!["PlayIntent", "PlayAudio", "AMAZON.ResumeIntent"].includes(intentName)) {
    return json(buildAlexaSpeechResponse("That command is not available yet."));
  }

  const alexaUserId = extractAlexaUserId(envelope);
  if (!alexaUserId) return json({ error: "missing-user-id" }, 400);

  const home = await resolveHomeByAlexaUser(env.ECHOWEAVE_DB, alexaUserId);
  if (!home) {
    console.warn(JSON.stringify({ event: "home_resolution_failed", request_id: requestId, alexa_user_id_present: true }));
    return json(buildAlexaSpeechResponse("Your account is not linked to a home yet."), 404);
  }

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
      },
      timeout_ms: 8000,
    }),
  });

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
    return json(buildAlexaSpeechResponse("Your home connector is offline. Please try again."), 503);
  }

  const prepared = (await doResp.json()) as PreparedPlayContext;
  if (!prepared.queue_id || !prepared.queue_item_id || !prepared.origin_stream_path) {
    return json(buildAlexaSpeechResponse("Could not resolve a playable item."), 502);
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
  return json(buildAlexaAudioPlayResponse(streamUrl, prepared.queue_item_id, `Playing ${prepared.title}`));
}
