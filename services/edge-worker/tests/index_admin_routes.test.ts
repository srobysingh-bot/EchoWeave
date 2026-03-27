import { describe, expect, test } from "vitest";

import worker from "../src/index";
import { createEnv, MockD1Database } from "./mock_env";

const adminHeaders = {
  "content-type": "application/json",
  authorization: "Bearer test-admin-key",
};

describe("worker index admin route integration", () => {
  test("POST /v1/admin/homes rejects unauthorized callers", async () => {
    const env = createEnv();
    const req = new Request("https://worker.example.com/v1/admin/homes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        tenant_id: "tenant-a",
        home_id: "home-a",
      }),
    });

    const resp = await worker.fetch(req, env);
    expect(resp.status).toBe(401);
    const body = (await resp.json()) as { error: string };
    expect(body.error).toBe("unauthorized");
  });

  test("POST /v1/admin/homes is reachable via index.ts", async () => {
    const env = createEnv();
    const req = new Request("https://worker.example.com/v1/admin/homes", {
      method: "POST",
      headers: adminHeaders,
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

  test("POST /v1/alexa is rate-limited when threshold is exceeded", async () => {
    const env = createEnv({ RATE_LIMIT_ALEXA_PER_MINUTE: "1" });
    const payload = {
      context: {
        System: {
          user: {
            userId: "amzn1.ask.account.test",
          },
        },
      },
      request: {
        type: "LaunchRequest",
        requestId: "req-1",
        timestamp: "2026-01-01T00:00:00Z",
      },
      version: "1.0",
    };

    const first = await worker.fetch(
      new Request("https://worker.example.com/v1/alexa", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "cf-connecting-ip": "203.0.113.10",
        },
        body: JSON.stringify(payload),
      }),
      env,
    );
    expect(first.status).not.toBe(429);

    const second = await worker.fetch(
      new Request("https://worker.example.com/v1/alexa", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "cf-connecting-ip": "203.0.113.10",
        },
        body: JSON.stringify(payload),
      }),
      env,
    );

    expect(second.status).toBe(429);
    const body = (await second.json()) as { error: string; retry_after: number };
    expect(body.error).toBe("rate-limited");
    expect(body.retry_after).toBeGreaterThanOrEqual(1);
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
      headers: { authorization: "Bearer test-admin-key" },
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
