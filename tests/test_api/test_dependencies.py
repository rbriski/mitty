"""Tests for mitty.api.dependencies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.api.dependencies import _NOT_CONFIGURED, get_ai_client, get_supabase_client


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


class TestGetAiClient:
    """get_ai_client dependency tests — rate limiter wiring."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_api_key(self) -> None:
        """When ANTHROPIC_API_KEY is not set, returns None and caches sentinel."""
        request = MagicMock()
        request.app.state.ai_client = None

        with patch("mitty.config.load_settings") as mock_load:
            settings = MagicMock()
            settings.anthropic_api_key = None
            mock_load.return_value = settings

            result = await get_ai_client(request)

        assert result is None
        assert request.app.state.ai_client is _NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_returns_cached_client(self) -> None:
        """When ai_client is already set on app state, returns it directly."""
        mock_client = MagicMock()
        request = MagicMock()
        request.app.state.ai_client = mock_client

        result = await get_ai_client(request)

        assert result is mock_client

    @pytest.mark.asyncio
    async def test_returns_none_when_cached_as_not_configured(self) -> None:
        """When ai_client is the _NOT_CONFIGURED sentinel, returns None."""
        request = MagicMock()
        request.app.state.ai_client = _NOT_CONFIGURED

        result = await get_ai_client(request)

        assert result is None

    @pytest.mark.asyncio
    async def test_creates_client_with_rate_limiter(self) -> None:
        """Verifies RateLimiter is instantiated and passed to AIClient."""
        request = MagicMock()
        request.app.state.ai_client = None

        mock_ai_instance = MagicMock()
        mock_rl_instance = MagicMock()

        with (
            patch("mitty.config.load_settings") as mock_load,
            patch(
                "mitty.ai.client.AIClient",
                return_value=mock_ai_instance,
            ) as mock_ai_cls,
            patch(
                "mitty.ai.rate_limiter.RateLimiter",
                return_value=mock_rl_instance,
            ) as mock_rl_cls,
        ):
            settings = MagicMock()
            settings.anthropic_api_key = MagicMock()
            settings.anthropic_api_key.get_secret_value.return_value = "sk-test"
            settings.anthropic_model = "claude-sonnet-4-20250514"
            settings.ai_rate_limit_rpm = 30
            settings.ai_rate_limit_tpm = 100_000
            settings.ai_budget_per_session = 1.0
            settings.ai_budget_per_day = 5.0
            mock_load.return_value = settings

            result = await get_ai_client(request)

        # Rate limiter was created with settings values
        mock_rl_cls.assert_called_once_with(
            requests_per_minute=30,
            tokens_per_minute=100_000,
        )
        # AIClient was created with the rate limiter
        mock_ai_cls.assert_called_once()
        call_kwargs = mock_ai_cls.call_args.kwargs
        assert call_kwargs["rate_limiter"] is mock_rl_instance
        assert call_kwargs["api_key"] == "sk-test"
        # Client was cached on app state
        assert request.app.state.ai_client is mock_ai_instance
        assert result is mock_ai_instance

    @pytest.mark.asyncio
    async def test_handles_creation_failure_gracefully(self) -> None:
        """When AIClient creation fails, returns None and caches sentinel."""
        request = MagicMock()
        request.app.state.ai_client = None

        with patch(
            "mitty.config.load_settings",
            side_effect=Exception("missing dep"),
        ):
            result = await get_ai_client(request)

        assert result is None
        assert request.app.state.ai_client is _NOT_CONFIGURED
