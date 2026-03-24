"""High-level Alexa skill setup flow.

TODO: Phase 1 stub — all methods log and return placeholder results.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SkillSetup:
    """Orchestrate skill creation, update, and deployment."""

    async def detect_existing_skill(self) -> str | None:
        """Check if a skill already exists. Returns skill ID or None."""
        logger.info("Detecting existing skill — not yet implemented.")
        return None

    async def create_skill(self, endpoint_url: str, locale: str) -> str | None:
        """Create a new Alexa skill. Returns skill ID or None."""
        logger.info("Creating skill — not yet implemented.")
        return None

    async def update_endpoint(self, skill_id: str, endpoint_url: str) -> bool:
        """Update the skill's webhook endpoint URL."""
        logger.info("Updating endpoint for skill %s — not yet implemented.", skill_id)
        return False

    async def update_interaction_model(self, skill_id: str, locale: str) -> bool:
        """Push the interaction model to the skill."""
        logger.info("Updating interaction model for skill %s — not yet implemented.", skill_id)
        return False

    async def trigger_build(self, skill_id: str, locale: str) -> bool:
        """Trigger an interaction model build."""
        logger.info("Triggering build for skill %s — not yet implemented.", skill_id)
        return False

    async def get_build_status(self, skill_id: str) -> str:
        """Query the current build status."""
        logger.info("Querying build status for skill %s — not yet implemented.", skill_id)
        return "UNKNOWN"
