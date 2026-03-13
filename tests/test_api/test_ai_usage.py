"""Tests for the AI usage endpoint GET /ai/usage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "12345678-1234-5678-1234-567812345678"
HEADERS = {"Authorization": "Bearer test-jwt-token"}

AUDIT_ROW_COACH = {
    "call_type": "coach",
    "input_tokens": 500,
    "output_tokens": 200,
    "cost_usd": "0.00350000",
}

AUDIT_ROW_COACH_2 = {
    "call_type": "coach",
    "input_tokens": 300,
    "output_tokens": 150,
    "cost_usd": "0.00225000",
}

AUDIT_ROW_PRACTICE = {
    "call_type": "practice_generate",
    "input_tokens": 1000,
    "output_tokens": 800,
    "cost_usd": "0.00900000",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(mock_client: MagicMock) -> FastAPI:
    """Build a minimal FastAPI app with the ai_usage router."""
    from mitty.api.routers.ai_usage import router

    app = FastAPI()
    app.include_router(router)

    async def _user() -> dict[str, str]:
        return {"user_id": USER_ID, "email": "student@example.com"}

    async def _client() -> MagicMock:
        return mock_client

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_user_client] = _client

    return app


def _chain_mock(data: list) -> MagicMock:
    """Build a fluent chained mock for Supabase queries."""
    result = MagicMock()
    result.data = data

    chain = MagicMock()
    chain.execute = AsyncMock(return_value=result)
    for attr in ("select", "eq", "gte", "lte", "order", "range"):
        getattr(chain, attr).return_value = chain
    return chain


def _setup_mock(mock_client: MagicMock, audit_data: list) -> MagicMock:
    """Configure mock for ai_audit_log table and return the chain."""
    chain = _chain_mock(audit_data)
    mock_client.table = MagicMock(return_value=chain)
    return chain


# ===========================================================================
# Tests
# ===========================================================================


class TestAIUsageHappyPath:
    """GET /ai/usage returns aggregated usage."""

    def test_returns_aggregated_usage(self) -> None:
        mock_client = MagicMock()
        _setup_mock(
            mock_client,
            [AUDIT_ROW_COACH, AUDIT_ROW_COACH_2, AUDIT_ROW_PRACTICE],
        )
        app = _build_app(mock_client)

        with TestClient(app) as tc:
            resp = tc.get("/ai/usage", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 3
        assert data["total_input_tokens"] == 1800
        assert data["total_output_tokens"] == 1150
        assert data["total_cost_usd"] == pytest.approx(0.01475)

    def test_breakdown_by_call_type(self) -> None:
        mock_client = MagicMock()
        _setup_mock(
            mock_client,
            [AUDIT_ROW_COACH, AUDIT_ROW_COACH_2, AUDIT_ROW_PRACTICE],
        )
        app = _build_app(mock_client)

        with TestClient(app) as tc:
            resp = tc.get("/ai/usage", headers=HEADERS)

        assert resp.status_code == 200
        breakdown = resp.json()["breakdown"]
        assert len(breakdown) == 2

        # Sorted alphabetically by call_type
        coach = breakdown[0]
        assert coach["call_type"] == "coach"
        assert coach["calls"] == 2
        assert coach["input_tokens"] == 800
        assert coach["output_tokens"] == 350
        assert coach["cost_usd"] == pytest.approx(0.00575)

        practice = breakdown[1]
        assert practice["call_type"] == "practice_generate"
        assert practice["calls"] == 1
        assert practice["input_tokens"] == 1000
        assert practice["output_tokens"] == 800
        assert practice["cost_usd"] == pytest.approx(0.009)


class TestAIUsageEmpty:
    """GET /ai/usage with no audit rows returns zeros."""

    def test_empty_usage_returns_zeros(self) -> None:
        mock_client = MagicMock()
        _setup_mock(mock_client, [])
        app = _build_app(mock_client)

        with TestClient(app) as tc:
            resp = tc.get("/ai/usage", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 0
        assert data["total_input_tokens"] == 0
        assert data["total_output_tokens"] == 0
        assert data["total_cost_usd"] == 0.0
        assert data["breakdown"] == []


class TestAIUsageDateFiltering:
    """Verify date filters are passed to the query."""

    def test_start_date_filter(self) -> None:
        mock_client = MagicMock()
        chain = _setup_mock(mock_client, [AUDIT_ROW_COACH])
        app = _build_app(mock_client)

        with TestClient(app) as tc:
            resp = tc.get(
                "/ai/usage?start_date=2026-03-01",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        chain.gte.assert_called_once_with("created_at", "2026-03-01")

    def test_end_date_filter(self) -> None:
        mock_client = MagicMock()
        chain = _setup_mock(mock_client, [AUDIT_ROW_COACH])
        app = _build_app(mock_client)

        with TestClient(app) as tc:
            resp = tc.get(
                "/ai/usage?end_date=2026-03-31",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        chain.lte.assert_called_once_with("created_at", "2026-03-31")

    def test_both_date_filters(self) -> None:
        mock_client = MagicMock()
        chain = _setup_mock(mock_client, [AUDIT_ROW_PRACTICE])
        app = _build_app(mock_client)

        with TestClient(app) as tc:
            resp = tc.get(
                "/ai/usage?start_date=2026-03-01&end_date=2026-03-31",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        chain.gte.assert_called_once_with("created_at", "2026-03-01")
        chain.lte.assert_called_once_with("created_at", "2026-03-31")


class TestAIUsageAuth:
    """Verify auth is required."""

    def test_unauthenticated_returns_401(self) -> None:
        from mitty.api.routers.ai_usage import router

        app = FastAPI()
        app.include_router(router)

        # No dependency overrides — real auth will fail
        mock_client = MagicMock()
        app.state.supabase_admin = mock_client
        app.state.supabase_client = mock_client

        # Simulate auth failure
        mock_client.auth.get_user = AsyncMock(side_effect=Exception("JWT expired"))

        with TestClient(app) as tc:
            resp = tc.get("/ai/usage")

        assert resp.status_code == 401
