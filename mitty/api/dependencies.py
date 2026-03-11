"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from supabase import AsyncClient


async def get_supabase_client(request: Request) -> AsyncClient:
    """Retrieve the Supabase async client from application state.

    Raises:
        RuntimeError: If the Supabase client was not configured at startup.
    """
    client: AsyncClient | None = request.app.state.supabase_client
    if client is None:
        msg = "Supabase client is not configured"
        raise RuntimeError(msg)
    return client
