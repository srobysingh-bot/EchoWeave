"""Cloud backend FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.alexa_webhook import router as alexa_router
from app.api.connectors import router as connectors_router
from app.api.health import router as health_router
from app.logging_config import setup_logging
from app.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize logging and shared process state on startup."""
    setup_logging(settings.log_level)
    # Sprint 1 baseline: initialize process-level logging only.
    yield


def create_app() -> FastAPI:
    """Build the backend API with health, Alexa, and connector routes."""
    # Keep API surface explicit for Sprint 1 and easy to extend in later phases.
    # Route registration order is intentional for predictable diagnostics output.
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(alexa_router)
    app.include_router(connectors_router)
    return app


app = create_app()
