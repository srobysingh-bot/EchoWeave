import { handleAlexaWebhook } from "./alexa";
import { handleConnectorRegister, handleConnectorWebSocket } from "./connectors";
import { HomeSession } from "./durable_objects/HomeSession";
import { handleStreamRequest } from "./stream";
import { Env } from "./types";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function withCors(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET,POST,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,signature,signaturecertchainurl,x-connector-bootstrap-secret");
  return new Response(response.body, { status: response.status, headers });
}

export { HomeSession };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return withCors(new Response(null, { status: 204 }));
    }

    const url = new URL(request.url);
    const pathname = url.pathname;

    try {
      if (pathname === "/healthz") {
        return withCors(json({ status: "ok", service: "edge-worker" }));
      }

      if (pathname === "/v1/alexa") {
        return withCors(await handleAlexaWebhook(request, env));
      }

      if (pathname === "/v1/connectors/register") {
        return withCors(await handleConnectorRegister(request, env));
      }

      if (pathname === "/v1/connectors/ws") {
        return withCors(await handleConnectorWebSocket(request, env));
      }

      if (pathname.startsWith("/v1/stream/")) {
        const token = decodeURIComponent(pathname.replace("/v1/stream/", ""));
        return withCors(await handleStreamRequest(request, env, token));
      }

      return withCors(json({ error: "not-found" }, 404));
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal-error";
      return withCors(json({ error: message }, 500));
    }
  },
};
