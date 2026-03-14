"""Tests for mitty.canvas.fetcher — high-level async fetch functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from mitty.canvas.fetcher import (
    fetch_all,
    fetch_assignments,
    fetch_calendar_events,
    fetch_courses,
    fetch_enrollments,
    fetch_file_contents,
    fetch_files,
    fetch_module_items,
    fetch_modules,
    fetch_pages,
    fetch_quizzes,
    fetch_submission_attachments,
    resolve_module_item_pages,
    strip_html,
)

# fetch_discussion_topics is tested in test_fetcher_discussions.py but exercised
# indirectly via _patch_all_fetchers for fetch_all tests.
from mitty.models import (
    Assignment,
    CalendarEvent,
    Course,
    DiscussionTopic,
    Enrollment,
    FileMetadata,
    Module,
    ModuleItem,
    Page,
    Quiz,
    Submission,
    Term,
)

FETCHER_MODULE = "mitty.canvas.fetcher"

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

        # First assignment: has a graded submission + description
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

        # Description: HTML stripped to plain text
        assert a0.description is not None
        assert "<" not in a0.description  # HTML tags stripped
        assert "rhetorical analysis" in a0.description
        assert "Minimum 1000 words" in a0.description

        # Second assignment: unsubmitted + missing, null description
        a1 = result[1]
        assert a1.submission is not None
        assert a1.submission.score is None
        assert a1.submission.missing is True
        assert a1.description is None

        # Third assignment: null submission, has description
        a2 = result[2]
        assert a2.submission is None
        assert a2.description is not None
        assert "Submit your project proposal" in a2.description

        # Fourth assignment: no description field in JSON
        a3 = result[3]
        assert a3.description is None

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


def _make_quiz(quiz_id: int, title: str = "Quiz") -> Quiz:
    """Create a Quiz instance for testing."""
    return Quiz(id=quiz_id, title=title)


def _make_module(module_id: int, name: str = "Module") -> Module:
    """Create a Module instance for testing."""
    return Module(id=module_id, name=name)


def _make_module_item(item_id: int, module_id: int, title: str = "Item") -> ModuleItem:
    """Create a ModuleItem instance for testing."""
    return ModuleItem(id=item_id, module_id=module_id, title=title, type="Page")


def _make_page(page_id: int, title: str = "Page") -> Page:
    """Create a Page instance for testing."""
    return Page(page_id=page_id, title=title, url=f"page-{page_id}")


def _make_file(file_id: int, name: str = "file.pdf") -> FileMetadata:
    """Create a FileMetadata instance for testing."""
    return FileMetadata(id=file_id, display_name=name)


def _make_calendar_event(
    event_id: int, title: str, context_code: str = "course_1"
) -> CalendarEvent:
    """Create a CalendarEvent instance for testing."""
    return CalendarEvent(id=event_id, title=title, context_code=context_code)


def _make_discussion_topic(topic_id: int, title: str = "Discussion") -> DiscussionTopic:
    """Create a DiscussionTopic instance for testing."""
    return DiscussionTopic(id=topic_id, title=title)


def _patch_all_fetchers(**overrides):
    """Return a dict of patches for all fetcher functions used by fetch_all.

    Values can be:
    - A plain list: used as ``return_value``
    - A list of lists: used as ``side_effect`` (one return per call)
    - An Exception: used as ``side_effect``
    - A callable: used as ``side_effect``

    For per-course fetchers that are called multiple times, pass a list
    of lists to use ``side_effect``.
    """
    defaults: dict = {
        "fetch_courses": [],
        "fetch_enrollments": [],
        "fetch_assignments": [],
        "fetch_quizzes": [],
        "fetch_modules": [],
        "fetch_module_items": [],
        "resolve_module_item_pages": {},
        "fetch_pages": [],
        "fetch_files": [],
        "fetch_file_contents": {},
        "fetch_discussion_topics": [],
        "fetch_calendar_events": [],
    }
    defaults.update(overrides)
    patches = {}
    for name, value in defaults.items():
        if isinstance(value, Exception) or (
            callable(value) and not isinstance(value, list)
        ):
            patches[name] = patch(
                f"{FETCHER_MODULE}.{name}",
                new_callable=AsyncMock,
                side_effect=value,
            )
        elif isinstance(value, list) and value and isinstance(value[0], list):
            # List of lists -> side_effect (one return per call)
            patches[name] = patch(
                f"{FETCHER_MODULE}.{name}",
                new_callable=AsyncMock,
                side_effect=value,
            )
        else:
            patches[name] = patch(
                f"{FETCHER_MODULE}.{name}",
                new_callable=AsyncMock,
                return_value=value,
            )
    return patches


class TestFetchAll:
    """fetch_all orchestrates concurrent fetching of all data."""

    async def test_all_courses_succeed(self) -> None:
        """All courses fetched successfully — full result with no errors."""
        courses = [_make_course(1, "Math"), _make_course(2, "English")]
        assignments_1 = [_make_assignment(10, 1), _make_assignment(11, 1)]
        assignments_2 = [_make_assignment(20, 2)]
        enrollments = [_make_enrollment(100, 1), _make_enrollment(101, 2)]
        quizzes_1 = [_make_quiz(50)]
        quizzes_2 = [_make_quiz(60)]
        modules_1 = [_make_module(30, "Unit 1")]
        items_1_30 = [_make_module_item(300, 30)]
        pages_1 = [_make_page(80)]
        files_1 = [_make_file(90)]
        discussions_1 = [_make_discussion_topic(110, "Welcome")]
        cal_events = [_make_calendar_event(70, "Midterm Exam")]

        patches = _patch_all_fetchers(
            fetch_courses=courses,
            fetch_enrollments=enrollments,
            fetch_assignments=[assignments_1, assignments_2],
            fetch_quizzes=[quizzes_1, quizzes_2],
            fetch_modules=[modules_1, []],
            fetch_module_items=items_1_30,
            fetch_pages=[pages_1, []],
            fetch_files=[files_1, []],
            fetch_discussion_topics=[discussions_1, []],
            fetch_calendar_events=cal_events,
        )

        with (
            patches["fetch_courses"],
            patches["fetch_enrollments"],
            patches["fetch_assignments"] as mock_assign,
            patches["fetch_quizzes"] as mock_quiz,
            patches["fetch_modules"] as mock_mod,
            patches["fetch_module_items"] as mock_mod_items,
            patches["resolve_module_item_pages"],
            patches["fetch_pages"] as mock_pages,
            patches["fetch_files"] as mock_files,
            patches["fetch_file_contents"],
            patches["fetch_discussion_topics"] as mock_disc,
            patches["fetch_calendar_events"] as mock_cal,
        ):
            client = AsyncMock()
            settings = _make_settings()
            result = await fetch_all(client, settings)

        assert result["courses"] == courses
        assert result["enrollments"] == enrollments
        assert result["errors"] == []
        assert result["assignments"]["1"] == assignments_1
        assert result["assignments"]["2"] == assignments_2
        assert result["quizzes"]["1"] == quizzes_1
        assert result["quizzes"]["2"] == quizzes_2
        assert result["modules"]["1"]["modules"] == modules_1
        assert result["modules"]["1"]["module_items"][30] == items_1_30
        assert result["pages"]["1"] == pages_1
        assert result["files"]["1"] == files_1
        assert result["file_contents"]["1"] == {}
        assert result["discussion_topics"]["1"] == discussions_1
        assert result["calendar_events"] == cal_events
        assert mock_assign.call_count == 2
        assert mock_quiz.call_count == 2
        assert mock_mod.call_count == 2
        assert mock_mod_items.call_count == 1  # only 1 module in course 1
        assert mock_pages.call_count == 2
        assert mock_files.call_count == 2
        assert mock_disc.call_count == 2
        mock_cal.assert_called_once_with(client, [1, 2])

    async def test_one_course_fails(self) -> None:
        """One course's data fails — partial results + error recorded."""
        courses = [_make_course(1, "Math"), _make_course(2, "English")]
        assignments_1 = [_make_assignment(10, 1)]
        enrollments = [_make_enrollment(100, 1)]

        # Course 1 succeeds, course 2 fails at assignments
        call_count = {"assign": 0}

        async def _assign_side_effect(_client, course_id):
            call_count["assign"] += 1
            if course_id == 2:
                raise RuntimeError("Canvas API timeout")
            return assignments_1

        patches = _patch_all_fetchers(
            fetch_courses=courses,
            fetch_enrollments=enrollments,
            fetch_assignments=_assign_side_effect,
            fetch_quizzes=[],
            fetch_modules=[],
            fetch_pages=[],
            fetch_files=[],
            fetch_calendar_events=[],
        )

        with (
            patches["fetch_courses"],
            patches["fetch_enrollments"],
            patches["fetch_assignments"],
            patches["fetch_quizzes"],
            patches["fetch_modules"],
            patches["fetch_module_items"],
            patches["resolve_module_item_pages"],
            patches["fetch_pages"],
            patches["fetch_files"],
            patches["fetch_file_contents"],
            patches["fetch_discussion_topics"],
            patches["fetch_calendar_events"],
        ):
            client = AsyncMock()
            settings = _make_settings()
            result = await fetch_all(client, settings)

        assert result["courses"] == courses
        assert result["enrollments"] == enrollments

        # Only the successful course should appear
        assert "1" in result["assignments"]
        assert result["assignments"]["1"] == assignments_1
        assert "2" not in result["assignments"]

        # One error should be recorded
        assert len(result["errors"]) == 1
        assert "course 2" in result["errors"][0]
        assert "English" in result["errors"][0]
        assert "Canvas API timeout" in result["errors"][0]

    async def test_empty_course_list(self) -> None:
        """No courses — empty data dicts and no errors."""
        patches = _patch_all_fetchers(
            fetch_courses=[],
            fetch_enrollments=[_make_enrollment(100, 1)],
        )

        with (
            patches["fetch_courses"],
            patches["fetch_enrollments"],
            patches["fetch_assignments"] as mock_assign,
            patches["fetch_quizzes"],
            patches["fetch_modules"],
            patches["fetch_module_items"],
            patches["resolve_module_item_pages"],
            patches["fetch_pages"],
            patches["fetch_files"],
            patches["fetch_file_contents"],
            patches["fetch_discussion_topics"],
            patches["fetch_calendar_events"],
        ):
            client = AsyncMock()
            settings = _make_settings()
            result = await fetch_all(client, settings)

        assert result["courses"] == []
        assert result["assignments"] == {}
        assert result["quizzes"] == {}
        assert result["modules"] == {}
        assert result["pages"] == {}
        assert result["files"] == {}
        assert result["file_contents"] == {}
        assert result["discussion_topics"] == {}
        assert result["calendar_events"] == []
        assert result["enrollments"] == [_make_enrollment(100, 1)]
        assert result["errors"] == []

        mock_assign.assert_not_called()

    async def test_calendar_events_failure_does_not_block(self) -> None:
        """Calendar event failure is logged but doesn't block other data."""
        courses = [_make_course(1, "Math")]

        patches = _patch_all_fetchers(
            fetch_courses=courses,
            fetch_enrollments=[],
            fetch_assignments=[[]],
            fetch_quizzes=[[]],
            fetch_modules=[[]],
            fetch_pages=[[]],
            fetch_files=[[]],
            fetch_discussion_topics=[[]],
            fetch_calendar_events=RuntimeError("Calendar API down"),
        )

        with (
            patches["fetch_courses"],
            patches["fetch_enrollments"],
            patches["fetch_assignments"],
            patches["fetch_quizzes"],
            patches["fetch_modules"],
            patches["fetch_module_items"],
            patches["resolve_module_item_pages"],
            patches["fetch_pages"],
            patches["fetch_files"],
            patches["fetch_file_contents"],
            patches["fetch_discussion_topics"],
            patches["fetch_calendar_events"],
        ):
            client = AsyncMock()
            settings = _make_settings()
            result = await fetch_all(client, settings)

        # Per-course data still present
        assert "1" in result["assignments"]
        assert result["calendar_events"] == []
        assert len(result["errors"]) == 1
        assert "calendar events" in result["errors"][0].lower()

    async def test_returns_all_expected_keys(self) -> None:
        """Result dict always contains all expected keys."""
        patches = _patch_all_fetchers()

        with (
            patches["fetch_courses"],
            patches["fetch_enrollments"],
            patches["fetch_assignments"],
            patches["fetch_quizzes"],
            patches["fetch_modules"],
            patches["fetch_module_items"],
            patches["resolve_module_item_pages"],
            patches["fetch_pages"],
            patches["fetch_files"],
            patches["fetch_file_contents"],
            patches["fetch_discussion_topics"],
            patches["fetch_calendar_events"],
        ):
            client = AsyncMock()
            settings = _make_settings()
            result = await fetch_all(client, settings)

        expected_keys = {
            "courses",
            "assignments",
            "enrollments",
            "quizzes",
            "modules",
            "pages",
            "files",
            "file_contents",
            "discussion_topics",
            "calendar_events",
            "errors",
        }
        assert set(result.keys()) == expected_keys


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


class TestFetchPages:
    """fetch_pages calls get_paginated and strips HTML bodies."""

    async def test_fetch_pages_parses_fixture(self) -> None:
        raw = _load_fixture("pages.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_pages(client, course_id=12345)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/pages",
            {"include[]": "body", "per_page": "100"},
        )
        assert len(result) == 3
        assert all(isinstance(p, Page) for p in result)

        # First page: HTML stripped to plain text
        assert result[0].page_id == 8001
        assert result[0].title == "Course Syllabus"
        assert "<" not in (result[0].body or "")
        assert "AP English Language" in (result[0].body or "")
        assert "Welcome to AP English" in (result[0].body or "")

        # Second page: null body preserved
        assert result[1].page_id == 8002
        assert result[1].body is None

        # Third page: unpublished but still parsed
        assert result[2].page_id == 8003
        assert result[2].published is False

    async def test_fetch_pages_empty_body(self) -> None:
        """Pages with null body are returned with body=None."""
        raw = [
            {
                "page_id": 9001,
                "title": "Empty Page",
                "body": None,
                "url": "empty-page",
                "published": True,
            }
        ]
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_pages(client, course_id=99)

        assert len(result) == 1
        assert result[0].body is None

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_pages(client, course_id=12345)

        assert result == []


class TestFetchFiles:
    """fetch_files calls get_paginated with course_id in the path."""

    async def test_fetch_files_parses_fixture(self) -> None:
        raw = _load_fixture("files.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_files(client, course_id=12345)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/files",
            {"per_page": "100"},
        )
        assert len(result) == 3
        assert all(isinstance(f, FileMetadata) for f in result)

        # First file: PDF with full metadata
        f0 = result[0]
        assert f0.id == 9001
        assert f0.display_name == "Unit1_Study_Guide.pdf"
        assert f0.content_type == "application/pdf"
        assert f0.size == 245760
        assert f0.url == "https://mitty.instructure.com/files/9001/download"
        assert f0.folder_id == 4001

        # Second file: DOCX
        f1 = result[1]
        assert f1.id == 9002
        assert f1.display_name == "lecture_notes_week3.docx"

        # Third file: empty URL and null folder
        f2 = result[2]
        assert f2.id == 9003
        assert f2.url == ""
        assert f2.folder_id is None
        assert f2.size == 0

    async def test_fetch_files_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_files(client, course_id=99999)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/99999/files",
            {"per_page": "100"},
        )
        assert result == []


class TestStripHtml:
    """strip_html removes tags, scripts, and styles."""

    def test_html_stripping_removes_scripts_and_styles(self) -> None:
        html = (
            "<html><head><style>body { color: red; }</style></head>"
            "<body><script>alert('xss')</script>"
            "<h1>Title</h1><p>Content here.</p></body></html>"
        )
        text = strip_html(html)
        assert "alert" not in text
        assert "color: red" not in text
        assert "Title" in text
        assert "Content here." in text

    def test_preserves_plain_text_content(self) -> None:
        html = "<p>Hello <strong>world</strong></p>"
        text = strip_html(html)
        assert "Hello" in text
        assert "world" in text
        assert "<" not in text

    def test_newline_separator(self) -> None:
        html = "<p>Line one</p><p>Line two</p>"
        text = strip_html(html)
        assert "Line one" in text
        assert "Line two" in text


class TestFetchCalendarEvents:
    """fetch_calendar_events calls get_paginated with context codes."""

    async def test_fetch_calendar_events_parses_fixture(self) -> None:
        raw = _load_fixture("calendar_events.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_calendar_events(client, [12345])

        client.get_paginated.assert_called_once_with(
            "/api/v1/calendar_events",
            {"per_page": "100", "context_codes[]": "course_12345"},
        )
        assert len(result) == 4
        assert all(isinstance(e, CalendarEvent) for e in result)

        # First event: quiz with dates
        assert result[0].id == 7001
        assert result[0].title == "Chapter 5 Quiz"
        assert result[0].context_code == "course_12345"
        assert result[0].start_at is not None

        # Second event: user-context (non-course)
        assert result[1].id == 7002
        assert result[1].context_code == "user_42"

        # Fourth event: null dates
        assert result[3].id == 7004
        assert result[3].start_at is None

    async def test_multiple_courses_fetch_separately(self) -> None:
        """Each course ID triggers a separate API call."""
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_calendar_events(client, [100, 200])

        assert client.get_paginated.call_count == 2
        assert result == []

    async def test_empty_course_ids_returns_empty(self) -> None:
        client = AsyncMock()

        result = await fetch_calendar_events(client, [])

        assert result == []
        client.get_paginated.assert_not_called()

    async def test_date_range_params_passed(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        await fetch_calendar_events(
            client,
            [12345],
            start_date="2026-01-01",
            end_date="2026-06-30",
        )

        client.get_paginated.assert_called_once_with(
            "/api/v1/calendar_events",
            {
                "per_page": "100",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "context_codes[]": "course_12345",
            },
        )


class TestResolveModuleItemPages:
    """resolve_module_item_pages fetches page bodies for Page-type items."""

    async def test_resolves_page_items(self) -> None:
        """Page-type items with page_url get their bodies fetched and stripped."""
        items = [
            ModuleItem(
                id=101,
                module_id=10,
                title="Intro",
                type="Page",
                page_url="intro-page",
            ),
            ModuleItem(
                id=102,
                module_id=10,
                title="Guide",
                type="Page",
                page_url="study-guide",
            ),
        ]

        response_1 = MagicMock()
        response_1.json.return_value = {
            "body": "<p>Welcome to the <strong>course</strong>.</p>"
        }
        response_2 = MagicMock()
        response_2.json.return_value = {
            "body": "<h1>Study Guide</h1><p>Review chapters 1-3.</p>"
        }

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[response_1, response_2])

        result = await resolve_module_item_pages(
            client, course_id=12345, module_items=items
        )

        assert len(result) == 2
        assert 101 in result
        assert 102 in result
        assert "Welcome to the" in result[101]
        assert "course" in result[101]
        assert "<" not in result[101]  # HTML stripped
        assert "Study Guide" in result[102]
        assert "Review chapters 1-3" in result[102]

        # Verify API paths
        client.get.assert_any_call("/api/v1/courses/12345/pages/intro-page")
        client.get.assert_any_call("/api/v1/courses/12345/pages/study-guide")

    async def test_skips_non_page_items(self) -> None:
        """Non-Page items are ignored."""
        items = [
            ModuleItem(id=201, module_id=10, title="File", type="File"),
            ModuleItem(id=202, module_id=10, title="Link", type="ExternalUrl"),
            ModuleItem(id=203, module_id=10, title="Header", type="SubHeader"),
        ]

        client = AsyncMock()

        result = await resolve_module_item_pages(
            client, course_id=12345, module_items=items
        )

        assert result == {}
        client.get.assert_not_called()

    async def test_skips_page_without_page_url(self) -> None:
        """Page items with no page_url are skipped."""
        items = [
            ModuleItem(
                id=301,
                module_id=10,
                title="No URL",
                type="Page",
                page_url=None,
            ),
        ]

        client = AsyncMock()

        result = await resolve_module_item_pages(
            client, course_id=12345, module_items=items
        )

        assert result == {}
        client.get.assert_not_called()

    async def test_skips_page_with_null_body(self) -> None:
        """Pages with null body are excluded from the result."""
        items = [
            ModuleItem(
                id=401,
                module_id=10,
                title="Empty",
                type="Page",
                page_url="empty-page",
            ),
        ]

        response = MagicMock()
        response.json.return_value = {"body": None}

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        result = await resolve_module_item_pages(
            client, course_id=12345, module_items=items
        )

        assert result == {}

    async def test_graceful_skip_on_api_failure(self) -> None:
        """API errors on individual pages are logged and skipped."""
        items = [
            ModuleItem(
                id=501,
                module_id=10,
                title="Good",
                type="Page",
                page_url="good-page",
            ),
            ModuleItem(
                id=502,
                module_id=10,
                title="Bad",
                type="Page",
                page_url="bad-page",
            ),
        ]

        good_response = MagicMock()
        good_response.json.return_value = {"body": "<p>Good content</p>"}

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[good_response, RuntimeError("404 Not Found")]
        )

        result = await resolve_module_item_pages(
            client, course_id=12345, module_items=items
        )

        # Only the successful page should be in the result
        assert len(result) == 1
        assert 501 in result
        assert "Good content" in result[501]
        assert 502 not in result

    async def test_empty_items_returns_empty_dict(self) -> None:
        """Empty items list returns empty dict without API calls."""
        client = AsyncMock()

        result = await resolve_module_item_pages(
            client, course_id=12345, module_items=[]
        )

        assert result == {}
        client.get.assert_not_called()


class TestFetchAssignmentDescriptions:
    """fetch_assignments strips HTML from assignment descriptions."""

    async def test_strips_html_description(self) -> None:
        """HTML descriptions are stripped to plain text."""
        raw = [
            {
                "id": 1,
                "name": "Essay",
                "course_id": 100,
                "description": (
                    "<p>Write an <em>essay</em> about <strong>rhetoric</strong>.</p>"
                ),
            },
        ]
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_assignments(client, course_id=100)

        assert len(result) == 1
        assert result[0].description is not None
        assert "<" not in result[0].description
        assert "Write an" in result[0].description
        assert "essay" in result[0].description
        assert "rhetoric" in result[0].description

    async def test_null_description_preserved(self) -> None:
        """Null descriptions remain None."""
        raw = [
            {
                "id": 2,
                "name": "Quiz",
                "course_id": 100,
                "description": None,
            },
        ]
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_assignments(client, course_id=100)

        assert result[0].description is None

    async def test_missing_description_defaults_to_none(self) -> None:
        """Assignments without description field default to None."""
        raw = [
            {
                "id": 3,
                "name": "HW",
                "course_id": 100,
            },
        ]
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_assignments(client, course_id=100)

        assert result[0].description is None


# ------------------------------------------------------------------ #
#  fetch_file_contents
# ------------------------------------------------------------------ #


class TestFetchFileContents:
    """fetch_file_contents downloads and extracts text from PDF/DOCX files."""

    async def test_fetch_file_contents_extracts_pdf(self) -> None:
        """PDF files are downloaded and their text extracted."""
        file = FileMetadata(
            id=9001,
            display_name="study_guide.pdf",
            content_type="application/pdf",
            url="https://mitty.instructure.com/files/9001/download",
        )
        client = AsyncMock()

        with (
            patch(
                f"{FETCHER_MODULE}.download_file_content",
                new_callable=AsyncMock,
                return_value=b"fake-pdf-bytes",
            ) as mock_download,
            patch(
                f"{FETCHER_MODULE}.extract_text",
                return_value="Extracted PDF text content",
            ) as mock_extract,
        ):
            result = await fetch_file_contents(client, [file])

        mock_download.assert_awaited_once_with(
            client._http,
            "https://mitty.instructure.com/files/9001/download",
        )
        mock_extract.assert_called_once_with(b"fake-pdf-bytes", "application/pdf")
        assert result == {9001: "Extracted PDF text content"}

    async def test_fetch_file_contents_skips_unsupported(self) -> None:
        """Non-PDF/DOCX files are skipped entirely."""
        txt_file = FileMetadata(
            id=9002,
            display_name="notes.txt",
            content_type="text/plain",
            url="https://mitty.instructure.com/files/9002/download",
        )
        png_file = FileMetadata(
            id=9003,
            display_name="diagram.png",
            content_type="image/png",
            url="https://mitty.instructure.com/files/9003/download",
        )

        client = AsyncMock()

        with patch(
            f"{FETCHER_MODULE}.download_file_content",
            new_callable=AsyncMock,
        ) as mock_download:
            result = await fetch_file_contents(client, [txt_file, png_file])

        mock_download.assert_not_called()
        assert result == {}

    async def test_fetch_file_contents_handles_download_failure(self) -> None:
        """Download failure for one file does not stop others."""
        file_ok = FileMetadata(
            id=9001,
            display_name="good.pdf",
            content_type="application/pdf",
            url="https://mitty.instructure.com/files/9001/download",
        )
        file_bad = FileMetadata(
            id=9002,
            display_name="bad.pdf",
            content_type="application/pdf",
            url="https://mitty.instructure.com/files/9002/download",
        )
        client = AsyncMock()

        call_count = {"n": 0}

        async def _download_side_effect(_client, url, **kwargs):
            call_count["n"] += 1
            if "9002" in url:
                raise RuntimeError("Network error")
            return b"pdf-bytes"

        with (
            patch(
                f"{FETCHER_MODULE}.download_file_content",
                new_callable=AsyncMock,
                side_effect=_download_side_effect,
            ),
            patch(
                f"{FETCHER_MODULE}.extract_text",
                return_value="Good PDF text",
            ),
        ):
            result = await fetch_file_contents(client, [file_ok, file_bad])

        # The good file succeeded, the bad one was skipped
        assert 9001 in result
        assert 9002 not in result
        assert result[9001] == "Good PDF text"

    async def test_fetch_file_contents_skips_empty_extraction(self) -> None:
        """Files that produce empty extracted text are excluded."""
        file = FileMetadata(
            id=9001,
            display_name="empty.pdf",
            content_type="application/pdf",
            url="https://mitty.instructure.com/files/9001/download",
        )
        client = AsyncMock()

        with (
            patch(
                f"{FETCHER_MODULE}.download_file_content",
                new_callable=AsyncMock,
                return_value=b"fake-bytes",
            ),
            patch(
                f"{FETCHER_MODULE}.extract_text",
                return_value="",
            ),
        ):
            result = await fetch_file_contents(client, [file])

        assert result == {}

    async def test_fetch_file_contents_docx_by_extension(self) -> None:
        """DOCX files detected by extension are processed."""
        file = FileMetadata(
            id=9004,
            display_name="essay.docx",
            content_type="application/octet-stream",
            url="https://mitty.instructure.com/files/9004/download",
        )
        client = AsyncMock()

        with (
            patch(
                f"{FETCHER_MODULE}.download_file_content",
                new_callable=AsyncMock,
                return_value=b"docx-bytes",
            ) as mock_download,
            patch(
                f"{FETCHER_MODULE}.extract_text",
                return_value="Essay content here",
            ) as mock_extract,
        ):
            result = await fetch_file_contents(client, [file])

        mock_download.assert_awaited_once()
        # When content_type is generic, should guess from extension
        expected_ct = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        mock_extract.assert_called_once_with(b"docx-bytes", expected_ct)
        assert result == {9004: "Essay content here"}

    async def test_fetch_file_contents_download_returns_none(self) -> None:
        """When download returns None (rejected/oversized), file is skipped."""
        file = FileMetadata(
            id=9005,
            display_name="huge.pdf",
            content_type="application/pdf",
            url="https://mitty.instructure.com/files/9005/download",
        )
        client = AsyncMock()

        with patch(
            f"{FETCHER_MODULE}.download_file_content",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await fetch_file_contents(client, [file])

        assert result == {}


class TestFetchSubmissionAttachments:
    """fetch_submission_attachments fetches attachment metadata per assignment."""

    async def test_fetch_submission_attachments_success(self) -> None:
        """Returns attachment dicts when submission has attachments."""
        attachment_data = [
            {
                "id": 1001,
                "uuid": "abc123",
                "display_name": "essay.pdf",
                "filename": "essay.pdf",
                "url": "https://mitty.instructure.com/files/1001/download",
                "content-type": "application/pdf",
                "size": 204800,
            },
            {
                "id": 1002,
                "uuid": "def456",
                "display_name": "notes.docx",
                "filename": "notes.docx",
                "url": "https://mitty.instructure.com/files/1002/download",
                "content-type": (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
                "size": 51200,
            },
        ]
        response = MagicMock()
        response.json.return_value = {"attachments": attachment_data}

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[67890]
        )

        client.get.assert_called_once_with(
            "/api/v1/courses/12345/assignments/67890/submissions/self",
            params={"include[]": "attachments"},
        )
        assert len(result) == 2
        assert result[0]["url"] == ("https://mitty.instructure.com/files/1001/download")
        assert result[0]["filename"] == "essay.pdf"
        assert result[0]["content_type"] == "application/pdf"
        assert result[0]["size"] == 204800
        assert result[1]["filename"] == "notes.docx"
        assert result[1]["size"] == 51200

    async def test_no_submission(self) -> None:
        """Returns empty list when submission does not exist (404)."""
        from mitty.canvas.client import CanvasAPIError

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=CanvasAPIError(
                "Canvas API error: 404 Not Found for "
                "/api/v1/courses/12345/assignments/99999/submissions/self"
            )
        )

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[99999]
        )

        assert result == []

    async def test_no_attachments(self) -> None:
        """Returns empty list when submission exists but has no attachments."""
        response = MagicMock()
        response.json.return_value = {
            "id": 5001,
            "assignment_id": 67890,
            "workflow_state": "submitted",
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[67890]
        )

        assert result == []

    async def test_multiple_assignments(self) -> None:
        """Fetches attachments across multiple assignments."""
        response_1 = MagicMock()
        response_1.json.return_value = {
            "attachments": [
                {
                    "id": 2001,
                    "display_name": "hw1.pdf",
                    "filename": "hw1.pdf",
                    "url": "https://mitty.instructure.com/files/2001/download",
                    "content-type": "application/pdf",
                    "size": 10240,
                },
            ]
        }
        response_2 = MagicMock()
        response_2.json.return_value = {
            "attachments": [
                {
                    "id": 2002,
                    "display_name": "hw2.pdf",
                    "filename": "hw2.pdf",
                    "url": "https://mitty.instructure.com/files/2002/download",
                    "content-type": "application/pdf",
                    "size": 20480,
                },
            ]
        }

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[response_1, response_2])

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[100, 200]
        )

        assert len(result) == 2
        assert result[0]["filename"] == "hw1.pdf"
        assert result[1]["filename"] == "hw2.pdf"

        client.get.assert_any_call(
            "/api/v1/courses/12345/assignments/100/submissions/self",
            params={"include[]": "attachments"},
        )
        client.get.assert_any_call(
            "/api/v1/courses/12345/assignments/200/submissions/self",
            params={"include[]": "attachments"},
        )

    async def test_empty_assignment_ids(self) -> None:
        """Returns empty list when no assignment IDs are provided."""
        client = AsyncMock()

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[]
        )

        assert result == []
        client.get.assert_not_called()

    async def test_mixed_success_and_404(self) -> None:
        """Successful submissions are collected even when others 404."""
        from mitty.canvas.client import CanvasAPIError

        good_response = MagicMock()
        good_response.json.return_value = {
            "attachments": [
                {
                    "id": 3001,
                    "display_name": "report.pdf",
                    "filename": "report.pdf",
                    "url": "https://mitty.instructure.com/files/3001/download",
                    "content-type": "application/pdf",
                    "size": 30720,
                },
            ]
        }

        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                good_response,
                CanvasAPIError("Canvas API error: 404 Not Found"),
            ]
        )

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[100, 200]
        )

        assert len(result) == 1
        assert result[0]["filename"] == "report.pdf"

    async def test_empty_attachments_list(self) -> None:
        """Returns empty list when attachments key exists but is empty."""
        response = MagicMock()
        response.json.return_value = {
            "id": 6001,
            "attachments": [],
        }

        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        result = await fetch_submission_attachments(
            client, course_id=12345, assignment_ids=[67890]
        )

        assert result == []
