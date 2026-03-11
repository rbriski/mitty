"""Supabase client creation helper for the API layer."""

from __future__ import annotations

from supabase import AsyncClient, acreate_client


async def create_supabase_client(url: str, key: str) -> AsyncClient:
    """Create an async Supabase client."""
    return await acreate_client(url, key)
