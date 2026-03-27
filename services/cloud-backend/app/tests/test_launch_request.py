import threading
import time

from fastapi.testclient import TestClient

from app.main import app
from app.storage.memory_store import store


def _register_connector(client: TestClient) -> None:
    client.post(
        "/v1/connectors/register",
        json={
            "connector_id": "connector-e2e-1",
            "tenant_id": "tenant-e2e",
            "home_id": "home-e2e",
            "connector_secret": "secret-e2e",
            "capabilities": {"music_assistant": {"reachable": True}},
        },
    )
    client.post(
        "/v1/connectors/connector-e2e-1/heartbeat",
        json={"connector_secret": "secret-e2e", "status": "online"},
    )


def test_launch_request_returns_expected_payload():
    store.connectors.clear()
    body = {
        "version": "1.0",
        "request": {"type": "LaunchRequest"},
        "session": {"new": True},
    }
    with TestClient(app) as client:
        resp = client.post("/v1/alexa", json=body)

    assert resp.status_code == 200
    assert resp.json() == {
        "version": "1.0",
        "sessionAttributes": {},
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": "Welcome to EchoWeave.",
            },
            "reprompt": {
                "outputSpeech": {
                    "type": "PlainText",
                    "text": "EchoWeave is ready.",
                }
            },
            "shouldEndSession": False,
        },
    }


def test_launch_and_play_route_to_registered_connector_with_logs(capfd):
    store.connectors.clear()
    with TestClient(app) as client:
        _register_connector(client)

        launch_body = {
            "version": "1.0",
            "session": {
                "new": True,
                "sessionId": "session-e2e-1",
                "attributes": {"tenant_id": "tenant-e2e", "home_id": "home-e2e"},
            },
            "request": {"type": "LaunchRequest", "requestId": "req-launch-1"},
            "context": {"System": {"user": {"userId": "user-1"}}},
        }
        play_body = {
            "version": "1.0",
            "session": {
                "new": False,
                "sessionId": "session-e2e-1",
                "attributes": {"tenant_id": "tenant-e2e", "home_id": "home-e2e"},
            },
            "request": {
                "type": "IntentRequest",
                "requestId": "req-play-1",
                "intent": {"name": "PlayIntent"},
            },
            "context": {"System": {"user": {"userId": "user-1"}}},
        }

        launch_resp = client.post("/v1/alexa", json=launch_body)

        captured: dict[str, str] = {"command_id": ""}

        def _ack_worker() -> None:
            deadline = time.time() + 5
            while time.time() < deadline:
                poll_resp = client.post(
                    "/v1/connectors/connector-e2e-1/commands/next",
                    json={"connector_secret": "secret-e2e"},
                )
                if poll_resp.status_code == 200 and poll_resp.json():
                    payload = poll_resp.json()
                    captured["command_id"] = payload["command_id"]
                    client.post(
                        f"/v1/connectors/connector-e2e-1/commands/{payload['command_id']}/ack",
                        json={
                            "connector_secret": "secret-e2e",
                            "success": True,
                            "message": "play-started",
                            "result": {"player_id": "player-1"},
                        },
                    )
                    return
                time.sleep(0.1)

        thread = threading.Thread(target=_ack_worker, daemon=True)
        thread.start()
        play_resp = client.post("/v1/alexa", json=play_body)
        thread.join(timeout=5)

    assert launch_resp.status_code == 200
    assert launch_resp.json()["response"]["outputSpeech"]["text"] == "Welcome to EchoWeave. Your connector is online."

    assert play_resp.status_code == 200
    assert play_resp.json()["response"]["outputSpeech"]["text"] == "Playing now from Music Assistant."
    assert captured["command_id"]

    log_output = capfd.readouterr().out
    assert "alexa_request type=LaunchRequest" in log_output
    assert "alexa_request type=IntentRequest intent=PlayIntent" in log_output
    assert "tenant_home_resolve tenant_id=tenant-e2e home_id=home-e2e" in log_output
    assert "connector_lookup result=found connector_id=connector-e2e-1" in log_output
    assert "connector_dispatch_attempt connector_id=connector-e2e-1 request_type=LaunchRequest" in log_output
    assert "connector_dispatch_attempt connector_id=connector-e2e-1 request_type=IntentRequest intent=PlayIntent" in log_output
    assert "connector_dispatch_result connector_id=connector-e2e-1 success=True note=launch-routed-real" in log_output
    assert "connector_dispatch_result connector_id=connector-e2e-1 success=True note=play-routed-acked" in log_output
    assert "command_id=" in log_output
    assert "connector_ack=" in log_output
    assert "alexa_response payload=" in log_output
