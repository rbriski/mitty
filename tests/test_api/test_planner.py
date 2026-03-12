"""Tests for /study-plans/generate and /study-plans/today endpoints."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.routers.study_plans import router
from mitty.planner.allocator import StudyBlock
from mitty.planner.generator import PlanGenerationError, StudyPlan

USER_A_ID = "12345678-1234-5678-1234-567812345678"
HEADERS = {"Authorization": "Bearer test-jwt-token"}

SAMPLE_PLAN_ROW = {
    "id": 42,
    "user_id": USER_A_ID,
    "plan_date": "2026-03-11",
    "total_minutes": 60,
    "status": "draft",
    "created_at": "2026-03-11T08:00:00",
    "updated_at": "2026-03-11T08:00:00",
}

SAMPLE_BLOCK_ROW = {
    "id": 100,
    "plan_id": 42,
    "block_type": "plan",
    "title": "Plan your session",
    "description": "Review today's goals",
    "target_minutes": 5,
    "actual_minutes": None,
    "course_id": None,
    "assessment_id": None,
    "sort_order": 0,
    "status": "pending",
    "started_at": None,
    "completed_at": None,
}


def _make_app(supabase_client: AsyncMock, user_id: str = USER_A_ID) -> FastAPI:
    """Create a FastAPI app with mock Supabase client and auth."""
    app = FastAPI()
    app.state.supabase_admin = supabase_client
    app.state.supabase_client = supabase_client

    mock_user = MagicMock()
    mock_user.id = UUID(user_id)
    mock_user.email = "test@example.com"
    auth_response = MagicMock()
    auth_response.user = mock_user
    supabase_client.auth.get_user = AsyncMock(return_value=auth_response)

    app.include_router(router)
    return app


def _make_chain(data: list | dict | None, count: int | None = None) -> MagicMock:
    """Create a chainable mock that returns data on execute()."""
    result = MagicMock()
    result.data = data
    result.count = count

    chain = AsyncMock()
    chain.execute = AsyncMock(return_value=result)
    chain.eq = MagicMock(return_value=chain)
    chain.gte = MagicMock(return_value=chain)
    chain.lte = MagicMock(return_value=chain)
    chain.order = MagicMock(return_value=chain)
    chain.range = MagicMock(return_value=chain)
    chain.limit = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.select = MagicMock(return_value=chain)
    chain.insert = MagicMock(return_value=chain)
    chain.update = MagicMock(return_value=chain)
    chain.delete = MagicMock(return_value=chain)
    return chain


class TestGenerateEndpoint:
    """Tests for POST /study-plans/generate."""

    @patch("mitty.api.routers.study_plans.generate_plan")
    def test_generate_returns_201_with_plan_and_blocks(
        self, mock_generate: AsyncMock, mock_supabase_client: AsyncMock
    ) -> None:
        """Successful generation returns 201 with nested blocks."""
        mock_generate.return_value = StudyPlan(
            plan_id=42,
            user_id=USER_A_ID,
            plan_date=date(2026, 3, 11),
            total_minutes=60,
            status="draft",
            blocks=[
                StudyBlock(
                    block_type="plan",
                    title="Plan your session",
                    duration_minutes=5,
                )
            ],
        )

        # After generate_plan, the endpoint reads back from DB.
        # We need table() to return different chains for different tables.
        plan_chain = _make_chain(SAMPLE_PLAN_ROW)
        blocks_chain = _make_chain([SAMPLE_BLOCK_ROW])

        call_count = 0

        def table_side_effect(name: str) -> MagicMock:
            nonlocal call_count
            if name == "study_plans":
                return plan_chain
            if name == "study_blocks":
                return blocks_chain
            # Fallback
            call_count += 1
            return _make_chain([])

        mock_supabase_client.table = MagicMock(side_effect=table_side_effect)
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post("/study-plans/generate", headers=HEADERS)

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == 42
        assert body["total_minutes"] == 60
        assert body["status"] == "draft"
        assert len(body["blocks"]) == 1
        assert body["blocks"][0]["block_type"] == "plan"

    @patch("mitty.api.routers.study_plans.generate_plan")
    def test_generate_returns_400_no_signal(
        self, mock_generate: AsyncMock, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 400 NO_SIGNAL_TODAY when no recent signal exists."""
        mock_generate.side_effect = PlanGenerationError(
            "No student signal found for user abc within 24h of 2026-03-11.",
            code="NO_SIGNAL",
        )
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post("/study-plans/generate", headers=HEADERS)

        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["code"] == "NO_SIGNAL_TODAY"

    @patch("mitty.api.routers.study_plans.generate_plan")
    def test_generate_returns_409_plan_exists(
        self, mock_generate: AsyncMock, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 409 PLAN_EXISTS when active/completed plan exists."""
        mock_generate.side_effect = PlanGenerationError(
            "A plan with status 'active' already exists for 2026-03-11 (plan_id=5).",
            code="PLAN_EXISTS",
        )
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post("/study-plans/generate", headers=HEADERS)

        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"]["code"] == "PLAN_EXISTS"

    def test_generate_returns_401_without_auth(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 401 when no auth header is provided."""
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post("/study-plans/generate")

        assert resp.status_code == 401

    @patch("mitty.api.routers.study_plans.generate_plan")
    def test_generate_returns_500_on_unexpected_error(
        self, mock_generate: AsyncMock, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 500 GENERATION_FAILED on unexpected PlanGenerationError."""
        mock_generate.side_effect = PlanGenerationError(
            "Failed to read assignments: connection reset"
        )
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post("/study-plans/generate", headers=HEADERS)

        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"]["code"] == "GENERATION_FAILED"

    @patch("mitty.api.routers.study_plans.generate_plan")
    def test_generate_silently_replaces_draft(
        self, mock_generate: AsyncMock, mock_supabase_client: AsyncMock
    ) -> None:
        """Draft plans are silently replaced (generate_plan handles this)."""
        # generate_plan handles draft replacement internally — no error raised.
        mock_generate.return_value = StudyPlan(
            plan_id=99,
            user_id=USER_A_ID,
            plan_date=date(2026, 3, 11),
            total_minutes=45,
            status="draft",
            blocks=[],
        )

        new_plan_row = {**SAMPLE_PLAN_ROW, "id": 99, "total_minutes": 45}
        plan_chain = _make_chain(new_plan_row)
        blocks_chain = _make_chain([])

        def table_side_effect(name: str) -> MagicMock:
            if name == "study_plans":
                return plan_chain
            return blocks_chain

        mock_supabase_client.table = MagicMock(side_effect=table_side_effect)
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post("/study-plans/generate", headers=HEADERS)

        assert resp.status_code == 201
        assert resp.json()["id"] == 99


class TestTodayEndpoint:
    """Tests for GET /study-plans/today."""

    def test_today_returns_200_with_plan_and_blocks(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 200 with plan + nested blocks when today's plan exists."""
        plan_chain = _make_chain([SAMPLE_PLAN_ROW])
        blocks_chain = _make_chain([SAMPLE_BLOCK_ROW])

        def table_side_effect(name: str) -> MagicMock:
            if name == "study_plans":
                return plan_chain
            return blocks_chain

        mock_supabase_client.table = MagicMock(side_effect=table_side_effect)
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/today", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 42
        assert len(body["blocks"]) == 1
        assert body["blocks"][0]["title"] == "Plan your session"

    def test_today_returns_404_when_no_plan(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 404 NOT_FOUND when no plan exists for today."""
        plan_chain = _make_chain([])

        mock_supabase_client.table = MagicMock(return_value=plan_chain)
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/today", headers=HEADERS)

        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["code"] == "NOT_FOUND"

    def test_today_returns_401_without_auth(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns 401 when no auth header is provided."""
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/today")

        assert resp.status_code == 401

    def test_today_returns_plan_with_empty_blocks(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """Returns plan with empty blocks list when no blocks exist."""
        plan_chain = _make_chain([SAMPLE_PLAN_ROW])
        blocks_chain = _make_chain([])

        def table_side_effect(name: str) -> MagicMock:
            if name == "study_plans":
                return plan_chain
            return blocks_chain

        mock_supabase_client.table = MagicMock(side_effect=table_side_effect)
        mock_supabase_client.postgrest = MagicMock()
        mock_supabase_client.postgrest.auth = MagicMock()

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/today", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["blocks"] == []
