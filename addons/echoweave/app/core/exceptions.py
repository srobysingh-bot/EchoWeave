"""Application-specific exception types."""

from __future__ import annotations


class EchoWeaveError(Exception):
    """Base exception for all EchoWeave errors."""

    def __init__(self, message: str = "", *, detail: str = "") -> None:
        self.detail = detail
        super().__init__(message)


class ConfigurationError(EchoWeaveError):
    """Raised when required configuration is missing or invalid."""


class MusicAssistantError(EchoWeaveError):
    """Raised when an MA API call fails."""


class MusicAssistantAuthError(MusicAssistantError):
    """Raised when MA token authentication fails."""


class MusicAssistantUnreachableError(MusicAssistantError):
    """Raised when the MA server cannot be reached."""


class StreamResolutionError(EchoWeaveError):
    """Raised when a playable stream URL cannot be derived."""


class AlexaRequestError(EchoWeaveError):
    """Raised when an incoming Alexa request is malformed."""


class AlexaSessionError(EchoWeaveError):
    """Raised on session state lookup/write failures."""


class StorageError(EchoWeaveError):
    """Raised on persistent storage read/write failures."""


class ASKError(EchoWeaveError):
    """Raised on ASK CLI or skill management failures."""


class EndpointValidationError(EchoWeaveError):
    """Raised when configured public endpoint fails validation."""
