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
    for attr in ("select", "eq", "order", "range", "in_"):
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
        assert all(
            i >= len(non_none) for i in none_indices
        ), "None values should sort last"

    def test_sort_by_calibration_gap(self) -> None:
        concepts = self._get_sorted("calibration_gap")
        gaps = [c["calibration_gap"] for c in concepts]
        non_none = [g for g in gaps if g is not None]
        assert non_none == sorted(non_none)
        none_indices = [i for i, d in enumerate(gaps) if d is None]
        assert all(
            i >= len(non_none) for i in none_indices
        ), "None values should sort last"

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
        assert "Mastery Dashboard" in response.text

    def test_contains_auth_gate(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "Please sign in" in response.text

    def test_contains_back_to_dashboard_link(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert 'href="/"' in response.text
        assert "Dashboard" in response.text

    def test_contains_mastery_app_script(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "masteryDashboardApp()" in response.text

    def test_contains_mastery_bar(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "mastery_level" in response.text

    def test_contains_calibration_badge(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "calibration_status" in response.text

    def test_contains_no_study_materials_indicator(
        self, page_client: TestClient
    ) -> None:
        response = page_client.get("/mastery")

        assert "No study materials" in response.text

    def test_contains_course_selector(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "course" in response.text.lower()

    def test_contains_sort_control(self, page_client: TestClient) -> None:
        response = page_client.get("/mastery")

        assert "sort" in response.text.lower()
