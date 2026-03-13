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
from mitty.api.routers import (
    ai_usage,
    assessments,
    config,
    health,
    mastery_dashboard,
    mastery_states,
    pages,
    practice_results,
    practice_sessions,
    resource_chunks,
    resources,
    student_signals,
    study_blocks,
    study_plans,
)
from mitty.config import load_settings

logger = logging.getLogger("mitty.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle — Supabase client setup and teardown."""
    settings = load_settings()

    # Service-role client — used ONLY for auth.get_user() token validation.
    # Bypasses RLS by design; never used for data queries.
    if settings.supabase_url and settings.supabase_service_role_key:
        from mitty.api._supabase import create_supabase_client

        key = settings.supabase_service_role_key.get_secret_value()
        app.state.supabase_admin = await create_supabase_client(
            settings.supabase_url, key
        )
        logger.info("Supabase admin client initialised (auth only)")
    else:
        app.state.supabase_admin = None
        logger.warning("Supabase admin client not configured (auth will fail)")

    # Anon-key client — used for all data queries.
    # Respects RLS; user JWT is set per-request via postgrest.auth().
    if settings.supabase_url and settings.supabase_anon_key:
        from mitty.api._supabase import create_supabase_client

        anon = settings.supabase_anon_key.get_secret_value()
        app.state.supabase_client = await create_supabase_client(
            settings.supabase_url, anon
        )
        logger.info("Supabase data client initialised (anon key, RLS enforced)")
    else:
        app.state.supabase_client = None
        logger.warning(
            "Supabase data client not configured (SUPABASE_ANON_KEY required)"
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
    app.include_router(pages.router)
    app.include_router(student_signals.router)
    app.include_router(study_plans.router)
    app.include_router(study_blocks.router)
    app.include_router(mastery_states.router)
    app.include_router(mastery_dashboard.router)
    app.include_router(practice_results.router)
    app.include_router(config.router)
    app.include_router(assessments.router)
    app.include_router(resources.router)
    app.include_router(resource_chunks.router)
    app.include_router(practice_sessions.router)
    app.include_router(ai_usage.router)

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
