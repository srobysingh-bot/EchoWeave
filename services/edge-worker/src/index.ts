import { handleAlexaWebhookWithContext } from "./alexa";
import { handleAdminRequest } from "./admin";
import { handleConnectorRegister, handleConnectorWebSocket } from "./connectors";
import { HomeSession } from "./durable_objects/HomeSession";
import { handleStreamRequestWithContext } from "./stream";
import { Env } from "./types";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type RateEntry = { count: number; resetAt: number };
const rateWindowMs = 60_000;
const rateState = new Map<string, RateEntry>();

function getClientIdentifier(request: Request): string {
  const cfIp = request.headers.get("cf-connecting-ip")?.trim();
  if (cfIp) return cfIp;
  const xff = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (xff) return xff;
  return "unknown";
}

function parseLimit(value: string | undefined, fallback: number): number {
  const parsed = Number(value ?? "");
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.floor(parsed);
}

function checkRateLimit(bucket: string, key: string, maxPerMinute: number): { limited: boolean; retryAfter: number } {
  const now = Date.now();
  const mapKey = `${bucket}:${key}`;
  const existing = rateState.get(mapKey);
  if (!existing || existing.resetAt <= now) {
    rateState.set(mapKey, { count: 1, resetAt: now + rateWindowMs });
    return { limited: false, retryAfter: 0 };
  }

  if (existing.count >= maxPerMinute) {
    return { limited: true, retryAfter: Math.max(1, Math.ceil((existing.resetAt - now) / 1000)) };
  }

  existing.count += 1;
  rateState.set(mapKey, existing);
  return { limited: false, retryAfter: 0 };
}

function cleanupRateState(): void {
  const now = Date.now();
  for (const [key, entry] of rateState.entries()) {
    if (entry.resetAt <= now) rateState.delete(key);
  }
}

function withCors(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET,POST,OPTIONS");
  headers.set(
    "access-control-allow-headers",
    "content-type,authorization,signature,signaturecertchainurl,x-connector-bootstrap-secret",
  );
  return new Response(response.body, { status: response.status, headers });
}

export { HomeSession };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    cleanupRateState();
    const requestId = request.headers.get("x-request-id")?.trim() || crypto.randomUUID();
    const clientId = getClientIdentifier(request);

    const logBase = {
      request_id: requestId,
      method: request.method,
      path: new URL(request.url).pathname,
      client_id: clientId,
    };

    if (request.method === "OPTIONS") {
      const response = withCors(new Response(null, { status: 204 }));
      response.headers.set("x-request-id", requestId);
      return response;
    }

    const url = new URL(request.url);
    const pathname = url.pathname;

    try {
      if (pathname === "/healthz") {
        let d1Reachable = false;
        try {
          const probe = await env.ECHOWEAVE_DB.prepare("SELECT 1 as ok").first<{ ok: number }>();
          d1Reachable = probe?.ok === 1;
        } catch {
          d1Reachable = false;
        }

        const payload = {
          status: "ok",
          service: "edge-worker",
          request_id: requestId,
          build_id: env.BUILD_ID ?? "unknown",
          d1_reachable: d1Reachable,
        };
        const response = withCors(json(payload));
        response.headers.set("x-request-id", requestId);
        return response;
      }

      if (pathname === "/v1/alexa") {
        const limit = parseLimit(env.RATE_LIMIT_ALEXA_PER_MINUTE, 60);
        const limited = checkRateLimit("alexa", clientId, limit);
        if (limited.limited) {
          console.warn(JSON.stringify({ event: "alexa_request_rejected", ...logBase, reason: "rate_limited" }));
          const resp = withCors(json({ error: "rate-limited", request_id: requestId, retry_after: limited.retryAfter }, 429));
          resp.headers.set("retry-after", String(limited.retryAfter));
          resp.headers.set("x-request-id", requestId);
          return resp;
        }
        console.info(JSON.stringify({ event: "alexa_request_received", ...logBase }));
        const resp = withCors(await handleAlexaWebhookWithContext(request, env, requestId));
        resp.headers.set("x-request-id", requestId);
        return resp;
      }

      if (pathname.startsWith("/v1/admin/")) {
        const limit = parseLimit(env.RATE_LIMIT_ADMIN_PER_MINUTE, 30);
        const limited = checkRateLimit("admin", clientId, limit);
        if (limited.limited) {
          const resp = withCors(json({ error: "rate-limited", request_id: requestId, retry_after: limited.retryAfter }, 429));
          resp.headers.set("retry-after", String(limited.retryAfter));
          resp.headers.set("x-request-id", requestId);
          return resp;
        }
        const adminResp = await handleAdminRequest(request, env, pathname, requestId);
        if (adminResp) {
          const resp = withCors(adminResp);
          resp.headers.set("x-request-id", requestId);
          return resp;
        }
      }

      if (pathname === "/v1/connectors/register") {
        const limit = parseLimit(env.RATE_LIMIT_CONNECTOR_REGISTER_PER_MINUTE, 60);
        const connectorId = clientId;
        const limited = checkRateLimit("connector-register", connectorId, limit);
        if (limited.limited) {
          const resp = withCors(json({ error: "rate-limited", request_id: requestId, retry_after: limited.retryAfter }, 429));
          resp.headers.set("retry-after", String(limited.retryAfter));
          resp.headers.set("x-request-id", requestId);
          return resp;
        }
        const resp = withCors(await handleConnectorRegister(request, env));
        resp.headers.set("x-request-id", requestId);
        return resp;
      }

      if (pathname === "/v1/connectors/ws") {
        const wsResponse = await handleConnectorWebSocket(request, env);
        // Do not clone websocket upgrade responses (status 101); cloning drops
        // upgrade internals and can throw in Response constructor validation.
        if (wsResponse.status === 101) {
          return wsResponse;
        }
        const resp = withCors(wsResponse);
        resp.headers.set("x-request-id", requestId);
        return resp;
      }

      if (pathname.startsWith("/v1/stream/")) {
        const token = decodeURIComponent(pathname.replace("/v1/stream/", ""));
        const resp = withCors(await handleStreamRequestWithContext(request, env, token, requestId));
        resp.headers.set("x-request-id", requestId);
        return resp;
      }

      const resp = withCors(json({ error: "not-found", request_id: requestId }, 404));
      resp.headers.set("x-request-id", requestId);
      return resp;
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal-error";
      const resp = withCors(json({ error: message, request_id: requestId }, 500));
      resp.headers.set("x-request-id", requestId);
      return resp;
    }
  },
};
