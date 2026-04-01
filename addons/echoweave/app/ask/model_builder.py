"""Store and generate the Alexa interaction model JSON.

The interaction model defines the intents and slots that the Alexa skill
understands.  It is versioned in the repository and pushed to AWS via ASK.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Version of the interaction model embedded in this codebase.
MODEL_VERSION = "0.1.5"


def build_interaction_model(locale: str = "en-US") -> dict[str, Any]:
    """Generate the interaction model for the given locale.

    This is a minimal MVP model focused on audio playback intents.
    """
    return {
        "interactionModel": {
            "languageModel": {
                "invocationName": "weave bridge",
                "intents": [
                    {
                        "name": "PlayIntent",
                        "slots": [],
                        "samples": [
                            "play",
                            "play music",
                            "start playing",
                            "play something",
                            "start music",
                        ],
                    },
                    {
                        "name": "PlayAudio",
                        "slots": [
                            {
                                "name": "query",
                                "type": "AMAZON.SearchQuery",
                            }
                        ],
                        "samples": [
                            "play {query}",
                            "play music by {query}",
                            "play songs by {query}",
                            "search for {query}",
                        ],
                    },
                    {"name": "AMAZON.PauseIntent", "samples": []},
                    {"name": "AMAZON.ResumeIntent", "samples": []},
                    {"name": "AMAZON.NextIntent", "samples": []},
                    {"name": "AMAZON.PreviousIntent", "samples": []},
                    {"name": "AMAZON.StopIntent", "samples": []},
                    {"name": "AMAZON.CancelIntent", "samples": []},
                    {"name": "AMAZON.HelpIntent", "samples": []},
                ],
                "types": [],
            },
        },
    }


def model_as_json(locale: str = "en-US") -> str:
    """Return the interaction model as a formatted JSON string."""
    return json.dumps(build_interaction_model(locale), indent=2)
