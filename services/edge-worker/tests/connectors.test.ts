import { describe, expect, test } from "vitest";

import { handleConnectorRegister } from "../src/connectors";
import { createEnv, MockD1Database } from "./mock_env";

describe("connector registration", () => {
  test("bootstraps a missing home when origin_base_url is provided", async () => {
    const env = createEnv({ CONNECTOR_BOOTSTRAP_SECRET: "bootstrap-secret" });
    const db = env.ECHOWEAVE_DB as unknown as MockD1Database;

    const req = new Request("https://worker/v1/connectors/register", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-connector-bootstrap-secret": "bootstrap-secret",
      },
      body: JSON.stringify({
        connector_id: "conn-a",
        connector_secret: "secret-a",
        tenant_id: "tenant-a",
        home_id: "home-a",
        origin_base_url: "https://origin.example.com",
        alexa_source_queue_id: "queue-a",
        capabilities: { commands: ["prepare_play"] },
      }),
    });

    const resp = await handleConnectorRegister(req, env);

    expect(resp.status).toBe(200);
    expect(db.homes.get("home-a")).toMatchObject({
      tenant_id: "tenant-a",
      connector_id: "conn-a",
      origin_base_url: "https://origin.example.com",
      alexa_source_queue_id: "queue-a",
      is_active: 1,
    });
    expect(db.connectors.get("conn-a")).toMatchObject({
      tenant_id: "tenant-a",
      home_id: "home-a",
      registration_status: "registered",
    });
  });
});