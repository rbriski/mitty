"""Tests for mitty.canvas.fetcher — high-level async fetch functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mitty.canvas.fetcher import (
    fetch_all,
    fetch_assignments,
    fetch_courses,
    fetch_enrollments,
    fetch_module_items,
    fetch_modules,
    fetch_quizzes,
)
from mitty.models import (
    Assignment,
    Course,
    Enrollment,
    Module,
    ModuleItem,
    Quiz,
    Submission,
    Term,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    """Load a JSON fixture file and return a list of dicts."""
    return json.loads((FIXTURES / name).read_text())


class TestFetchCourses:
    """fetch_courses calls get_paginated with the correct path and params."""

    async def test_parses_courses_from_fixture(self) -> None:
        raw = _load_fixture("courses.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_courses(client)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses",
            {"include[]": "term", "per_page": "100"},
        )
        assert len(result) == 3
        assert all(isinstance(c, Course) for c in result)

        # Spot-check first course with nested term
        assert result[0].id == 12345
        assert result[0].name == "AP English Language"
        assert result[0].course_code == "ENG-AP"
        assert result[0].workflow_state == "available"
        assert isinstance(result[0].term, Term)
        assert result[0].term.id == 100
        assert result[0].term.name == "2025-2026"

        # Null term
        assert result[1].term is None

        # Completed course with term
        assert result[2].id == 12300
        assert result[2].workflow_state == "completed"
        assert result[2].term is not None
        assert result[2].term.name == "2024-2025"

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_courses(client)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses",
            {"include[]": "term", "per_page": "100"},
        )
        assert result == []


class TestFetchAssignments:
    """fetch_assignments calls get_paginated with course_id in the path."""

    async def test_parses_assignments_from_fixture(self) -> None:
        raw = _load_fixture("assignments.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_assignments(client, course_id=12345)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/assignments",
            {"include[]": "submission", "per_page": "100"},
        )
        assert len(result) == 4
        assert all(isinstance(a, Assignment) for a in result)

        # First assignment: has a graded submission
        a0 = result[0]
        assert a0.id == 67890
        assert a0.name == "Essay: Rhetorical Analysis"
        assert a0.course_id == 12345
        assert a0.points_possible == 50.0
        assert a0.html_url == (
            "https://mitty.instructure.com/courses/12345/assignments/67890"
        )
        assert isinstance(a0.submission, Submission)
        assert a0.submission.score == 48.0
        assert a0.submission.workflow_state == "graded"
        assert a0.submission.late is False
        assert a0.submission.missing is False

        # Second assignment: unsubmitted + missing
        a1 = result[1]
        assert a1.submission is not None
        assert a1.submission.score is None
        assert a1.submission.missing is True

        # Third assignment: null submission
        a2 = result[2]
        assert a2.submission is None

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_assignments(client, course_id=99999)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/99999/assignments",
            {"include[]": "submission", "per_page": "100"},
        )
        assert result == []

    async def test_uses_correct_course_id_in_path(self) -> None:
        """Verify the course_id is interpolated into the URL path."""
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        await fetch_assignments(client, course_id=42)

        call_args = client.get_paginated.call_args
        assert call_args[0][0] == "/api/v1/courses/42/assignments"


class TestFetchQuizzes:
    """fetch_quizzes calls get_paginated with course_id in the path."""

    async def test_fetch_quizzes_parses_fixture(self) -> None:
        raw = _load_fixture("quizzes.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_quizzes(client, course_id=12345)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/quizzes",
            {"per_page": "100"},
        )
        assert len(result) == 3
        assert all(isinstance(q, Quiz) for q in result)

        # First quiz: assignment-linked with due date
        q0 = result[0]
        assert q0.id == 5001
        assert q0.title == "Chapter 5 Quiz: The Great Gatsby"
        assert q0.quiz_type == "assignment"
        assert q0.points_possible == 25.0
        assert q0.time_limit == 30
        assert q0.assignment_id == 67900
        assert q0.description == "<p>Quiz covering chapters 4-5 themes.</p>"

        # Second quiz: practice quiz with null fields
        q1 = result[1]
        assert q1.id == 5002
        assert q1.quiz_type == "practice_quiz"
        assert q1.due_at is None
        assert q1.points_possible is None
        assert q1.time_limit is None
        assert q1.assignment_id is None
        assert q1.description is None

    async def test_fetch_quizzes_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_quizzes(client, course_id=99999)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/99999/quizzes",
            {"per_page": "100"},
        )
        assert result == []


class TestFetchEnrollments:
    """fetch_enrollments calls get_paginated for the self user enrollments."""

    async def test_parses_enrollments_from_fixture(self) -> None:
        raw = _load_fixture("enrollments.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_enrollments(client)

        client.get_paginated.assert_called_once_with(
            "/api/v1/users/self/enrollments",
            {"include[]": "current_points", "per_page": "100"},
        )
        assert len(result) == 2
        assert all(isinstance(e, Enrollment) for e in result)

        # First enrollment: active with grades
        e0 = result[0]
        assert e0.id == 111
        assert e0.course_id == 12345
        assert e0.type == "StudentEnrollment"
        assert e0.enrollment_state == "active"
        assert e0.grades is not None
        assert e0.grades["current_score"] == 96.2
        assert e0.grades["current_grade"] == "A"

        # Second enrollment: completed with null grades
        e1 = result[1]
        assert e1.enrollment_state == "completed"
        assert e1.grades is None

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_enrollments(client)

        client.get_paginated.assert_called_once_with(
            "/api/v1/users/self/enrollments",
            {"include[]": "current_points", "per_page": "100"},
        )
        assert result == []


def _make_settings(max_concurrent: int = 3):
    """Create a minimal Settings-like object for fetch_all tests."""
    from mitty.config import Settings

    return Settings(canvas_token="fake-token", max_concurrent=max_concurrent)


def _make_course(course_id: int, name: str = "Test Course") -> Course:
    """Create a Course instance for testing."""
    return Course(id=course_id, name=name, course_code=f"C-{course_id}")


def _make_assignment(assignment_id: int, course_id: int) -> Assignment:
    """Create an Assignment instance for testing."""
    return Assignment(id=assignment_id, name=f"HW {assignment_id}", course_id=course_id)


def _make_enrollment(enrollment_id: int, course_id: int) -> Enrollment:
    """Create an Enrollment instance for testing."""
    return Enrollment(id=enrollment_id, course_id=course_id, type="StudentEnrollment")


class TestFetchAll:
    """fetch_all orchestrates concurrent fetching of all data."""

    @patch("mitty.canvas.fetcher.fetch_enrollments", new_callable=AsyncMock)
    @patch("mitty.canvas.fetcher.fetch_assignments", new_callable=AsyncMock)
    @patch("mitty.canvas.fetcher.fetch_courses", new_callable=AsyncMock)
    async def test_all_courses_succeed(
        self,
        mock_fetch_courses: AsyncMock,
        mock_fetch_assignments: AsyncMock,
        mock_fetch_enrollments: AsyncMock,
    ) -> None:
        """All courses fetched successfully — full result with no errors."""
        courses = [_make_course(1, "Math"), _make_course(2, "English")]
        assignments_1 = [_make_assignment(10, 1), _make_assignment(11, 1)]
        assignments_2 = [_make_assignment(20, 2)]
        enrollments = [_make_enrollment(100, 1), _make_enrollment(101, 2)]

        mock_fetch_courses.return_value = courses
        mock_fetch_enrollments.return_value = enrollments
        mock_fetch_assignments.side_effect = [assignments_1, assignments_2]

        client = AsyncMock()
        settings = _make_settings()

        result = await fetch_all(client, settings)

        assert result["courses"] == courses
        assert result["enrollments"] == enrollments
        assert result["errors"] == []
        assert result["assignments"]["1"] == assignments_1
        assert result["assignments"]["2"] == assignments_2
        assert len(result["assignments"]) == 2

        mock_fetch_courses.assert_called_once_with(client)
        mock_fetch_enrollments.assert_called_once_with(client)
        assert mock_fetch_assignments.call_count == 2

    @patch("mitty.canvas.fetcher.fetch_enrollments", new_callable=AsyncMock)
    @patch("mitty.canvas.fetcher.fetch_assignments", new_callable=AsyncMock)
    @patch("mitty.canvas.fetcher.fetch_courses", new_callable=AsyncMock)
    async def test_one_course_fails(
        self,
        mock_fetch_courses: AsyncMock,
        mock_fetch_assignments: AsyncMock,
        mock_fetch_enrollments: AsyncMock,
    ) -> None:
        """One course's assignments fail — partial results + error recorded."""
        courses = [_make_course(1, "Math"), _make_course(2, "English")]
        assignments_1 = [_make_assignment(10, 1)]
        enrollments = [_make_enrollment(100, 1)]

        mock_fetch_courses.return_value = courses
        mock_fetch_enrollments.return_value = enrollments
        mock_fetch_assignments.side_effect = [
            assignments_1,
            RuntimeError("Canvas API timeout"),
        ]

        client = AsyncMock()
        settings = _make_settings()

        result = await fetch_all(client, settings)

        assert result["courses"] == courses
        assert result["enrollments"] == enrollments

        # Only the successful course should appear in assignments
        assert "1" in result["assignments"]
        assert result["assignments"]["1"] == assignments_1
        assert "2" not in result["assignments"]

        # One error should be recorded
        assert len(result["errors"]) == 1
        assert "course 2" in result["errors"][0]
        assert "English" in result["errors"][0]
        assert "Canvas API timeout" in result["errors"][0]

    @patch("mitty.canvas.fetcher.fetch_enrollments", new_callable=AsyncMock)
    @patch("mitty.canvas.fetcher.fetch_assignments", new_callable=AsyncMock)
    @patch("mitty.canvas.fetcher.fetch_courses", new_callable=AsyncMock)
    async def test_empty_course_list(
        self,
        mock_fetch_courses: AsyncMock,
        mock_fetch_assignments: AsyncMock,
        mock_fetch_enrollments: AsyncMock,
    ) -> None:
        """No courses — empty assignments dict and no errors."""
        mock_fetch_courses.return_value = []
        mock_fetch_enrollments.return_value = [_make_enrollment(100, 1)]

        client = AsyncMock()
        settings = _make_settings()

        result = await fetch_all(client, settings)

        assert result["courses"] == []
        assert result["assignments"] == {}
        assert result["enrollments"] == [_make_enrollment(100, 1)]
        assert result["errors"] == []

        # fetch_assignments should never be called with no courses
        mock_fetch_assignments.assert_not_called()


class TestFetchModules:
    """fetch_modules calls get_paginated with course_id in the path."""

    async def test_fetch_modules_parses_fixture(self) -> None:
        raw = _load_fixture("modules.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_modules(client, course_id=12345)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/modules",
            {"include[]": "items", "per_page": "100"},
        )
        assert len(result) == 3
        assert all(isinstance(m, Module) for m in result)

        # First module
        assert result[0].id == 3001
        assert result[0].name == "Unit 1: Introduction to Rhetoric"
        assert result[0].position == 1
        assert result[0].unlock_at is None
        assert result[0].items_count == 5

        # Second module with unlock_at
        assert result[1].id == 3002
        assert result[1].name == "Unit 2: Argument & Persuasion"
        assert result[1].position == 2
        assert result[1].unlock_at is not None
        assert result[1].items_count == 8

        # Third module — locked, zero items
        assert result[2].id == 3003
        assert result[2].items_count == 0

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_modules(client, course_id=99999)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/99999/modules",
            {"include[]": "items", "per_page": "100"},
        )
        assert result == []


class TestFetchModuleItems:
    """fetch_module_items calls get_paginated with course_id and module_id."""

    async def test_fetch_module_items_parses_fixture(self) -> None:
        raw = _load_fixture("module_items.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_module_items(client, course_id=12345, module_id=3001)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/modules/3001/items",
            {"per_page": "100"},
        )
        assert len(result) == 5
        assert all(isinstance(item, ModuleItem) for item in result)

        # Page item
        assert result[0].id == 5001
        assert result[0].module_id == 3001
        assert result[0].title == "Welcome to Rhetoric"
        assert result[0].type == "Page"
        assert result[0].page_url == "welcome-to-rhetoric"
        assert result[0].position == 1

        # File item
        assert result[1].type == "File"
        assert result[1].content_id == 8002

        # ExternalUrl item
        assert result[2].type == "ExternalUrl"
        assert result[2].external_url is not None
        assert "purdue" in result[2].external_url

        # Assignment item
        assert result[3].type == "Assignment"
        assert result[3].content_id == 67890

        # SubHeader item
        assert result[4].type == "SubHeader"

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_module_items(client, course_id=12345, module_id=3001)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/modules/3001/items",
            {"per_page": "100"},
        )
        assert result == []
