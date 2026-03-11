"""Gap coverage tests for API endpoints, auth, config, pagination, and validation.

Covers edge cases not addressed by the per-router TDD test files:
- Pagination edge cases (custom offset/limit, empty results, boundary values)
- Input validation at the endpoint level (missing fields, invalid types)
- Error response format from wrapped HTTPException handler
- Empty update body returning 400 for routers that enforce it
- User isolation for user-scoped routers (delete filters, update filters)
- Config: public read / auth-required write edge cases
- Auth middleware message content validation
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_supabase_client

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_A_ID = "12345678-1234-5678-1234-567812345678"
USER_B_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

SAMPLE_ASSESSMENT = {
    "id": 1,
    "course_id": 10,
    "name": "Midterm Exam",
    "assessment_type": "test",
    "scheduled_date": "2026-03-15T10:00:00",
    "weight": 0.3,
    "unit_or_topic": "Algebra",
    "description": "Covers chapters 1-5",
    "canvas_assignment_id": 42,
    "created_at": "2026-03-01T00:00:00",
    "updated_at": "2026-03-01T00:00:00",
}

SAMPLE_RESOURCE = {
    "id": 1,
    "course_id": 10,
    "title": "Chapter 5: Polynomials",
    "resource_type": "textbook_chapter",
    "source_url": "https://example.com/ch5.pdf",
    "canvas_module_id": 77,
    "sort_order": 5,
    "created_at": "2026-03-01T00:00:00",
    "updated_at": "2026-03-01T00:00:00",
}

SAMPLE_SIGNAL = {
    "id": 1,
    "user_id": USER_A_ID,
    "recorded_at": "2026-03-11T08:00:00",
    "available_minutes": 60,
    "confidence_level": 3,
    "energy_level": 4,
    "stress_level": 2,
    "blockers": None,
    "preferences": None,
    "notes": None,
}

SAMPLE_PLAN = {
    "id": 1,
    "user_id": USER_A_ID,
    "plan_date": "2026-03-11",
    "total_minutes": 120,
    "status": "draft",
    "created_at": "2026-03-11T08:00:00",
    "updated_at": "2026-03-11T08:00:00",
}

SAMPLE_MASTERY = {
    "id": 1,
    "user_id": USER_A_ID,
    "course_id": 10,
    "concept": "Algebra",
    "mastery_level": 0.7,
    "confidence_self_report": 0.5,
    "last_retrieval_at": None,
    "next_review_at": None,
    "retrieval_count": 3,
    "success_rate": 0.8,
    "updated_at": "2025-01-01T00:00:00",
}

SAMPLE_PRACTICE = {
    "id": 1,
    "user_id": USER_A_ID,
    "study_block_id": 5,
    "course_id": 10,
    "concept": "Quadratics",
    "practice_type": "quiz",
    "question_text": "Solve x^2 + 2x + 1 = 0",
    "student_answer": "x = -1",
    "correct_answer": "x = -1",
    "is_correct": True,
    "confidence_before": 3.0,
    "time_spent_seconds": 120,
    "created_at": "2025-01-01T00:00:00",
}

SAMPLE_CONFIG = {
    "id": 1,
    "current_term_name": "Spring 2025",
    "privilege_thresholds": [90, 80, 70],
    "privilege_names": ["Gold", "Silver", "Bronze"],
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T00:00:00",
}

SAMPLE_BLOCK = {
    "id": 1,
    "plan_id": 10,
    "block_type": "plan",
    "title": "Review chapter 5",
    "description": None,
    "target_minutes": 30,
    "actual_minutes": None,
    "course_id": None,
    "assessment_id": None,
    "sort_order": 1,
    "status": "pending",
    "started_at": None,
    "completed_at": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
    monkeypatch.setenv("CANVAS_TOKEN", "test-token")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("FASTAPI_DEBUG", raising=False)


@pytest.fixture()
def full_app_client(
    _mock_env: None,
    mock_supabase_client: AsyncMock,
) -> Generator[TestClient]:
    """TestClient using the real create_app (full exception handler)."""
    from mitty.api.app import create_app

    app = create_app()
    mock_supabase_client.table = MagicMock()
    with TestClient(app) as tc:
        app.state.supabase_client = mock_supabase_client
        yield tc


def _make_user_scoped_app(
    router_module: str,
    supabase_client: AsyncMock,
    user_id: str = USER_A_ID,
) -> FastAPI:
    """Build a minimal app with the given router and mocked auth user."""
    import importlib

    mod = importlib.import_module(f"mitty.api.routers.{router_module}")
    app = FastAPI()
    app.state.supabase_client = supabase_client

    mock_user = MagicMock()
    mock_user.id = UUID(user_id)
    mock_user.email = "test@example.com"
    auth_response = MagicMock()
    auth_response.user = mock_user
    supabase_client.auth.get_user = AsyncMock(return_value=auth_response)

    app.include_router(mod.router)
    return app


def _mock_chain(
    client: AsyncMock,
    data: list | dict | None,
    count: int | None = None,
) -> None:
    """Configure the mock's chained Supabase query to return given data."""
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
    chain.maybe_single = MagicMock(return_value=chain)
    chain.single = MagicMock(return_value=chain)
    chain.select = MagicMock(return_value=chain)
    chain.insert = MagicMock(return_value=chain)
    chain.upsert = MagicMock(return_value=chain)
    chain.update = MagicMock(return_value=chain)
    chain.delete = MagicMock(return_value=chain)

    client.table = MagicMock(return_value=chain)


def _chain_mock_dep(data: list | dict, count: int | None = None) -> MagicMock:
    """Build a fluent chained mock for dependency-override style tests."""
    result = MagicMock()
    result.data = data if isinstance(data, list) else [data]
    result.count = count
    terminal = AsyncMock(return_value=result)

    chain = MagicMock()
    chain.execute = terminal
    for attr in (
        "select",
        "insert",
        "upsert",
        "update",
        "delete",
        "eq",
        "order",
        "range",
    ):
        getattr(chain, attr).return_value = chain
    return chain


HEADERS = {"Authorization": "Bearer test-jwt-token"}


# ===========================================================================
# 1. Error response format validation
# ===========================================================================


class TestErrorResponseFormat:
    """Verify the global HTTPException handler wraps errors in ErrorDetail format."""

    def test_404_from_router_has_error_wrapper(
        self,
        full_app_client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        """A 404 raised by a router is wrapped in {error: {code, message, detail}}."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=None))

        response = full_app_client.get(
            "/assessments/999", headers=authenticated_headers
        )

        assert response.status_code == 404
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "404"

    def test_401_from_auth_has_error_wrapper(
        self,
        full_app_client: TestClient,
    ) -> None:
        """A 401 from missing auth is wrapped in the standard error format."""
        response = full_app_client.get("/assessments/1")

        assert response.status_code == 401
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "401"

    def test_422_validation_error_format(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """FastAPI 422 validation errors have the expected structure."""
        response = full_app_client.post(
            "/assessments/",
            json={},  # missing required fields
            headers=authenticated_headers,
        )

        assert response.status_code == 422
        body = response.json()
        # FastAPI 422 uses its own format with "detail" as a list
        assert "detail" in body


# ===========================================================================
# 2. Pagination edge cases
# ===========================================================================


class TestPaginationEdgeCases:
    """Test custom offset/limit, empty results, and boundary values."""

    def test_custom_offset_and_limit(
        self,
        full_app_client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        """Passing offset=10&limit=5 returns those values in the response."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[], count=0))

        response = full_app_client.get(
            "/assessments/?offset=10&limit=5",
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["offset"] == 10
        assert body["limit"] == 5
        assert body["data"] == []
        assert body["total"] == 0

    def test_empty_list_returns_zero_total(
        self,
        full_app_client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        """An empty table returns total=0 with an empty data list."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[], count=0))

        response = full_app_client.get(
            "/resources/",
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["data"] == []

    def test_negative_offset_rejected(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """offset < 0 is rejected with 422."""
        response = full_app_client.get(
            "/assessments/?offset=-1",
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_zero_limit_rejected(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """limit=0 (below ge=1) is rejected with 422."""
        response = full_app_client.get(
            "/assessments/?limit=0",
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_limit_above_max_rejected(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """limit above router max (200 for assessments) is rejected with 422."""
        response = full_app_client.get(
            "/assessments/?limit=201",
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_null_count_treated_as_zero(
        self,
        full_app_client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        """If Supabase returns count=None, total should be 0."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[], count=None))

        response = full_app_client.get(
            "/assessments/",
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        assert response.json()["total"] == 0


# ===========================================================================
# 3. Input validation at endpoint level
# ===========================================================================


class TestInputValidation:
    """Test missing required fields and invalid data types at the endpoint level."""

    def test_create_assessment_missing_required_fields(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """POST /assessments/ with empty body returns 422."""
        response = full_app_client.post(
            "/assessments/",
            json={},
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_create_assessment_invalid_type(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """POST with invalid assessment_type returns 422."""
        response = full_app_client.post(
            "/assessments/",
            json={
                "course_id": 10,
                "name": "Test",
                "assessment_type": "invalid_type",
            },
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_create_resource_missing_required_fields(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """POST /resources/ with missing title returns 422."""
        response = full_app_client.post(
            "/resources/",
            json={"course_id": 10},
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_create_resource_invalid_type(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """POST with invalid resource_type returns 422."""
        response = full_app_client.post(
            "/resources/",
            json={
                "course_id": 10,
                "title": "Test",
                "resource_type": "podcast",
            },
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_create_resource_chunk_missing_fields(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """POST /resource-chunks/ with partial data returns 422."""
        response = full_app_client.post(
            "/resource-chunks/",
            json={"resource_id": 5},
            headers=authenticated_headers,
        )
        assert response.status_code == 422

    def test_create_assessment_wrong_data_types(
        self,
        full_app_client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """POST with course_id as string instead of int returns 422."""
        response = full_app_client.post(
            "/assessments/",
            json={
                "course_id": "not_a_number",
                "name": "Test",
                "assessment_type": "test",
            },
            headers=authenticated_headers,
        )
        assert response.status_code == 422


# ===========================================================================
# 4. Empty update body returns 400 for user-scoped routers
# ===========================================================================


class TestEmptyUpdateBody:
    """Routers that check for empty update payloads should return 400."""

    def test_student_signal_empty_update_returns_400(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_SIGNAL])
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.put(
                "/student-signals/1",
                json={},
                headers=HEADERS,
            )
        assert resp.status_code == 400

    def test_study_plan_empty_update_returns_400(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN])
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.put(
                "/study-plans/1",
                json={},
                headers=HEADERS,
            )
        assert resp.status_code == 400

    def test_study_block_empty_update_returns_400(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        """Study blocks verify ownership first, then check for empty body."""
        # First call: ownership check (returns a block with join data)
        block_with_join = {
            **SAMPLE_BLOCK,
            "study_plans": {"user_id": USER_A_ID},
        }
        ownership_result = MagicMock()
        ownership_result.data = block_with_join
        ownership_chain = AsyncMock()
        ownership_chain.execute = AsyncMock(return_value=ownership_result)
        ownership_chain.eq = MagicMock(return_value=ownership_chain)
        ownership_chain.select = MagicMock(return_value=ownership_chain)
        ownership_chain.maybe_single = MagicMock(return_value=ownership_chain)

        mock_supabase_client.table = MagicMock(return_value=ownership_chain)
        app = _make_user_scoped_app("study_blocks", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.put(
                "/study-blocks/1",
                json={},
                headers=HEADERS,
            )
        assert resp.status_code == 400


# ===========================================================================
# 5. User isolation — delete and update filter by user_id
# ===========================================================================


class TestUserIsolationStudentSignals:
    """Verify user_id filter on delete and update for student_signals."""

    def test_delete_filters_by_user_id(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_SIGNAL])
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            tc.delete("/student-signals/1", headers=HEADERS)
        chain = mock_supabase_client.table.return_value
        eq_calls = [c for c in chain.eq.call_args_list if c[0][0] == "user_id"]
        assert len(eq_calls) >= 1
        assert eq_calls[0][0][1] == USER_A_ID

    def test_update_filters_by_user_id(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        updated = {**SAMPLE_SIGNAL, "available_minutes": 90}
        _mock_chain(mock_supabase_client, [updated])
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            tc.put(
                "/student-signals/1",
                json={"available_minutes": 90},
                headers=HEADERS,
            )
        chain = mock_supabase_client.table.return_value
        eq_calls = [c for c in chain.eq.call_args_list if c[0][0] == "user_id"]
        assert len(eq_calls) >= 1
        assert eq_calls[0][0][1] == USER_A_ID


class TestUserIsolationStudyPlans:
    """Verify user_id filter on delete for study_plans."""

    def test_delete_filters_by_user_id(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN])
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            tc.delete("/study-plans/1", headers=HEADERS)
        chain = mock_supabase_client.table.return_value
        eq_calls = [c for c in chain.eq.call_args_list if c[0][0] == "user_id"]
        assert len(eq_calls) >= 1
        assert eq_calls[0][0][1] == USER_A_ID

    def test_update_filters_by_user_id(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        updated = {**SAMPLE_PLAN, "total_minutes": 90}
        _mock_chain(mock_supabase_client, [updated])
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            tc.put(
                "/study-plans/1",
                json={"total_minutes": 90},
                headers=HEADERS,
            )
        chain = mock_supabase_client.table.return_value
        eq_calls = [c for c in chain.eq.call_args_list if c[0][0] == "user_id"]
        assert len(eq_calls) >= 1
        assert eq_calls[0][0][1] == USER_A_ID


class TestUserIsolationPracticeResults:
    """Verify user_id filter on delete for practice_results."""

    def test_delete_filters_by_user_id(self) -> None:
        from mitty.api.routers.practice_results import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        chain = _chain_mock_dep(SAMPLE_PRACTICE)
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            tc.delete("/practice-results/1")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_A_ID) for call in eq_calls)

    def test_update_filters_by_user_id(self) -> None:
        from mitty.api.routers.practice_results import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        updated = {**SAMPLE_PRACTICE, "is_correct": False}
        chain = _chain_mock_dep(updated)
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            tc.put("/practice-results/1", json={"is_correct": False})

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_A_ID) for call in eq_calls)


class TestUserIsolationMasteryStates:
    """Verify user_id filter on update for mastery_states."""

    def test_update_filters_by_user_id(self) -> None:
        from mitty.api.routers.mastery_states import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        updated = {**SAMPLE_MASTERY, "mastery_level": 0.9}
        chain = _chain_mock_dep(updated)
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            tc.put("/mastery-states/1", json={"mastery_level": 0.9})

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_A_ID) for call in eq_calls)


# ===========================================================================
# 6. Config: public read / auth-required write
# ===========================================================================


class TestConfigAuthBehavior:
    """Expanded config auth tests."""

    def test_get_config_works_without_auth_header(self) -> None:
        """GET /config/ should succeed with no auth header at all."""
        from mitty.api.routers.config import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_supabase_client] = _client

        result = MagicMock()
        result.data = SAMPLE_CONFIG
        chain = MagicMock()
        chain.execute = AsyncMock(return_value=result)
        for attr in ("select", "eq", "single"):
            getattr(chain, attr).return_value = chain
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            response = tc.get("/config/")

        assert response.status_code == 200
        assert response.json()["current_term_name"] == "Spring 2025"

    def test_put_config_without_auth_returns_401(
        self,
        full_app_client: TestClient,
    ) -> None:
        """PUT /config/ without auth returns 401."""
        response = full_app_client.put(
            "/config/",
            json={"current_term_name": "Fall 2025"},
        )
        assert response.status_code == 401

    def test_put_config_with_auth_succeeds(self) -> None:
        """PUT /config/ with auth and valid data succeeds."""
        from mitty.api.routers.config import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        updated = {**SAMPLE_CONFIG, "current_term_name": "Fall 2025"}
        result = MagicMock()
        result.data = [updated]
        chain = MagicMock()
        chain.execute = AsyncMock(return_value=result)
        for attr in ("select", "update", "eq", "single"):
            getattr(chain, attr).return_value = chain
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            response = tc.put(
                "/config/",
                json={"current_term_name": "Fall 2025"},
            )

        assert response.status_code == 200
        assert response.json()["current_term_name"] == "Fall 2025"


# ===========================================================================
# 7. Auth middleware — message content validation
# ===========================================================================


class TestAuthMessageContent:
    """Validate that auth error messages are specific and helpful."""

    def _create_test_app(self, supabase_client: AsyncMock | None) -> FastAPI:
        from fastapi import Depends

        app = FastAPI()
        app.state.supabase_client = supabase_client

        @app.get("/protected")
        async def protected(
            user: dict = Depends(get_current_user),  # noqa: B008
        ):
            return {"user_id": user["user_id"]}

        return app

    def test_missing_header_message_contains_missing(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        app = self._create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/protected")
        body = resp.json()
        assert "Missing" in body["detail"]["message"]

    def test_basic_auth_message_contains_malformed(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        app = self._create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/protected",
                headers={"Authorization": "Basic abc123"},
            )
        body = resp.json()
        assert "Malformed" in body["detail"]["message"]

    def test_empty_token_message_contains_empty(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        app = self._create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/protected",
                headers={"Authorization": "Bearer   "},
            )
        body = resp.json()
        assert "empty" in body["detail"]["message"].lower()

    def test_no_client_message_contains_unavailable(
        self,
        authenticated_headers: dict[str, str],
    ) -> None:
        app = self._create_test_app(supabase_client=None)
        with TestClient(app) as tc:
            resp = tc.get("/protected", headers=authenticated_headers)
        body = resp.json()
        assert "unavailable" in body["detail"]["message"].lower()

    def test_expired_token_message_contains_invalid_or_expired(
        self,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_supabase_client.auth.get_user = AsyncMock(
            side_effect=Exception("JWT expired")
        )
        app = self._create_test_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/protected", headers=authenticated_headers)
        body = resp.json()
        msg = body["detail"]["message"].lower()
        assert "invalid" in msg or "expired" in msg


# ===========================================================================
# 8. Pagination for user-scoped routers
# ===========================================================================


class TestUserScopedPagination:
    """Test custom pagination params for user-scoped routers."""

    def test_student_signals_custom_limit(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [], count=0)
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/student-signals/?offset=5&limit=10", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == 5
        assert body["limit"] == 10

    def test_study_plans_custom_limit(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [], count=0)
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/?offset=0&limit=5", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 5

    def test_mastery_states_custom_pagination(self) -> None:
        from mitty.api.routers.mastery_states import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        chain = _chain_mock_dep([], count=0)
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=0))
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            resp = tc.get("/mastery-states/?offset=20&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == 20
        assert body["limit"] == 10

    def test_practice_results_custom_pagination(self) -> None:
        from mitty.api.routers.practice_results import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        chain = _chain_mock_dep([], count=0)
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=0))
        mock_client.table.return_value = chain

        with TestClient(app) as tc:
            resp = tc.get("/practice-results/?offset=5&limit=25")
        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == 5
        assert body["limit"] == 25


# ===========================================================================
# 9. Limit boundary validation for user-scoped routers
# ===========================================================================


class TestLimitBoundaryUserScoped:
    """Validate limit max boundary for user-scoped routers."""

    def test_student_signals_limit_above_max_rejected(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        """Student signals max limit is 100."""
        _mock_chain(mock_supabase_client, [], count=0)
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/student-signals/?limit=101", headers=HEADERS)
        assert resp.status_code == 422

    def test_study_plans_limit_above_max_rejected(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        """Study plans max limit is 100."""
        _mock_chain(mock_supabase_client, [], count=0)
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/?limit=101", headers=HEADERS)
        assert resp.status_code == 422

    def test_mastery_states_limit_above_max_rejected(self) -> None:
        """Mastery states max limit is 100."""
        from mitty.api.routers.mastery_states import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        with TestClient(app) as tc:
            resp = tc.get("/mastery-states/?limit=101")
        assert resp.status_code == 422

    def test_practice_results_limit_above_max_rejected(self) -> None:
        """Practice results max limit is 100."""
        from mitty.api.routers.practice_results import router

        mock_client = MagicMock()
        app = FastAPI()
        app.include_router(router)

        async def _user() -> dict[str, str]:
            return {"user_id": USER_A_ID, "email": "student@example.com"}

        async def _client() -> MagicMock:
            return mock_client

        app.dependency_overrides[get_current_user] = _user
        app.dependency_overrides[get_supabase_client] = _client

        with TestClient(app) as tc:
            resp = tc.get("/practice-results/?limit=101")
        assert resp.status_code == 422


# ===========================================================================
# 10. Student signals validation at endpoint level
# ===========================================================================


class TestStudentSignalEndpointValidation:
    """Validate that student_signals endpoint rejects bad data."""

    def test_create_signal_missing_required_fields(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [])
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/student-signals/",
                json={"available_minutes": 60},  # missing confidence etc.
                headers=HEADERS,
            )
        assert resp.status_code == 422

    def test_create_signal_confidence_out_of_range(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [])
        app = _make_user_scoped_app("student_signals", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/student-signals/",
                json={
                    "user_id": USER_A_ID,
                    "available_minutes": 60,
                    "confidence_level": 0,  # below min of 1
                    "energy_level": 3,
                    "stress_level": 3,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 422


# ===========================================================================
# 11. Study plan validation at endpoint level
# ===========================================================================


class TestStudyPlanEndpointValidation:
    """Validate that study_plans endpoint rejects bad data."""

    def test_create_plan_missing_required_fields(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [])
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-plans/",
                json={"user_id": USER_A_ID},  # missing plan_date, total_minutes
                headers=HEADERS,
            )
        assert resp.status_code == 422

    def test_create_plan_invalid_status(
        self,
        mock_supabase_client: AsyncMock,
    ) -> None:
        _mock_chain(mock_supabase_client, [])
        app = _make_user_scoped_app("study_plans", mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-plans/",
                json={
                    "user_id": USER_A_ID,
                    "plan_date": "2026-03-11",
                    "total_minutes": 90,
                    "status": "cancelled",  # invalid literal
                },
                headers=HEADERS,
            )
        assert resp.status_code == 422
