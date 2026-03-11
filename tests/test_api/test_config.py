"""Tests for app_config CRUD router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_supabase_client, get_user_client
from mitty.api.routers.config import router

USER_ID = "12345678-1234-5678-1234-567812345678"

SAMPLE_CONFIG = {
    "id": 1,
    "current_term_name": "Spring 2025",
    "privilege_thresholds": [90, 80, 70],
    "privilege_names": ["Gold", "Silver", "Bronze"],
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00",
}


@pytest.fixture()
def mock_client() -> MagicMock:
    return MagicMock()


def _make_app(mock_client: MagicMock, *, with_auth: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _client() -> MagicMock:
        return mock_client

    app.dependency_overrides[get_supabase_client] = _client

    if with_auth:

        async def _user() -> dict[str, str]:
            return {"user_id": USER_ID, "email": "student@example.com"}

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_user_client] = _client

    return app


def _chain_mock(data: dict) -> MagicMock:
    """Build a fluent chained mock for config (single row via .single())."""
    result = MagicMock()
    result.data = data
    terminal = AsyncMock(return_value=result)

    chain = MagicMock()
    chain.execute = terminal
    for attr in ("select", "update", "eq", "single"):
        getattr(chain, attr).return_value = chain
    return chain


def _chain_mock_list(data: dict) -> MagicMock:
    """Build a fluent chained mock that returns data as a list (for update)."""
    result = MagicMock()
    result.data = [data]
    terminal = AsyncMock(return_value=result)

    chain = MagicMock()
    chain.execute = terminal
    for attr in ("select", "update", "eq", "single"):
        getattr(chain, attr).return_value = chain
    return chain


class TestGetConfig:
    def test_get_returns_config_without_auth(self, mock_client: MagicMock) -> None:
        """GET /config/ is public -- no auth required."""
        app = _make_app(mock_client, with_auth=False)
        client = TestClient(app)
        chain = _chain_mock(SAMPLE_CONFIG)
        mock_client.table.return_value = chain

        response = client.get("/config/")

        assert response.status_code == 200
        body = response.json()
        assert body["current_term_name"] == "Spring 2025"
        assert body["id"] == 1

    def test_get_calls_single(self, mock_client: MagicMock) -> None:
        app = _make_app(mock_client, with_auth=False)
        client = TestClient(app)
        chain = _chain_mock(SAMPLE_CONFIG)
        mock_client.table.return_value = chain

        client.get("/config/")

        chain.single.assert_called_once()
        chain.eq.assert_called_once_with("id", 1)


class TestUpdateConfig:
    def test_update_requires_auth(self, mock_client: MagicMock) -> None:
        """PUT /config/ without auth should fail."""
        app = _make_app(mock_client, with_auth=False)
        client = TestClient(app)

        response = client.put(
            "/config/",
            json={"current_term_name": "Fall 2025"},
        )

        # Without auth override, get_current_user will fail
        assert response.status_code == 401

    def test_update_returns_updated_config(self, mock_client: MagicMock) -> None:
        app = _make_app(mock_client, with_auth=True)
        client = TestClient(app)
        updated = {**SAMPLE_CONFIG, "current_term_name": "Fall 2025"}
        chain = _chain_mock_list(updated)
        mock_client.table.return_value = chain

        response = client.put(
            "/config/",
            json={"current_term_name": "Fall 2025"},
        )

        assert response.status_code == 200
        assert response.json()["current_term_name"] == "Fall 2025"

    def test_update_empty_body_returns_current(self, mock_client: MagicMock) -> None:
        """Empty update should return the current config without modifying."""
        app = _make_app(mock_client, with_auth=True)
        client = TestClient(app)
        chain = _chain_mock(SAMPLE_CONFIG)
        mock_client.table.return_value = chain

        response = client.put("/config/", json={})

        assert response.status_code == 200
        body = response.json()
        assert body["current_term_name"] == "Spring 2025"
        # Should have called select+single, not update
        chain.single.assert_called()
