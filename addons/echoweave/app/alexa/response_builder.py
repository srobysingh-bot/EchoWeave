"""Standardise Alexa JSON response envelopes.

Every response from the skill endpoint must follow the Alexa response format.
This module ensures well-formed responses and prevents malformed JSON.
"""

from __future__ import annotations

from typing import Any, Optional


def build_response(
    *,
    speech: str = "",
    reprompt: str = "",
    should_end_session: Optional[bool] = None,
    directives: list[dict[str, Any]] | None = None,
    card: dict[str, Any] | None = None,
    session_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a valid Alexa response envelope.

    Parameters
    ----------
    speech:
        Plain text or SSML to speak.  Omit for silent responses.
    reprompt:
        Follow-up prompt if the session stays open.
    should_end_session:
        ``True`` to close the session, ``False`` to keep it open, ``None``
        to omit (required for AudioPlayer-only responses).
    directives:
        List of AudioPlayer or other directives.
    card:
        Optional visual card for Alexa app.
    session_attributes:
        Optional session attributes object. Defaults to an empty object for
        schema safety in conversational responses.
    """
    response: dict[str, Any] = {}

    if speech:
        response["outputSpeech"] = {
            "type": "PlainText",
            "text": speech,
        }

    if reprompt:
        response["reprompt"] = {
            "outputSpeech": {
                "type": "PlainText",
                "text": reprompt,
            }
        }

    if should_end_session is not None:
        response["shouldEndSession"] = should_end_session

    if directives:
        response["directives"] = directives

    if card:
        response["card"] = card

    if session_attributes is None:
        session_attributes = {}

    return {
        "version": "1.0",
        "sessionAttributes": session_attributes,
        "response": response,
    }


def build_error_response(message: str) -> dict[str, Any]:
    """Build a response indicating an error, intended for logging only.

    Alexa will typically not render error responses to users, but having
    a structured error envelope helps debugging.
    """
    return build_response(
        speech=f"An error occurred: {message}",
        should_end_session=True,
    )
