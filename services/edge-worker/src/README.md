# EchoWeave Edge Worker

Cloudflare Worker control plane for Alexa ingress, connector routing, and stream proxying.

- `POST /v1/alexa`: public Alexa skill endpoint
- `POST /v1/connectors/register`: connector registration API
- `GET /v1/connectors/ws`: connector WebSocket attach endpoint
- `GET /v1/stream/:token`: signed stream proxy endpoint
- `POST /v1/admin/homes`: create/update home provisioning
- `POST /v1/admin/users`: create/update tenant user
- `POST /v1/admin/alexa-accounts/link`: deterministic alexa account link
- `POST /v1/admin/connectors/bootstrap`: generate/rotate connector bootstrap credentials
- `GET /v1/admin/homes/:tenant_id/:home_id/status`: provisioning and runtime readiness status

Durable Object class: `HomeSession`
D1 binding: `ECHOWEAVE_DB`

Security status:

- Alexa request verification enforces timestamp freshness, cert URL validation, certificate fetch/parsing, SAN/time checks, and RSA verification over exact request body.
- Full certificate chain trust and revocation checks are still a hardening follow-up.

TODO: Bind production secrets in Wrangler (`STREAM_TOKEN_SIGNING_SECRET`, `EDGE_ORIGIN_SHARED_SECRET`, optional `CONNECTOR_BOOTSTRAP_SECRET`).
