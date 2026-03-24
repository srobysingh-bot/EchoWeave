"""Map region and locale values for ASK configuration."""

from __future__ import annotations

# Supported Alexa locale → AWS region mapping.
LOCALE_REGION_MAP: dict[str, str] = {
    "en-US": "us-east-1",
    "en-CA": "us-east-1",
    "en-GB": "eu-west-1",
    "en-AU": "us-west-2",
    "en-IN": "eu-west-1",
    "de-DE": "eu-west-1",
    "fr-FR": "eu-west-1",
    "it-IT": "eu-west-1",
    "es-ES": "eu-west-1",
    "es-MX": "us-east-1",
    "ja-JP": "us-west-2",
    "pt-BR": "us-east-1",
}


def get_aws_region_for_locale(locale: str) -> str:
    """Return the recommended AWS region for the given Alexa locale."""
    return LOCALE_REGION_MAP.get(locale, "us-east-1")


def is_supported_locale(locale: str) -> bool:
    """Return ``True`` if *locale* is in our known list."""
    return locale in LOCALE_REGION_MAP
