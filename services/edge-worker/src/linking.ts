import { ProvisioningError } from "./provisioning";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/;

function validateId(value: string, field: string): string {
  const trimmed = (value ?? "").trim();
  if (!trimmed) throw new ProvisioningError(`${field} is required`, 400);
  if (!ID_PATTERN.test(trimmed)) throw new ProvisioningError(`${field} contains invalid characters`, 400);
  return trimmed;
}

export interface LinkAlexaAccountInput {
  alexa_user_id: string;
  user_id: string;
  tenant_id: string;
  home_id: string;
}

export async function linkAlexaAccountToHome(db: D1Database, input: LinkAlexaAccountInput): Promise<Record<string, unknown>> {
  const alexaUserId = validateId(input.alexa_user_id, "alexa_user_id");
  const userId = validateId(input.user_id, "user_id");
  const tenantId = validateId(input.tenant_id, "tenant_id");
  const homeId = validateId(input.home_id, "home_id");

  const user = await db
    .prepare("SELECT id, tenant_id FROM users WHERE id = ? LIMIT 1")
    .bind(userId)
    .first<{ id: string; tenant_id: string }>();
  if (!user) throw new ProvisioningError("user-not-found", 404);
  if (user.tenant_id !== tenantId) throw new ProvisioningError("cross-tenant user mismatch", 409);

  const home = await db
    .prepare("SELECT id, tenant_id FROM homes WHERE id = ? LIMIT 1")
    .bind(homeId)
    .first<{ id: string; tenant_id: string }>();
  if (!home) throw new ProvisioningError("home-not-found", 404);
  if (home.tenant_id !== tenantId) throw new ProvisioningError("cross-tenant home mismatch", 409);

  const existing = await db
    .prepare("SELECT alexa_user_id, user_id, tenant_id, home_id FROM alexa_accounts WHERE alexa_user_id = ? LIMIT 1")
    .bind(alexaUserId)
    .first<{ alexa_user_id: string; user_id: string; tenant_id: string; home_id: string }>();

  if (
    existing &&
    existing.user_id === userId &&
    existing.tenant_id === tenantId &&
    existing.home_id === homeId
  ) {
    return {
      updated: false,
      alexa_user_id: alexaUserId,
      user_id: userId,
      tenant_id: tenantId,
      home_id: homeId,
    };
  }

  if (existing && existing.tenant_id !== tenantId) {
    throw new ProvisioningError("cross-tenant alexa mapping update denied", 409);
  }

  await db
    .prepare(
      `
      INSERT INTO alexa_accounts (alexa_user_id, user_id, tenant_id, home_id)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(alexa_user_id) DO UPDATE SET
        user_id = excluded.user_id,
        tenant_id = excluded.tenant_id,
        home_id = excluded.home_id,
        updated_at = CURRENT_TIMESTAMP
      `,
    )
    .bind(alexaUserId, userId, tenantId, homeId)
    .run();

  return {
    updated: Boolean(existing),
    alexa_user_id: alexaUserId,
    user_id: userId,
    tenant_id: tenantId,
    home_id: homeId,
  };
}