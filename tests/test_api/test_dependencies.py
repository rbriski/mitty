"""Tests for mitty.api.dependencies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mitty.api.dependencies import get_supabase_client


class TestGetSupabaseClient:
    """get_supabase_client dependency tests."""

    async def test_returns_client_from_app_state(self) -> None:
        mock_client = AsyncMock()
        request = MagicMock()
        request.app.state.supabase_client = mock_client

        result = await get_supabase_client(request)

        assert result is mock_client

    async def test_raises_when_client_is_none(self) -> None:
        request = MagicMock()
        request.app.state.supabase_client = None

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_supabase_client(request)
        assert exc_info.value.status_code == 503
