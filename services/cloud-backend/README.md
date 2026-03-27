# EchoWeave Cloud Backend

Cloud control plane for connector registration, Alexa ingress, and connector command dispatch.

## Current routes

- `GET /health`
- `POST /v1/alexa`
- `POST /v1/connectors/register`
- `POST /v1/connectors/{connector_id}/heartbeat`
- `POST /v1/connectors/{connector_id}/commands/next`
- `POST /v1/connectors/{connector_id}/commands/{command_id}/ack`

## What is real vs stubbed

- Real:
	- connector registration and heartbeat lifecycle
	- PlayIntent command creation (`command_id`) and queueing for connector polling
	- connector ack-driven Alexa response for PlayIntent
	- structured dispatch logs including command_id, payload summary, ack result, and failure reason
- Stubbed/minimal:
	- only basic command type `play` is supported today
	- LaunchRequest does not send a connector command; it returns connector-aware welcome speech
	- no persistent database yet (in-memory store only)

## Run locally

```bash
cd services/cloud-backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Run tests

```bash
cd services/cloud-backend
pytest app/tests -v
```

## Public HTTPS deployment

This service must be reachable by Alexa over public HTTPS.

1. Deploy this folder as a web service on your host of choice (Render, Railway, Fly.io, Cloud Run).
2. Use this start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

3. After deploy, verify:

```bash
curl -i https://YOUR_BACKEND_HOST/health
curl -i -X POST https://YOUR_BACKEND_HOST/v1/alexa -H "content-type: application/json" -d '{"version":"1.0","request":{"type":"LaunchRequest"},"session":{"new":true}}'
```

4. Configure endpoint wiring:
	- EchoWeave add-on `backend_url`: `https://YOUR_BACKEND_HOST`
	- Alexa skill endpoint: `https://YOUR_BACKEND_HOST/v1/alexa`
	- Connector mode must be enabled in add-on config.

## Alexa routing logs

`POST /v1/alexa` logs these checkpoints for Launch and Play flows:

- incoming request type
- request body summary
- tenant/home resolution
- connector lookup result
- connector dispatch attempt
- command_id
- connector command payload summary
- connector ack result
- failure reason when dispatch fails
- connector dispatch result
- final Alexa response payload
- exceptions with stack trace
