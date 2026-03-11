"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import (  # noqa: TCH002 - FastAPI needs runtime type for DI
    HTTPException,
    Request,
)

if TYPE_CHECKING:
    from supabase import AsyncClient


async def get_supabase_client(request: Request) -> AsyncClient:
    """Retrieve the Supabase async client from application state.

    Raises:
        RuntimeError: If the Supabase client was not configured at startup.
    """
    client: AsyncClient | None = request.app.state.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return client
