from fastapi.testclient import TestClient

from app.main import app


def test_launch_request_returns_expected_payload():
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
