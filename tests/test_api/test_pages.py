"""Tests for page-serving routes (Jinja2 HTML responses)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


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
def client(_mock_env: None) -> Generator[TestClient]:
    """Create a TestClient with mocked settings (lifespan enabled)."""
    from mitty.api.app import create_app

    app = create_app()
    with TestClient(app) as tc:
        yield tc


class TestDashboardPage:
    """GET / returns the dashboard HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Grades Dashboard" in response.text


class TestStudyPlanRedirect:
    """GET /study-plan shows a redirect banner to Mastery Hub."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/study-plan")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_contains_redirect_banner(self, client: TestClient) -> None:
        response = client.get("/study-plan")

        assert "Study Plan has moved" in response.text
        assert "Mastery Hub" in response.text

    def test_contains_mastery_hub_link(self, client: TestClient) -> None:
        response = client.get("/study-plan")

        assert 'href="/mastery"' in response.text
        assert "Go to Mastery Hub" in response.text


class TestAssessmentsManagePage:
    """GET /assessments/manage returns the assessment management HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Manage Assessments" in response.text

    def test_contains_create_button(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "New Assessment" in response.text

    def test_contains_course_filter(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "course-filter" in response.text
        assert "All courses" in response.text

    def test_contains_auth_gate(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "Please sign in to manage assessments" in response.text

    def test_contains_assessments_app_script(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "assessmentsApp()" in response.text

    def test_contains_back_to_dashboard_link(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert 'href="/"' in response.text
        assert "Back to Dashboard" in response.text

    def test_contains_assessment_types(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "'test'" in response.text
        assert "'quiz'" in response.text
        assert "'essay'" in response.text
        assert "'lab'" in response.text
        assert "'project'" in response.text

    def test_contains_auto_created_badge(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "auto_created" in response.text
        assert "auto</span>" in response.text

    def test_contains_delete_confirmation(self, client: TestClient) -> None:
        response = client.get("/assessments/manage")

        assert "Delete Assessment" in response.text
        assert "cannot be undone" in response.text


class TestResourcesManagePage:
    """GET /resources/manage returns the resource management HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Manage Resources" in response.text

    def test_contains_sign_in_prompt(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert "Please sign in to manage resources." in response.text

    def test_contains_back_to_dashboard_link(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert 'href="/"' in response.text
        assert "Back to Dashboard" in response.text

    def test_contains_resources_app_script(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert "resourcesApp()" in response.text

    def test_contains_create_form(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert "Create Resource" in response.text

    def test_contains_filter_controls(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert "All courses" in response.text
        assert "All types" in response.text

    def test_contains_resource_type_options(self, client: TestClient) -> None:
        response = client.get("/resources/manage")

        assert "textbook_chapter" in response.text
        assert "canvas_page" in response.text
        assert "video" in response.text


class TestPracticeSessionPage:
    """GET /practice returns the practice session HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Practice Session" in response.text

    def test_contains_auth_gate(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "Please sign in to start a practice session." in response.text

    def test_contains_back_to_mastery_hub_link(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert 'href="/mastery"' in response.text
        assert "Back to Mastery Hub" in response.text

    def test_contains_practice_session_app_script(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "practiceSessionApp()" in response.text

    def test_contains_confidence_prompt(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "How confident are you?" in response.text

    def test_contains_check_answer_button(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "Check Answer" in response.text

    def test_contains_session_complete_section(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "Session Complete" in response.text

    def test_contains_progress_bar(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "questions" in response.text

    def test_contains_api_endpoints(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "/practice/generate" in response.text
        assert "/practice-results/evaluate" in response.text
        assert "/mastery-states/update-from-results" in response.text

    def test_contains_practice_type_labels(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "Multiple Choice" in response.text
        assert "Fill in the Blank" in response.text
        assert "Short Answer" in response.text
        assert "Flashcard" in response.text

    def test_contains_calibration_message(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "calibrationMessage" in response.text

    def test_contains_concepts_to_review(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "Concepts to Review" in response.text

    def test_contains_mastery_update_section(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert "Mastery Updated" in response.text

    def test_contains_view_mastery_link(self, client: TestClient) -> None:
        response = client.get("/practice")

        assert 'href="/mastery"' in response.text
        assert "View Mastery" in response.text


class TestTestPrepPage:
    """GET /test-prep returns the test prep HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/test-prep")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_contains_test_prep_title(self, client: TestClient) -> None:
        response = client.get("/test-prep")

        assert "Test Prep" in response.text


class TestClassDetailPage:
    """GET /class/{course_id} returns the class detail HTML page."""

    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/class/12345")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Class Detail" in response.text
