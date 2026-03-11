"""FastAPI application factory.

Creates the app with CORS middleware, request logging,
health endpoint, Supabase client lifecycle, and error handling.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mitty.api.middleware import RequestLoggingMiddleware
from mitty.api.routers import health
from mitty.config import load_settings

logger = logging.getLogger("mitty.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle — Supabase client setup and teardown."""
    settings = load_settings()

    if settings.supabase_url and settings.supabase_service_role_key:
        from mitty.api._supabase import create_supabase_client

        key = settings.supabase_service_role_key.get_secret_value()
        client = await create_supabase_client(settings.supabase_url, key)
        app.state.supabase_client = client
        logger.info("Supabase client initialised")
    else:
        app.state.supabase_client = None
        logger.warning(
            "Supabase client not configured "
            "(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required)"
        )

    yield

    # Shutdown: nothing to clean up for Supabase async client currently.
    logger.info("Application shutdown")


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    settings = load_settings()

    origins: list[str] = [
        o.strip() for o in settings.allowed_origins.split(",") if o.strip()
    ]

    app = FastAPI(
        title="Mitty API",
        version="1.0.0",
        debug=settings.fastapi_debug,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Routers
    app.include_router(health.router)

    # Standardized error handler (covers both FastAPI and Starlette HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": str(exc.status_code),
                    "message": exc.detail,
                    "detail": None,
                }
            },
        )

    return app
