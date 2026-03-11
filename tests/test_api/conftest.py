"""Shared test fixtures for API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest


@pytest.fixture()
def mock_user() -> MagicMock:
    """A mock Supabase user object with id and email."""
    user = MagicMock()
    user.id = UUID("12345678-1234-5678-1234-567812345678")
    user.email = "student@example.com"
    return user


@pytest.fixture()
def mock_supabase_client(mock_user: MagicMock) -> AsyncMock:
    """AsyncMock Supabase client with auth.get_user configured."""
    client = AsyncMock()
    response = MagicMock()
    response.user = mock_user
    client.auth.get_user = AsyncMock(return_value=response)
    return client


@pytest.fixture()
def authenticated_headers() -> dict[str, str]:
    """Headers dict with a Bearer token for authenticated requests."""
    return {"Authorization": "Bearer test-jwt-token"}
