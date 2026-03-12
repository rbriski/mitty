"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


class _UserScopedClient:
    """Lightweight proxy that captures the user's postgrest headers at
    construction time, preventing concurrent requests from clobbering
    each other's ``Authorization`` header on the shared Supabase client.

    Every call to ``table()`` / ``from_()`` injects the captured
    per-request headers rather than reading the (potentially mutated)
    shared headers from the underlying postgrest client.

    All other attribute access is forwarded to the inner client so
    callers (route handlers) can use it as a drop-in ``AsyncClient``.
    """

    __slots__ = ("_inner", "_headers")

    def __init__(self, inner: AsyncClient, token: str) -> None:
        self._inner = inner

        # Snapshot the current shared headers and stamp the user's JWT.
        try:
            self._headers = dict(inner.postgrest.headers)
        except (TypeError, AttributeError):
            # In test mocks, headers may not be a real dict.
            self._headers = {}
        self._headers["Authorization"] = f"Bearer {token}"

    def table(self, table_name: str) -> Any:
        """Delegate to the inner client's table() with per-request headers."""
        pg = self._inner.postgrest
        # Temporarily swap headers to our per-request copy so the
        # RequestBuilder captures the correct Authorization value.
        original_headers = pg.headers
        pg.headers = self._headers
        try:
            return self._inner.table(table_name)
        finally:
            pg.headers = original_headers

    def from_(self, table_name: str) -> Any:
        """Alias for ``table()``."""
        return self.table(table_name)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def get_user_client(
    request: Request,
    current_user: dict = Depends(get_current_user),  # noqa: B008
) -> AsyncClient:
    """Return a per-request Supabase client wrapper with the user's JWT.

    Creates a lightweight ``_UserScopedClient`` that snapshots the
    postgrest headers at dependency-resolution time and injects them
    on every ``table()`` / ``from_()`` call.  This prevents concurrent
    requests from overwriting each other's ``Authorization`` header.
    """
    client: AsyncClient | None = request.app.state.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    return _UserScopedClient(client, current_user["access_token"])  # type: ignore[return-value]
