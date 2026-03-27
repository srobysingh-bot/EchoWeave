# EchoWeave Cloud Backend (Sprint 1)

This service provides the first cloud baseline for EchoWeave:

- `GET /health`
- `POST /v1/alexa` (LaunchRequest only)
- `POST /v1/connectors/register`
- `POST /v1/connectors/{connector_id}/heartbeat`

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
curl -i https://YOUR_BACKEND_HOST/v1/alexa
```

4. Configure endpoints:
	- EchoWeave add-on `backend_url`: `https://YOUR_BACKEND_HOST`
	- Alexa skill endpoint: `https://YOUR_BACKEND_HOST/v1/alexa`

## Alexa routing logs

`POST /v1/alexa` logs these checkpoints for Launch and Play flows:

- incoming request type
- request body summary
- tenant/home resolution
- connector lookup result
- connector dispatch attempt
- connector dispatch result
- final Alexa response payload
- exceptions with stack trace
