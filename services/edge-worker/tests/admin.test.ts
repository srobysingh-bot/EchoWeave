import { describe, expect, test } from "vitest";

import { handleAdminRequest } from "../src/admin";
import { createEnv, MockD1Database } from "./mock_env";

const adminHeaders = {
  "content-type": "application/json",
  authorization: "Bearer test-admin-key",
};

describe("admin provisioning routes", () => {
  test("POST /v1/admin/homes creates a home", async () => {
    const env = createEnv();
    const req = new Request("https://worker/v1/admin/homes", {
      method: "POST",
      headers: adminHeaders,
      body: JSON.stringify({
        tenant_id: "tenant-a",
        home_id: "home-a",
        name: "My Home",
        origin_base_url: "https://origin.example.com",
        alexa_source_queue_id: "queue-a",
      }),
    });

    const resp = await handleAdminRequest(req, env, "/v1/admin/homes");
    expect(resp).not.toBeNull();
    expect(resp?.status).toBe(200);
    const body = (await resp?.json()) as { ok: boolean; result: { tenant_id: string; home_id: string } };
    expect(body.ok).toBe(true);
    expect(body.result.tenant_id).toBe("tenant-a");
    expect(body.result.home_id).toBe("home-a");
  });

  test("POST /v1/admin/users creates a user", async () => {
    const env = createEnv();
    const req = new Request("https://worker/v1/admin/users", {
      method: "POST",
      headers: adminHeaders,
      body: JSON.stringify({ user_id: "user-a", tenant_id: "tenant-a", email: "user@example.com" }),
    });

    const resp = await handleAdminRequest(req, env, "/v1/admin/users");
    expect(resp?.status).toBe(200);
    const body = (await resp?.json()) as { ok: boolean; result: { user_id: string } };
    expect(body.ok).toBe(true);
    expect(body.result.user_id).toBe("user-a");
  });

  test("POST /v1/admin/alexa-accounts/link creates mapping", async () => {
    const env = createEnv();

    await handleAdminRequest(
      new Request("https://worker/v1/admin/homes", {
        method: "POST",
        headers: adminHeaders,
        body: JSON.stringify({ tenant_id: "tenant-a", home_id: "home-a" }),
      }),
      env,
      "/v1/admin/homes",
    );
    await handleAdminRequest(
      new Request("https://worker/v1/admin/users", {
        method: "POST",
        headers: adminHeaders,
        body: JSON.stringify({ user_id: "user-a", tenant_id: "tenant-a", email: "user@example.com" }),
      }),
      env,
      "/v1/admin/users",
    );

    const resp = await handleAdminRequest(
      new Request("https://worker/v1/admin/alexa-accounts/link", {
        method: "POST",
        headers: adminHeaders,
        body: JSON.stringify({
          alexa_user_id: "amzn-account-1",
          user_id: "user-a",
          tenant_id: "tenant-a",
          home_id: "home-a",
        }),
      }),
      env,
      "/v1/admin/alexa-accounts/link",
    );

    expect(resp?.status).toBe(200);
    const body = (await resp?.json()) as { ok: boolean; result: { alexa_user_id: string } };
    expect(body.ok).toBe(true);
    expect(body.result.alexa_user_id).toBe("amzn-account-1");
  });

  test("GET /v1/admin/homes/:tenant/:home/status returns provisioning state", async () => {
    const env = createEnv();
    const db = env.ECHOWEAVE_DB as unknown as MockD1Database;
    db.homes.set("home-a", {
      id: "home-a",
      tenant_id: "tenant-a",
      name: "My Home",
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
    db.alexaAccounts.set("alexa-1", {
      alexa_user_id: "alexa-1",
      user_id: "user-a",
      tenant_id: "tenant-a",
      home_id: "home-a",
    });

    const resp = await handleAdminRequest(
      new Request("https://worker/v1/admin/homes/tenant-a/home-a/status", {
        method: "GET",
        headers: { authorization: "Bearer test-admin-key" },
      }),
      env,
      "/v1/admin/homes/tenant-a/home-a/status",
    );

    expect(resp?.status).toBe(200);
    const body = (await resp?.json()) as {
      ok: boolean;
      result: { alexa_account_linked: boolean; connector: { registration_status: string } };
    };
    expect(body.ok).toBe(true);
    expect(body.result.alexa_account_linked).toBe(true);
    expect(body.result.connector.registration_status).toBe("registered");
  });

  test("POST /v1/admin/connectors/bootstrap returns connector credentials", async () => {
    const env = createEnv();
    const db = env.ECHOWEAVE_DB as unknown as MockD1Database;
    db.homes.set("home-a", {
      id: "home-a",
      tenant_id: "tenant-a",
      name: "My Home",
      origin_base_url: "https://origin.example.com",
      connector_id: null,
      alexa_source_queue_id: "queue-a",
      is_active: 1,
    });

    const resp = await handleAdminRequest(
      new Request("https://worker/v1/admin/connectors/bootstrap", {
        method: "POST",
        headers: adminHeaders,
        body: JSON.stringify({
          tenant_id: "tenant-a",
          home_id: "home-a",
          connector_id: "conn-a",
          ttl_seconds: 1800,
        }),
      }),
      env,
      "/v1/admin/connectors/bootstrap",
    );

    expect(resp?.status).toBe(200);
    const body = (await resp?.json()) as { ok: boolean; result: { connector_id: string; connector_secret: string } };
    expect(body.ok).toBe(true);
    expect(body.result.connector_id).toBe("conn-a");
    expect(body.result.connector_secret.length).toBeGreaterThan(20);
  });
});
