"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import (  # noqa: TCH002 - FastAPI needs runtime type for DI
    Depends,
    HTTPException,
    Request,
)

from mitty.api.auth import get_current_user  # noqa: TCH001

if TYPE_CHECKING:
    from supabase import AsyncClient


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
