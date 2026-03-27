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
