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

function isAdminAuthorized(request: Request, env: Env): boolean {
  const requiredKey = (env.ADMIN_API_KEY ?? "").trim();
  if (!requiredKey) return true;

  const bearer = request.headers.get("authorization") ?? "";
  const token = bearer.toLowerCase().startsWith("bearer ") ? bearer.slice(7).trim() : "";
  return token === requiredKey;
}

function notFound(): Response {
  return json({ error: "not-found" }, 404);
}

export async function handleAdminRequest(request: Request, env: Env, pathname: string): Promise<Response | null> {
  if (!pathname.startsWith("/v1/admin/")) return null;

  if (!isAdminAuthorized(request, env)) {
    return json({ error: "unauthorized" }, 401);
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
      return json({ ok: true, result }, 200);
    }

    if (pathname === "/v1/admin/users" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string>;
      const result = await createOrUpdateUser(env.ECHOWEAVE_DB, {
        user_id: body.user_id ?? "",
        tenant_id: body.tenant_id ?? "",
        email: body.email ?? "",
      });
      return json({ ok: true, result }, 200);
    }

    if (pathname === "/v1/admin/alexa-accounts/link" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string>;
      const result = await linkAlexaAccountToHome(env.ECHOWEAVE_DB, {
        alexa_user_id: body.alexa_user_id ?? "",
        user_id: body.user_id ?? "",
        tenant_id: body.tenant_id ?? "",
        home_id: body.home_id ?? "",
      });
      return json({ ok: true, result }, 200);
    }

    if (pathname === "/v1/admin/connectors/bootstrap" && request.method === "POST") {
      const body = (await request.json()) as Record<string, string | number>;
      const result = await bootstrapConnector(env.ECHOWEAVE_DB, {
        tenant_id: String(body.tenant_id ?? ""),
        home_id: String(body.home_id ?? ""),
        connector_id: String(body.connector_id ?? ""),
        ttl_seconds: Number(body.ttl_seconds ?? 3600),
      });
      return json({ ok: true, result }, 200);
    }

    const homeStatusMatch = pathname.match(/^\/v1\/admin\/homes\/([^/]+)\/([^/]+)\/status$/);
    if (homeStatusMatch && request.method === "GET") {
      const tenantId = decodeURIComponent(homeStatusMatch[1]);
      const homeId = decodeURIComponent(homeStatusMatch[2]);
      const result = await getHomeStatus(env, tenantId, homeId);
      return json({ ok: true, result }, 200);
    }

    return notFound();
  } catch (error) {
    if (error instanceof ProvisioningError) {
      return json({ error: error.message }, error.status);
    }
    return json({ error: error instanceof Error ? error.message : "internal-error" }, 500);
  }
}