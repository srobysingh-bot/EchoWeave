import { handleAlexaWebhookWithContext } from "./alexa";
import { handleAdminRequest } from "./admin";
import {
  handleConnectorPlaybackHandoff,
  handleConnectorPlaybackStartStatus,
  handleConnectorRegister,
  handleConnectorWebSocket,
} from "./connectors";
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
    const rawPathname = new URL(request.url).pathname;

    const logBase = {
      request_id: requestId,
      method: request.method,
      path: rawPathname,
      client_id: clientId,
    };

    // Catch-all request log: every request that reaches the Worker is logged.
    const headerNames: string[] = [];
    request.headers.forEach((_, key) => headerNames.push(key));
    console.info(JSON.stringify({ 
      event: "worker_request_received", 
      ...logBase, 
      user_agent: request.headers.get("user-agent") ?? "",
      header_names: headerNames
    }));

    if (request.method === "OPTIONS") {
      const response = withCors(new Response(null, { status: 204 }));
      response.headers.set("x-request-id", requestId);
      return response;
    }

    const url = new URL(request.url);
    // Normalize trailing slashes to prevent silent 404s
    const pathname = rawPathname.length > 1 && rawPathname.endsWith("/") ? rawPathname.slice(0, -1) : rawPathname;

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

      if (pathname === "/v1/admin/debug-info" && request.method === "GET") {
        const adminKey = (env.ADMIN_API_KEY ?? "").trim();
        const bearer = request.headers.get("authorization") ?? "";
        const suppliedToken = bearer.toLowerCase().startsWith("bearer ") ? bearer.slice(7).trim() : "";
        if (!adminKey || suppliedToken !== adminKey) {
          const resp = withCors(json({ error: "unauthorized", request_id: requestId }, 401));
          resp.headers.set("x-request-id", requestId);
          return resp;
        }
        const recentUser = await env.ECHOWEAVE_DB.prepare("SELECT * FROM recent_alexa_users ORDER BY last_seen DESC LIMIT 1").first<{ alexa_user_id: string }>();
        const alexaUserId = recentUser?.alexa_user_id ?? "No failed user ID logged recently.";
        
        let resolution = null;
        if (recentUser) {
          resolution = await env.ECHOWEAVE_DB.prepare(`
            SELECT aa.tenant_id, aa.home_id, h.origin_base_url, h.alexa_source_queue_id
            FROM alexa_accounts aa
            LEFT JOIN homes h ON h.id = aa.home_id
            WHERE aa.alexa_user_id = ?
          `).bind(alexaUserId).first();
        }

        const debugPayload = {
          full_alexa_user_id: alexaUserId,
          resolved_tenant_id: resolution?.tenant_id ?? null,
          resolved_home_id: resolution?.home_id ?? null,
          queue_id: resolution?.alexa_source_queue_id ?? null,
          origin_base_url_present: !!resolution?.origin_base_url,
        };
        return withCors(json(debugPayload, 200));
      }

      if (pathname === "/v1/alexa") {
        // GET /v1/alexa: human-readable endpoint check (paste URL in browser to verify)
        if (request.method === "GET") {
          const resp = withCors(new Response(
            "EchoWeave Alexa webhook is active at this URL. Use POST to send Alexa requests.\n" +
            `Request ID: ${requestId}\nTimestamp: ${new Date().toISOString()}\n`,
            { status: 200, headers: { "content-type": "text/plain" } },
          ));
          resp.headers.set("x-request-id", requestId);
          return resp;
        }

        const limit = parseLimit(env.RATE_LIMIT_ALEXA_PER_MINUTE, 60);
        const limited = checkRateLimit("alexa", clientId, limit);
        if (limited.limited) {
          console.warn(JSON.stringify({ event: "alexa_request_rejected", ...logBase, reason: "rate_limited" }));
          const resp = withCors(json({ error: "rate-limited", request_id: requestId, retry_after: limited.retryAfter }, 429));
          resp.headers.set("retry-after", String(limited.retryAfter));
          resp.headers.set("x-request-id", requestId);
          return resp;
        }
        console.info(JSON.stringify({ event: "alexa_request_routed", ...logBase }));
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

      if (pathname === "/v1/connectors/playback-handoff") {
        const resp = withCors(await handleConnectorPlaybackHandoff(request, env));
        resp.headers.set("x-request-id", requestId);
        return resp;
      }

      if (pathname === "/v1/connectors/playback-start-status") {
        const resp = withCors(await handleConnectorPlaybackStartStatus(request, env));
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
