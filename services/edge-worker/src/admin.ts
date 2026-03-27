import { linkAlexaAccountToHome } from "./linking";
import {
  bootstrapConnector,
  createOrUpdateHome,
  createOrUpdateUser,
  getHomeStatus,
  ProvisioningError,
} from "./provisioning";
import { Env } from "./types";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function parseBearerToken(request: Request): string {
  const bearer = request.headers.get("authorization") ?? "";
  if (!bearer.toLowerCase().startsWith("bearer ")) return "";
  return bearer.slice(7).trim();
}

function logAdminAuthFailed(requestId: string, reason: string): void {
  console.warn(
    JSON.stringify({
      event: "admin_auth_failed",
      request_id: requestId,
      reason,
    }),
  );
}

function isAdminAuthorized(request: Request, env: Env, requestId: string): { ok: boolean; status: number; reason: string } {
  const requiredKey = (env.ADMIN_API_KEY ?? "").trim();
  if (!requiredKey) {
    logAdminAuthFailed(requestId, "admin-api-key-not-configured");
    return { ok: false, status: 503, reason: "admin-auth-not-configured" };
  }

  const token = parseBearerToken(request);
  if (!token) {
    logAdminAuthFailed(requestId, "missing-bearer-token");
    return { ok: false, status: 401, reason: "unauthorized" };
  }

  if (token !== requiredKey) {
    logAdminAuthFailed(requestId, "invalid-bearer-token");
    return { ok: false, status: 403, reason: "forbidden" };
  }
  return { ok: true, status: 200, reason: "ok" };
}

function notFound(): Response {
  return json({ error: "not-found" }, 404);
}

export async function handleAdminRequest(
  request: Request,
  env: Env,
  pathname: string,
  requestId = crypto.randomUUID(),
): Promise<Response | null> {
  if (!pathname.startsWith("/v1/admin/")) return null;

  const auth = isAdminAuthorized(request, env, requestId);
  if (!auth.ok) {
    return json({ error: auth.reason, request_id: requestId }, auth.status);
  }

  try {
    if (pathname === "/v1/admin/homes" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string>;
      const result = await createOrUpdateHome(env.ECHOWEAVE_DB, {
        tenant_id: body.tenant_id ?? "",
        home_id: body.home_id ?? "",
        name: body.name ?? "",
        origin_base_url: body.origin_base_url ?? "",
        alexa_source_queue_id: body.alexa_source_queue_id ?? "",
      });
      return json({ ok: true, request_id: requestId, result }, 200);
    }

    if (pathname === "/v1/admin/users" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string>;
      const result = await createOrUpdateUser(env.ECHOWEAVE_DB, {
        user_id: body.user_id ?? "",
        tenant_id: body.tenant_id ?? "",
        email: body.email ?? "",
      });
      return json({ ok: true, request_id: requestId, result }, 200);
    }

    if (pathname === "/v1/admin/alexa-accounts/link" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string>;
      const result = await linkAlexaAccountToHome(env.ECHOWEAVE_DB, {
        alexa_user_id: body.alexa_user_id ?? "",
        user_id: body.user_id ?? "",
        tenant_id: body.tenant_id ?? "",
        home_id: body.home_id ?? "",
      });
      return json({ ok: true, request_id: requestId, result }, 200);
    }

    if (pathname === "/v1/admin/connectors/bootstrap" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string | number>;
      const result = await bootstrapConnector(env.ECHOWEAVE_DB, {
        tenant_id: String(body.tenant_id ?? ""),
        home_id: String(body.home_id ?? ""),
        connector_id: String(body.connector_id ?? ""),
        ttl_seconds: Number(body.ttl_seconds ?? 3600),
      });
      return json({ ok: true, request_id: requestId, result }, 200);
    }

    const homeStatusMatch = pathname.match(/^\/v1\/admin\/homes\/([^/]+)\/([^/]+)\/status$/);
    if (homeStatusMatch && request.method === "GET") {
      const tenantId = decodeURIComponent(homeStatusMatch[1]);
      const homeId = decodeURIComponent(homeStatusMatch[2]);
      const result = await getHomeStatus(env, tenantId, homeId);
      return json({ ok: true, request_id: requestId, result }, 200);
    }

    return notFound();
  } catch (error) {
    if (error instanceof ProvisioningError) {
      return json({ error: error.message, request_id: requestId }, error.status);
    }
    return json({ error: error instanceof Error ? error.message : "internal-error", request_id: requestId }, 500);
  }
}