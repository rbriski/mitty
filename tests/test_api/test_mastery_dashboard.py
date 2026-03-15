"""Tests for the mastery dashboard API and page route."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "12345678-1234-5678-1234-567812345678"
HEADERS = {"Authorization": "Bearer test-jwt-token"}

MASTERY_WELL_CALIBRATED = {
    "id": 1,
    "user_id": USER_ID,
    "course_id": 10,
    "concept": "Algebra",
    "mastery_level": 0.7,
    "confidence_self_report": 0.8,
    "last_retrieval_at": "2026-03-10T10:00:00",
    "next_review_at": "2026-03-15T10:00:00",
    "retrieval_count": 5,
    "success_rate": 0.8,
    "updated_at": "2026-03-10T10:00:00",
}

MASTERY_OVER_CONFIDENT = {
    "id": 2,
    "user_id": USER_ID,
    "course_id": 10,
    "concept": "Geometry",
    "mastery_level": 0.4,
    "confidence_self_report": 0.9,
    "last_retrieval_at": "2026-03-09T10:00:00",
    "next_review_at": "2026-03-12T10:00:00",
    "retrieval_count": 3,
    "success_rate": 0.5,
    "updated_at": "2026-03-09T10:00:00",
}

MASTERY_UNDER_CONFIDENT = {
    "id": 3,
    "user_id": USER_ID,
    "course_id": 10,
    "concept": "Calculus",
    "mastery_level": 0.9,
    "confidence_self_report": 0.5,
    "last_retrieval_at": "2026-03-08T10:00:00",
    "next_review_at": "2026-03-20T10:00:00",
    "retrieval_count": 10,
    "success_rate": 0.95,
    "updated_at": "2026-03-08T10:00:00",
}

MASTERY_NO_CONFIDENCE = {
    "id": 4,
    "user_id": USER_ID,
    "course_id": 10,
    "concept": "Statistics",
    "mastery_level": 0.5,
    "confidence_self_report": None,
    "last_retrieval_at": None,
    "next_review_at": None,
    "retrieval_count": 0,
    "success_rate": None,
    "updated_at": "2026-03-07T10:00:00",
}

RESOURCE_ALGEBRA = {
    "id": 1,
    "course_id": 10,
    "title": "Algebra Notes",
    "resource_type": "notes",
}

RESOURCE_GEOMETRY = {
    "id": 2,
    "course_id": 10,
    "title": "Geometry Guide",
    "resource_type": "textbook_chapter",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(
    mock_client: MagicMock,
    user_id: str = USER_ID,
) -> FastAPI:
    """Build a minimal FastAPI app with the mastery_dashboard router."""
    from mitty.api.routers.mastery_dashboard import router

    app = FastAPI()
    app.include_router(router)

    async def _user() -> dict[str, str]:
        return {"user_id": user_id, "email": "student@example.com"}

    async def _client() -> MagicMock:
        return mock_client

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_user_client] = _client

    return app


def _chain_mock(
    data: list,
    count: int | None = None,
) -> MagicMock:
    """Build a fluent chained mock for Supabase queries."""
    result = MagicMock()
    result.data = data
    result.count = count

    chain = MagicMock()
    chain.execute = AsyncMock(return_value=result)
    for attr in (
        "select",
        "eq",
        "order",
        "range",
        "in_",
        "limit",
        "gt",
        "gte",
        "lt",
        "lte",
    ):
        getattr(chain, attr).return_value = chain
    return chain


def _setup_two_table_mock(
    mock_client: MagicMock,
    mastery_data: list,
    resource_data: list,
) -> None:
    """Configure mock for mastery_states and resources tables."""
    mastery_chain = _chain_mock(mastery_data)
    resource_chain = _chain_mock(resource_data)

    def table_router(name: str) -> MagicMock:
        if name == "mastery_states":
            return mastery_chain
        if name == "resources":
            return resource_chain
        return _chain_mock([])

    mock_client.table = MagicMock(side_effect=table_router)


# ===========================================================================
# API endpoint tests: GET /mastery-dashboard/{course_id}
# ===========================================================================


class TestMasteryDashboardCalibrationStatus:
    """Verify calibration_status is computed correctly."""

    def test_well_calibrated(self) -> None:
        """Gap <= 0.2 and >= -0.2 => well_calibrated."""
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_WELL_CALIBRATED],
            [RESOURCE_ALGEBRA],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["concepts"]) == 1
        concept = data["concepts"][0]
        assert concept["calibration_status"] == "well_calibrated"

    def test_over_confident(self) -> None:
        """confidence - mastery > 0.2 => over_confident."""
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_OVER_CONFIDENT],
            [RESOURCE_GEOMETRY],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        concept = resp.json()["concepts"][0]
        assert concept["calibration_status"] == "over_confident"
        assert concept["calibration_gap"] == pytest.approx(0.5)

    def test_under_confident(self) -> None:
        """confidence - mastery < -0.2 => under_confident."""
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_UNDER_CONFIDENT],
            [],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        concept = resp.json()["concepts"][0]
        assert concept["calibration_status"] == "under_confident"
        assert concept["calibration_gap"] == pytest.approx(-0.4)

    def test_no_confidence_report_returns_unknown(self) -> None:
        """When confidence_self_report is None, calibration_status is 'unknown'."""
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_NO_CONFIDENCE],
            [],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        concept = resp.json()["concepts"][0]
        assert concept["calibration_status"] == "unknown"
        assert concept["calibration_gap"] is None


class TestMasteryDashboardSorting:
    """Verify sort_by parameter works correctly."""

    def _get_sorted(self, sort_by: str, mastery_data: list | None = None) -> list[dict]:
        mock_client = MagicMock()
        data = mastery_data or [
            MASTERY_WELL_CALIBRATED,
            MASTERY_OVER_CONFIDENT,
            MASTERY_UNDER_CONFIDENT,
        ]
        _setup_two_table_mock(mock_client, data, [RESOURCE_ALGEBRA])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                f"/mastery-dashboard/10?sort_by={sort_by}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        return resp.json()["concepts"]

    def test_sort_by_mastery_level(self) -> None:
        concepts = self._get_sorted("mastery_level")
        levels = [c["mastery_level"] for c in concepts]
        assert levels == sorted(levels)

    def test_sort_by_next_review_at(self) -> None:
        concepts = self._get_sorted("next_review_at")
        # None values should sort last
        dates = [c["next_review_at"] for c in concepts]
        non_none = [d for d in dates if d is not None]
        assert non_none == sorted(non_none)
        none_indices = [i for i, d in enumerate(dates) if d is None]
        assert all(i >= len(non_none) for i in none_indices), (
            "None values should sort last"
        )

    def test_sort_by_calibration_gap(self) -> None:
        concepts = self._get_sorted("calibration_gap")
        gaps = [c["calibration_gap"] for c in concepts]
        non_none = [g for g in gaps if g is not None]
        assert non_none == sorted(non_none)
        none_indices = [i for i, d in enumerate(gaps) if d is None]
        assert all(i >= len(non_none) for i in none_indices), (
            "None values should sort last"
        )

    def test_invalid_sort_by_returns_422(self) -> None:
        mock_client = MagicMock()
        _setup_two_table_mock(mock_client, [MASTERY_WELL_CALIBRATED], [])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/10?sort_by=invalid_field",
                headers=HEADERS,
            )
        assert resp.status_code == 422


class TestMasteryDashboardResourceCoverage:
    """Verify has_resources flag per concept."""

    def test_concept_with_resources(self) -> None:
        """Concept that matches a resource title gets has_resources=True."""
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_WELL_CALIBRATED],
            [RESOURCE_ALGEBRA],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        concept = resp.json()["concepts"][0]
        assert concept["has_resources"] is True

    def test_concept_without_resources(self) -> None:
        """Concept with no matching resources gets has_resources=False."""
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_UNDER_CONFIDENT],
            [],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        concept = resp.json()["concepts"][0]
        assert concept["has_resources"] is False


class TestMasteryDashboardResponseShape:
    """Verify the response structure."""

    def test_response_has_expected_fields(self) -> None:
        mock_client = MagicMock()
        _setup_two_table_mock(
            mock_client,
            [MASTERY_WELL_CALIBRATED],
            [RESOURCE_ALGEBRA],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert "course_id" in data
        assert data["course_id"] == 10
        assert "concepts" in data
        assert len(data["concepts"]) == 1

        concept = data["concepts"][0]
        expected_keys = {
            "concept",
            "mastery_level",
            "confidence_self_report",
            "calibration_gap",
            "calibration_status",
            "next_review_at",
            "last_retrieval_at",
            "retrieval_count",
            "success_rate",
            "has_resources",
        }
        assert expected_keys.issubset(set(concept.keys()))

    def test_empty_course_returns_empty_concepts(self) -> None:
        mock_client = MagicMock()
        _setup_two_table_mock(mock_client, [], [])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == 10
        assert data["concepts"] == []


class TestMasteryDashboardAuth:
    """Verify auth is required."""

    def test_unauthenticated_returns_401(self) -> None:
        """Request without auth header returns 401."""
        from mitty.api.routers.mastery_dashboard import router

        app = FastAPI()
        app.include_router(router)

        # No dependency overrides — real auth will fail
        mock_client = MagicMock()
        app.state.supabase_admin = mock_client
        app.state.supabase_client = mock_client

        # Simulate auth failure
        mock_client.auth.get_user = AsyncMock(side_effect=Exception("JWT expired"))

        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/10")

        assert resp.status_code == 401


# ===========================================================================
# Page route tests: GET /mastery
# ===========================================================================


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set minimum env vars needed by load_settings()."""
    monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
    monkeypatch.setenv("CANVAS_TOKEN", "test-token")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("FASTAPI_DEBUG", raising=False)


@pytest.fixture()
def page_client(_mock_env: None) -> Generator[TestClient]:
    """Create a TestClient with mocked settings."""
    from mitty.api.app import create_app

    app = create_app()
    with TestClient(app) as tc:
        yield tc


class TestMasteryPage:
    """GET /mastery returns the mastery dashboard HTML page."""

    def test_returns_html(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Mastery Hub" in response.text

    def test_contains_auth_gate(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "Please sign in" in response.text

    def test_contains_back_to_dashboard_link(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert 'href="/"' in response.text
        assert "Dashboard" in response.text

    def test_contains_mastery_app_script(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "masteryHubApp()" in response.text

    def test_contains_mastery_bar(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "mastery_level" in response.text

    def test_contains_calibration_badge(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "calibration_status" in response.text

    def test_contains_start_practice_cta(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "startPractice" in response.text

    def test_contains_course_selector(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "course" in response.text.lower()

    def test_contains_sort_control(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "sort" in response.text.lower()


# ===========================================================================
# Session History endpoint tests: GET /mastery-dashboard/session-history
# ===========================================================================

_SESSION_BASE = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "user_id": USER_ID,
    "course_id": 10,
    "assessment_id": None,
    "state_json": {},
    "started_at": "2026-03-10T10:00:00",
    "completed_at": "2026-03-10T11:00:00",
    "total_problems": 20,
    "total_correct": 15,
    "duration_seconds": 3600,
    "phase_reached": "calibration",
    "session_type": "full",
}


def _make_session(
    idx: int,
    *,
    total_problems: int = 20,
    total_correct: int = 15,
    duration_seconds: int = 3600,
) -> dict:
    """Create a session dict with a unique id and started_at shifted by idx hours."""
    return {
        **_SESSION_BASE,
        "id": f"aaaaaaaa-bbbb-cccc-dddd-{idx:012d}",
        "started_at": f"2026-03-{10 + idx:02d}T10:00:00",
        "completed_at": f"2026-03-{10 + idx:02d}T11:00:00",
        "total_problems": total_problems,
        "total_correct": total_correct,
        "duration_seconds": duration_seconds,
    }


def _setup_session_history_mock(
    mock_client: MagicMock,
    sessions: list[dict],
) -> None:
    """Configure mock for test_prep_sessions table queries."""
    session_chain = _chain_mock(sessions)

    def table_router(name: str) -> MagicMock:
        if name == "test_prep_sessions":
            return session_chain
        return _chain_mock([])

    mock_client.table = MagicMock(side_effect=table_router)


class TestSessionHistoryReturnsLast5:
    """GET /mastery-dashboard/session-history returns last 5 completed sessions."""

    def test_returns_last_5(self) -> None:
        """When 6 sessions exist, only 5 are returned (DB LIMIT)."""
        sessions = [_make_session(i) for i in range(5)]
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, sessions)
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 5
        # Verify each session has required fields
        for session in data["sessions"]:
            assert "session_id" in session
            assert "started_at" in session
            assert "total_problems" in session
            assert "total_correct" in session
            assert "accuracy" in session
            assert "duration_seconds" in session
            assert "phase_reached" in session
            assert "session_type" in session

    def test_accuracy_computed_correctly(self) -> None:
        """Accuracy should be total_correct / total_problems as a percentage."""
        sessions = [_make_session(0, total_problems=20, total_correct=15)]
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, sessions)
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        session = resp.json()["sessions"][0]
        assert session["accuracy"] == pytest.approx(75.0)


class TestSessionHistoryTrend:
    """trend_text computation from 3+ sessions."""

    def test_trend_text_3_sessions_improving(self) -> None:
        """With 3+ sessions showing improving accuracy, trend_text is present."""
        # Mock returns newest-first (DESC order from DB)
        sessions = [
            _make_session(2, total_problems=20, total_correct=16),  # 80% newest
            _make_session(1, total_problems=20, total_correct=14),  # 70%
            _make_session(0, total_problems=20, total_correct=10),  # 50% oldest
        ]
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, sessions)
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["trend_text"] is not None
        assert "Improving" in data["trend_text"]

    def test_trend_text_3_sessions_declining(self) -> None:
        """With 3+ sessions showing declining accuracy, trend_text reflects it."""
        # Mock returns newest-first (DESC order from DB)
        sessions = [
            _make_session(2, total_problems=20, total_correct=10),  # 50% newest
            _make_session(1, total_problems=20, total_correct=14),  # 70%
            _make_session(0, total_problems=20, total_correct=16),  # 80% oldest
        ]
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, sessions)
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["trend_text"] is not None
        assert "Declining" in data["trend_text"]

    def test_trend_text_3_sessions_steady(self) -> None:
        """With 3+ sessions showing similar accuracy, trend_text says Steady."""
        sessions = [
            _make_session(0, total_problems=20, total_correct=15),  # 75%
            _make_session(1, total_problems=20, total_correct=15),  # 75%
            _make_session(2, total_problems=20, total_correct=15),  # 75%
        ]
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, sessions)
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["trend_text"] is not None
        assert "Steady" in data["trend_text"]

    def test_trend_text_fewer_than_3_sessions_is_none(self) -> None:
        """With fewer than 3 sessions, trend_text should be None."""
        sessions = [
            _make_session(0, total_problems=20, total_correct=15),
            _make_session(1, total_problems=20, total_correct=18),
        ]
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, sessions)
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["trend_text"] is None


class TestSessionHistoryEmpty:
    """Edge case: no sessions."""

    def test_no_sessions_empty(self) -> None:
        """When no sessions exist, return empty list and no trend_text."""
        mock_client = MagicMock()
        _setup_session_history_mock(mock_client, [])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/session-history?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert data["trend_text"] is None


# ===========================================================================
# Upcoming assessment endpoint tests: GET /mastery-dashboard/upcoming
# ===========================================================================

# Future assessment (test) — scheduled tomorrow relative to test time
_ASSESSMENT_FUTURE_TEST = {
    "id": 100,
    "course_id": 10,
    "name": "Chapter 5 Test",
    "assessment_type": "test",
    "scheduled_date": "2026-03-20T10:00:00",
    "weight": 0.3,
    "unit_or_topic": "Chapter 5",
    "description": "Unit test on Chapter 5",
    "canvas_assignment_id": 500,
    "canvas_quiz_id": None,
    "auto_created": False,
    "source": None,
    "created_at": "2026-03-01T10:00:00",
    "updated_at": "2026-03-01T10:00:00",
}

# Future assessment (quiz) — scheduled further out
_ASSESSMENT_FUTURE_QUIZ = {
    "id": 101,
    "course_id": 10,
    "name": "Weekly Quiz 8",
    "assessment_type": "quiz",
    "scheduled_date": "2026-03-25T10:00:00",
    "weight": 0.1,
    "unit_or_topic": "Chapter 5-6",
    "description": "Weekly quiz",
    "canvas_assignment_id": 501,
    "canvas_quiz_id": None,
    "auto_created": False,
    "source": None,
    "created_at": "2026-03-01T10:00:00",
    "updated_at": "2026-03-01T10:00:00",
}

# Past assessment (already happened)
_ASSESSMENT_PAST = {
    "id": 102,
    "course_id": 10,
    "name": "Old Test",
    "assessment_type": "test",
    "scheduled_date": "2026-03-01T10:00:00",
    "weight": 0.3,
    "unit_or_topic": "Chapter 3",
    "description": None,
    "canvas_assignment_id": 502,
    "canvas_quiz_id": None,
    "auto_created": False,
    "source": None,
    "created_at": "2026-02-01T10:00:00",
    "updated_at": "2026-02-01T10:00:00",
}

# Assessment of type "essay" (should be excluded)
_ASSESSMENT_ESSAY = {
    "id": 103,
    "course_id": 10,
    "name": "Research Essay",
    "assessment_type": "essay",
    "scheduled_date": "2026-03-22T10:00:00",
    "weight": 0.2,
    "unit_or_topic": "Research",
    "description": None,
    "canvas_assignment_id": 503,
    "canvas_quiz_id": None,
    "auto_created": False,
    "source": None,
    "created_at": "2026-03-01T10:00:00",
    "updated_at": "2026-03-01T10:00:00",
}

# Homework analysis with per_problem_json containing concepts
_HOMEWORK_ANALYSIS_1 = {
    "id": 1,
    "user_id": USER_ID,
    "assignment_id": 500,
    "course_id": 10,
    "page_number": 1,
    "analysis_json": {"overall_score": 0.8},
    "image_tokens": 1000,
    "analyzed_at": "2026-03-10T10:00:00",
    "per_problem_json": [
        {
            "problem_number": 1,
            "correctness": 1.0,
            "error_type": None,
            "concept": "Quadratic equations",
        },
        {
            "problem_number": 2,
            "correctness": 0.5,
            "error_type": "procedural",
            "concept": "Factoring",
        },
    ],
}

_HOMEWORK_ANALYSIS_2 = {
    "id": 2,
    "user_id": USER_ID,
    "assignment_id": 500,
    "course_id": 10,
    "page_number": 2,
    "analysis_json": {"overall_score": 0.9},
    "image_tokens": 800,
    "analyzed_at": "2026-03-10T10:00:00",
    "per_problem_json": [
        {
            "problem_number": 3,
            "correctness": 1.0,
            "error_type": None,
            "concept": "Quadratic equations",
        },
        {
            "problem_number": 4,
            "correctness": 0.0,
            "error_type": "conceptual",
            "concept": "Completing the square",
        },
    ],
}


def _setup_upcoming_mock(
    mock_client: MagicMock,
    assessments: list[dict],
    homework_analyses: list[dict] | None = None,
) -> None:
    """Configure mock for assessments and homework_analyses tables."""
    assessment_chain = _chain_mock(assessments)
    homework_chain = _chain_mock(homework_analyses or [])

    def table_router(name: str) -> MagicMock:
        if name == "assessments":
            return assessment_chain
        if name == "homework_analyses":
            return homework_chain
        return _chain_mock([])

    mock_client.table = MagicMock(side_effect=table_router)


class TestUpcomingReturnsNearest:
    """GET /mastery-dashboard/upcoming returns the nearest future test/quiz."""

    def test_upcoming_returns_nearest(self) -> None:
        """Should return the assessment with the earliest future scheduled_date."""
        mock_client = MagicMock()
        # DB returns nearest first (ordered by scheduled_date ASC, limit 1)
        _setup_upcoming_mock(mock_client, [_ASSESSMENT_FUTURE_TEST])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/upcoming", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["assessment_id"] == 100
        assert data["name"] == "Chapter 5 Test"
        assert data["assessment_type"] == "test"
        assert data["course_id"] == 10
        assert data["scheduled_date"] is not None


class TestUpcomingNoFutureReturnsEmpty:
    """When no future test/quiz exists, return null."""

    def test_no_future_returns_empty(self) -> None:
        """Should return null when no future assessments of type test/quiz exist."""
        mock_client = MagicMock()
        _setup_upcoming_mock(mock_client, [])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/upcoming", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data is None


class TestUpcomingFiltersByType:
    """Only assessment_type IN ('test', 'quiz') are returned."""

    def test_filters_by_type(self) -> None:
        """Essay-type assessments should be excluded (filtered via DB query)."""
        mock_client = MagicMock()
        # The endpoint queries with .in_("assessment_type", ["test", "quiz"])
        # so only test/quiz come back from DB. Simulating correct DB behavior:
        _setup_upcoming_mock(mock_client, [_ASSESSMENT_FUTURE_QUIZ])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/upcoming", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["assessment_type"] == "quiz"
        assert data["name"] == "Weekly Quiz 8"


class TestUpcomingIncludesConcepts:
    """Concepts are extracted from homework_analyses linked to the assessment."""

    def test_includes_concepts(self) -> None:
        """Should include deduplicated concepts from homework analyses."""
        mock_client = MagicMock()
        _setup_upcoming_mock(
            mock_client,
            [_ASSESSMENT_FUTURE_TEST],
            [_HOMEWORK_ANALYSIS_1, _HOMEWORK_ANALYSIS_2],
        )
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/upcoming", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        concepts = data["concepts"]
        assert isinstance(concepts, list)
        # Should have deduplicated concepts
        assert "Quadratic equations" in concepts
        assert "Factoring" in concepts
        assert "Completing the square" in concepts
        # No duplicates
        assert len(concepts) == len(set(concepts))

    def test_no_analyses_returns_empty_concepts(self) -> None:
        """When no homework analyses exist, concepts should be empty list."""
        mock_client = MagicMock()
        _setup_upcoming_mock(mock_client, [_ASSESSMENT_FUTURE_TEST], [])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/upcoming", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["concepts"] == []


class TestUpcomingCourseIdFilter:
    """Optional course_id query param filters assessments."""

    def test_with_course_id(self) -> None:
        """Should pass course_id filter to DB query."""
        mock_client = MagicMock()
        _setup_upcoming_mock(mock_client, [_ASSESSMENT_FUTURE_TEST])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/mastery-dashboard/upcoming?course_id=10",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["assessment_id"] == 100

    def test_without_course_id(self) -> None:
        """Should work without course_id param (returns from any course)."""
        mock_client = MagicMock()
        _setup_upcoming_mock(mock_client, [_ASSESSMENT_FUTURE_TEST])
        app = _build_app(mock_client)
        with TestClient(app) as tc:
            resp = tc.get("/mastery-dashboard/upcoming", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
