import { describe, expect, test } from "vitest";

import worker from "../src/index";
import { createEnv, MockD1Database } from "./mock_env";

describe("worker index admin route integration", () => {
  test("POST /v1/admin/homes is reachable via index.ts", async () => {
    const env = createEnv();
    const req = new Request("https://worker.example.com/v1/admin/homes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        tenant_id: "tenant-a",
        home_id: "home-a",
        name: "Home A",
        origin_base_url: "https://origin.example.com",
        alexa_source_queue_id: "queue-a",
      }),
    });

    const resp = await worker.fetch(req, env);
    expect(resp.status).toBe(200);
    const body = (await resp.json()) as { ok: boolean; result: { home_id: string } };
    expect(body.ok).toBe(true);
    expect(body.result.home_id).toBe("home-a");
  });

  test("GET /v1/admin/homes/:tenant/:home/status is reachable via index.ts", async () => {
    const env = createEnv();
    const db = env.ECHOWEAVE_DB as unknown as MockD1Database;
    db.homes.set("home-a", {
      id: "home-a",
      tenant_id: "tenant-a",
      name: "Home A",
      origin_base_url: "https://origin.example.com",
      connector_id: "conn-a",
      alexa_source_queue_id: "queue-a",
      is_active: 1,
    });
    db.connectors.set("conn-a", {
      connector_id: "conn-a",
      tenant_id: "tenant-a",
      home_id: "home-a",
      registration_status: "registered",
      updated_at: "2026-01-01T00:00:00Z",
    });

    const req = new Request("https://worker.example.com/v1/admin/homes/tenant-a/home-a/status", {
      method: "GET",
    });

    const resp = await worker.fetch(req, env);
    expect(resp.status).toBe(200);
    const body = (await resp.json()) as {
      ok: boolean;
      result: { tenant_id: string; home_id: string; connector: { registration_status: string } };
    };
    expect(body.ok).toBe(true);
    expect(body.result.tenant_id).toBe("tenant-a");
    expect(body.result.home_id).toBe("home-a");
    expect(body.result.connector.registration_status).toBe("registered");
  });
});
