from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/alexa", tags=["alexa"])

_LAUNCH_RESPONSE = {
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


@router.post("")
@router.post("/")
async def alexa_webhook(body: dict) -> JSONResponse:
    request_type = body.get("request", {}).get("type", "")
    if request_type == "LaunchRequest":
        return JSONResponse(content=_LAUNCH_RESPONSE)
    return JSONResponse(content={"error": "Unsupported request type for sprint 1."}, status_code=400)
