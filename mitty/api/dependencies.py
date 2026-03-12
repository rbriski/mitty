"""FastAPI dependency injection providers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import (  # noqa: TCH002 - FastAPI needs runtime type for DI
    Depends,
    HTTPException,
    Request,
)

from mitty.api.auth import get_current_user  # noqa: TCH001

if TYPE_CHECKING:
    from supabase import AsyncClient

    from mitty.ai.client import AIClient

logger = logging.getLogger("mitty.api.dependencies")


async def get_ai_client(request: Request) -> AIClient | None:
    """Return an AIClient instance, or None if not configured.

    The AIClient is lazily created on first request and cached on
    ``app.state.ai_client``.  Returns None when the Anthropic API key
    is not set, allowing endpoints to degrade gracefully.
    """
    existing: AIClient | None = getattr(request.app.state, "ai_client", None)
    if existing is not None:
        return existing

    try:
        from mitty.ai.client import AIClient as _AIClient
        from mitty.config import load_settings

        settings = load_settings()
        if settings.anthropic_api_key is None:
            logger.info("Anthropic API key not configured — AI features disabled")
            return None

        client = _AIClient(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
        )
        request.app.state.ai_client = client
        return client
    except Exception:
        logger.warning("Failed to create AIClient", exc_info=True)
        return None


async def get_supabase_client(request: Request) -> AsyncClient:
    """Retrieve the anon-key Supabase client from application state.

    This client respects RLS but has NO user context set.
    Use ``get_user_client`` for user-scoped queries instead.
    """
    client: AsyncClient | None = request.app.state.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return client


async def get_user_client(
    request: Request,
    current_user: dict = Depends(get_current_user),  # noqa: B008
) -> AsyncClient:
    """Return the anon-key Supabase client with the user's JWT set for RLS.

    Sets ``postgrest.auth(token)`` so all subsequent queries on this
    client run as the authenticated user, with RLS enforced.

    Note: postgrest.auth() sets state on the shared client.  This is
    safe for single-user / low-concurrency usage.  For high-concurrency
    scenarios, create a per-request postgrest client instead.
    """
    client: AsyncClient | None = request.app.state.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Set the user's JWT so PostgREST enforces RLS as this user
    client.postgrest.auth(current_user["access_token"])
    return client
