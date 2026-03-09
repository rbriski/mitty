"""Tests for mitty.canvas.fetcher — high-level async fetch functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from mitty.canvas.fetcher import fetch_assignments, fetch_courses, fetch_enrollments
from mitty.models import Assignment, Course, Enrollment, Submission, Term

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
