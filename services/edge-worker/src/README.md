# EchoWeave Edge Worker

Cloudflare Worker control plane for Alexa ingress, connector routing, and stream proxying.

- `POST /v1/alexa`: public Alexa skill endpoint
- `POST /v1/connectors/register`: connector registration API
- `GET /v1/connectors/ws`: connector WebSocket attach endpoint
- `GET /v1/stream/:token`: signed stream proxy endpoint

Durable Object class: `HomeSession`
D1 binding: `ECHOWEAVE_DB`

TODO: Bind production secrets in Wrangler (`STREAM_TOKEN_SIGNING_SECRET`, `EDGE_ORIGIN_SHARED_SECRET`, optional `CONNECTOR_BOOTSTRAP_SECRET`).
