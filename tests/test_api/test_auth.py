"""Tests for the get_current_user auth dependency."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user


def _create_test_app(supabase_client: AsyncMock | None) -> FastAPI:
    """Build a minimal FastAPI app with a protected endpoint."""
    app = FastAPI()
    app.state.supabase_admin = supabase_client

    @app.get("/protected")
    async def protected(user: dict = Depends(get_current_user)):  # noqa: B008
        return {"user_id": user["user_id"], "email": user["email"]}

    return app


class TestGetCurrentUserValid:
    """Valid token returns the authenticated user."""

    def test_valid_token_returns_user(
        self,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        app = _create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            response = tc.get("/protected", headers=authenticated_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == "12345678-1234-5678-1234-567812345678"
        assert body["email"] == "student@example.com"
        mock_supabase_client.auth.get_user.assert_called_once_with("test-jwt-token")


class TestGetCurrentUserMissingHeader:
    """Missing Authorization header returns 401."""

    def test_missing_auth_header_returns_401(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        app = _create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            response = tc.get("/protected")

        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "401"
        assert "missing" in body["detail"]["message"].lower()


class TestGetCurrentUserMalformedHeader:
    """Malformed Authorization header (no Bearer prefix) returns 401."""

    @pytest.mark.parametrize(
        "auth_value",
        [
            "Basic abc123",
            "token-without-prefix",
            "Bearer",
            "Bearer ",
        ],
    )
    def test_malformed_header_returns_401(
        self,
        mock_supabase_client: AsyncMock,
        auth_value: str,
    ) -> None:
        app = _create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            response = tc.get("/protected", headers={"Authorization": auth_value})

        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "401"


class TestGetCurrentUserInvalidToken:
    """Invalid/expired token (Supabase returns error) returns 401."""

    def test_invalid_token_returns_401(
        self,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_supabase_client.auth.get_user = AsyncMock(
            side_effect=Exception("Invalid JWT")
        )
        app = _create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            response = tc.get("/protected", headers=authenticated_headers)

        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "401"

    def test_null_user_returns_401(
        self,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        response_obj = MagicMock()
        response_obj.user = None
        mock_supabase_client.auth.get_user = AsyncMock(return_value=response_obj)

        app = _create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            response = tc.get("/protected", headers=authenticated_headers)

        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "401"


class TestGetCurrentUserSupabaseError:
    """Supabase client network failure returns 401."""

    def test_network_error_returns_401(
        self,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_supabase_client.auth.get_user = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        app = _create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            response = tc.get("/protected", headers=authenticated_headers)

        assert response.status_code == 401
        body = response.json()
        assert body["detail"]["code"] == "401"

    def test_no_supabase_client_returns_401(
        self,
        authenticated_headers: dict[str, str],
    ) -> None:
        app = _create_test_app(supabase_client=None)
        with TestClient(app) as tc:
            response = tc.get("/protected", headers=authenticated_headers)

        assert response.status_code == 401
