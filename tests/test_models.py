"""Tests for mitty.models — Pydantic data models for Canvas API objects."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mitty.models import (
    Assignment,
    CalendarEvent,
    Course,
    Enrollment,
    FileMetadata,
    Module,
    ModuleItem,
    Page,
    Quiz,
    Submission,
    Term,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def courses_data() -> list[dict]:
    return json.loads((FIXTURES / "courses.json").read_text())


@pytest.fixture()
def assignments_data() -> list[dict]:
    return json.loads((FIXTURES / "assignments.json").read_text())


@pytest.fixture()
def enrollments_data() -> list[dict]:
    return json.loads((FIXTURES / "enrollments.json").read_text())


# --- Term ---


class TestTerm:
    def test_term_parse(self) -> None:
        raw = {"id": 100, "name": "2025-2026", "created_at": "2025-06-01T00:00:00Z"}
        term = Term.model_validate(raw)
        assert term.id == 100
        assert term.name == "2025-2026"

    def test_term_ignores_extra_fields(self) -> None:
        raw = {"id": 100, "name": "2025-2026", "created_at": "2025-06-01T00:00:00Z"}
        term = Term.model_validate(raw)
        assert not hasattr(term, "created_at")


# --- Course ---


class TestCourse:
    def test_course_parse_with_term(self, courses_data: list[dict]) -> None:
        raw = courses_data[0]  # AP English Language, has term
        course = Course.model_validate(raw)
        assert course.id == 12345
        assert course.name == "AP English Language"
        assert course.course_code == "ENG-AP"
        assert course.workflow_state == "available"
        assert course.term is not None
        assert course.term.id == 100
        assert course.term.name == "2025-2026"

    def test_course_parse_without_term(self, courses_data: list[dict]) -> None:
        raw = courses_data[1]  # Honors Chemistry, term=null
        course = Course.model_validate(raw)
        assert course.id == 12346
        assert course.name == "Honors Chemistry"
        assert course.term is None

    def test_course_ignores_extra_fields(self, courses_data: list[dict]) -> None:
        raw = courses_data[0]  # Has extra fields: enrollment_term_id, account_id, uuid
        course = Course.model_validate(raw)
        assert not hasattr(course, "enrollment_term_id")
        assert not hasattr(course, "account_id")
        assert not hasattr(course, "uuid")

    def test_course_completed_state(self, courses_data: list[dict]) -> None:
        raw = courses_data[2]  # World History, completed
        course = Course.model_validate(raw)
        assert course.workflow_state == "completed"
        assert course.term is not None
        assert course.term.name == "2024-2025"


# --- Submission ---


class TestSubmission:
    def test_submission_parse_all_fields(self, assignments_data: list[dict]) -> None:
        raw = assignments_data[0]["submission"]  # Graded submission
        submission = Submission.model_validate(raw)
        assert submission.score == 48.0
        assert submission.grade == "48"
        assert submission.submitted_at == datetime(2026, 3, 14, 10, 30, 0, tzinfo=UTC)
        assert submission.workflow_state == "graded"
        assert submission.late is False
        assert submission.missing is False

    def test_submission_ignores_extra_fields(
        self, assignments_data: list[dict]
    ) -> None:
        raw = assignments_data[0]["submission"]  # Has extra: attempt, body
        submission = Submission.model_validate(raw)
        assert not hasattr(submission, "attempt")
        assert not hasattr(submission, "body")

    def test_submission_missing_assignment(self, assignments_data: list[dict]) -> None:
        raw = assignments_data[1]["submission"]  # Missing assignment
        submission = Submission.model_validate(raw)
        assert submission.score is None
        assert submission.grade is None
        assert submission.missing is True
        assert submission.workflow_state == "unsubmitted"


# --- Assignment ---


class TestAssignment:
    def test_assignment_parse_with_submission(
        self, assignments_data: list[dict]
    ) -> None:
        raw = assignments_data[0]  # Essay with graded submission
        assignment = Assignment.model_validate(raw)
        assert assignment.id == 67890
        assert assignment.name == "Essay: Rhetorical Analysis"
        assert assignment.course_id == 12345
        assert assignment.due_at == datetime(2026, 3, 15, 23, 59, 59, tzinfo=UTC)
        assert assignment.points_possible == 50.0
        assert assignment.html_url == (
            "https://mitty.instructure.com/courses/12345/assignments/67890"
        )
        assert assignment.submission is not None
        assert assignment.submission.score == 48.0

    def test_assignment_parse_null_submission(
        self, assignments_data: list[dict]
    ) -> None:
        raw = assignments_data[2]  # Final Project Proposal, submission=null
        assignment = Assignment.model_validate(raw)
        assert assignment.id == 67892
        assert assignment.submission is None

    def test_assignment_parse_null_due_at(self, assignments_data: list[dict]) -> None:
        raw = assignments_data[2]  # Final Project Proposal, due_at=null
        assignment = Assignment.model_validate(raw)
        assert assignment.due_at is None

    def test_assignment_ignores_extra_fields(
        self, assignments_data: list[dict]
    ) -> None:
        raw = assignments_data[
            0
        ]  # Has extra: submission_types, grading_type, published
        assignment = Assignment.model_validate(raw)
        assert not hasattr(assignment, "submission_types")
        assert not hasattr(assignment, "grading_type")
        assert not hasattr(assignment, "published")


# --- Enrollment ---


class TestEnrollment:
    def test_enrollment_parse_with_grades(self, enrollments_data: list[dict]) -> None:
        raw = enrollments_data[0]  # Active enrollment with grades
        enrollment = Enrollment.model_validate(raw)
        assert enrollment.id == 111
        assert enrollment.course_id == 12345
        assert enrollment.type == "StudentEnrollment"
        assert enrollment.enrollment_state == "active"
        assert enrollment.grades is not None
        assert enrollment.grades["current_score"] == 96.2
        assert enrollment.grades["current_grade"] == "A"
        assert enrollment.grades["final_score"] == 94.8
        assert enrollment.grades["final_grade"] == "A"

    def test_enrollment_parse_null_grades(self, enrollments_data: list[dict]) -> None:
        raw = enrollments_data[1]  # Completed enrollment, grades=null
        enrollment = Enrollment.model_validate(raw)
        assert enrollment.id == 112
        assert enrollment.enrollment_state == "completed"
        assert enrollment.grades is None

    def test_enrollment_ignores_extra_fields(
        self, enrollments_data: list[dict]
    ) -> None:
        raw = enrollments_data[0]  # Has extra: user_id, html_url, created_at
        enrollment = Enrollment.model_validate(raw)
        assert not hasattr(enrollment, "user_id")
        assert not hasattr(enrollment, "html_url")
        assert not hasattr(enrollment, "created_at")


# --- Quiz ---


@pytest.fixture()
def quizzes_data() -> list[dict]:
    return json.loads((FIXTURES / "quizzes.json").read_text())


class TestQuiz:
    def test_quiz_parse(self, quizzes_data: list[dict]) -> None:
        quiz = Quiz.model_validate(quizzes_data[0])
        assert quiz.id == 5001
        assert quiz.title == "Chapter 5 Quiz: The Great Gatsby"
        assert quiz.quiz_type == "assignment"
        assert quiz.due_at == datetime(2026, 4, 10, 23, 59, 59, tzinfo=UTC)
        assert quiz.points_possible == 25.0
        assert quiz.time_limit == 30
        assert quiz.assignment_id == 67900
        assert quiz.description == "<p>Quiz covering chapters 4-5 themes.</p>"

    def test_quiz_nullable_fields(self, quizzes_data: list[dict]) -> None:
        quiz = Quiz.model_validate(quizzes_data[1])
        assert quiz.id == 5002
        assert quiz.due_at is None
        assert quiz.points_possible is None
        assert quiz.time_limit is None
        assert quiz.assignment_id is None
        assert quiz.description is None

    def test_quiz_ignores_extra_fields(self, quizzes_data: list[dict]) -> None:
        quiz = Quiz.model_validate(quizzes_data[0])
        assert not hasattr(quiz, "html_url")
        assert not hasattr(quiz, "shuffle_answers")
        assert not hasattr(quiz, "question_count")

    def test_quiz_defaults(self) -> None:
        raw = {"id": 1, "title": "Minimal Quiz"}
        quiz = Quiz.model_validate(raw)
        assert quiz.quiz_type == ""
        assert quiz.due_at is None
        assert quiz.points_possible is None
        assert quiz.time_limit is None
        assert quiz.assignment_id is None
        assert quiz.description is None


# --- Module ---


@pytest.fixture()
def modules_data() -> list[dict]:
    return json.loads((FIXTURES / "modules.json").read_text())


class TestModule:
    def test_module_parse(self, modules_data: list[dict]) -> None:
        module = Module.model_validate(modules_data[0])
        assert module.id == 3001
        assert module.name == "Unit 1: Introduction to Rhetoric"
        assert module.position == 1
        assert module.unlock_at is None
        assert module.items_count == 5

    def test_module_with_unlock_at(self, modules_data: list[dict]) -> None:
        module = Module.model_validate(modules_data[1])
        assert module.unlock_at == datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
        assert module.items_count == 8

    def test_module_ignores_extra_fields(self, modules_data: list[dict]) -> None:
        module = Module.model_validate(modules_data[0])
        assert not hasattr(module, "items_url")
        assert not hasattr(module, "state")
        assert not hasattr(module, "workflow_state")

    def test_module_defaults(self) -> None:
        raw = {"id": 1, "name": "Minimal Module"}
        module = Module.model_validate(raw)
        assert module.position == 0
        assert module.unlock_at is None
        assert module.items_count == 0


# --- ModuleItem ---


class TestModuleItem:
    def test_module_item_parse(self) -> None:
        raw = {
            "id": 4001,
            "module_id": 3001,
            "title": "Read Chapter 1",
            "type": "Page",
            "content_id": 8001,
            "position": 1,
            "page_url": "read-chapter-1",
            "external_url": None,
            "indent": 0,
            "html_url": "https://mitty.instructure.com/courses/12345/modules/items/4001",
        }
        item = ModuleItem.model_validate(raw)
        assert item.id == 4001
        assert item.module_id == 3001
        assert item.title == "Read Chapter 1"
        assert item.type == "Page"
        assert item.content_id == 8001
        assert item.position == 1
        assert item.page_url == "read-chapter-1"
        assert item.external_url is None

    def test_module_item_external_url(self) -> None:
        raw = {
            "id": 4002,
            "module_id": 3001,
            "title": "External Resource",
            "type": "ExternalUrl",
            "content_id": None,
            "position": 2,
            "page_url": None,
            "external_url": "https://example.com/resource",
        }
        item = ModuleItem.model_validate(raw)
        assert item.external_url == "https://example.com/resource"
        assert item.content_id is None
        assert item.page_url is None

    def test_module_item_ignores_extra_fields(self) -> None:
        raw = {
            "id": 4001,
            "module_id": 3001,
            "title": "Item",
            "type": "Page",
            "indent": 0,
            "html_url": "https://example.com",
        }
        item = ModuleItem.model_validate(raw)
        assert not hasattr(item, "indent")
        assert not hasattr(item, "html_url")

    def test_module_item_defaults(self) -> None:
        raw = {"id": 1, "module_id": 1, "title": "Item", "type": "Page"}
        item = ModuleItem.model_validate(raw)
        assert item.content_id is None
        assert item.position == 0
        assert item.page_url is None
        assert item.external_url is None


# --- Page ---


@pytest.fixture()
def pages_data() -> list[dict]:
    return json.loads((FIXTURES / "pages.json").read_text())


class TestPage:
    def test_page_parse_with_body(self, pages_data: list[dict]) -> None:
        page = Page.model_validate(pages_data[0])
        assert page.page_id == 8001
        assert page.title == "Course Syllabus"
        assert "<h1>" in page.body  # type: ignore[operator]
        assert page.url == "course-syllabus"
        assert page.published is True

    def test_page_null_body(self, pages_data: list[dict]) -> None:
        page = Page.model_validate(pages_data[1])
        assert page.body is None

    def test_page_unpublished(self, pages_data: list[dict]) -> None:
        page = Page.model_validate(pages_data[2])
        assert page.published is False

    def test_page_ignores_extra_fields(self, pages_data: list[dict]) -> None:
        page = Page.model_validate(pages_data[0])
        assert not hasattr(page, "created_at")
        assert not hasattr(page, "editing_roles")
        assert not hasattr(page, "front_page")

    def test_page_defaults(self) -> None:
        raw = {"page_id": 1, "title": "Minimal Page"}
        page = Page.model_validate(raw)
        assert page.body is None
        assert page.url == ""
        assert page.published is True


# --- FileMetadata ---


@pytest.fixture()
def files_data() -> list[dict]:
    return json.loads((FIXTURES / "files.json").read_text())


class TestFileMetadata:
    def test_file_parse(self, files_data: list[dict]) -> None:
        f = FileMetadata.model_validate(files_data[0])
        assert f.id == 9001
        assert f.display_name == "Unit1_Study_Guide.pdf"
        assert f.content_type == "application/pdf"
        assert f.size == 245760
        assert "download" in f.url
        assert f.folder_id == 4001

    def test_file_null_folder(self, files_data: list[dict]) -> None:
        f = FileMetadata.model_validate(files_data[2])
        assert f.folder_id is None

    def test_file_ignores_extra_fields(self, files_data: list[dict]) -> None:
        f = FileMetadata.model_validate(files_data[0])
        assert not hasattr(f, "uuid")
        assert not hasattr(f, "created_at")
        assert not hasattr(f, "thumbnail_url")

    def test_file_defaults(self) -> None:
        raw = {"id": 1, "display_name": "empty.txt"}
        f = FileMetadata.model_validate(raw)
        assert f.content_type == ""
        assert f.size == 0
        assert f.url == ""
        assert f.folder_id is None


# --- CalendarEvent ---


@pytest.fixture()
def calendar_events_data() -> list[dict]:
    return json.loads((FIXTURES / "calendar_events.json").read_text())


class TestCalendarEvent:
    def test_calendar_event_parse(self, calendar_events_data: list[dict]) -> None:
        event = CalendarEvent.model_validate(calendar_events_data[0])
        assert event.id == 7001
        assert event.title == "Chapter 5 Quiz"
        assert event.start_at == datetime(2026, 4, 10, 13, 0, 0, tzinfo=UTC)
        assert event.end_at == datetime(2026, 4, 10, 13, 45, 0, tzinfo=UTC)
        assert event.context_type == "Course"
        assert event.context_code == "course_12345"

    def test_calendar_event_nullable_fields(
        self, calendar_events_data: list[dict]
    ) -> None:
        event = CalendarEvent.model_validate(calendar_events_data[1])
        assert event.description is None

    def test_calendar_event_null_times(self, calendar_events_data: list[dict]) -> None:
        event = CalendarEvent.model_validate(calendar_events_data[3])
        assert event.start_at is None
        assert event.end_at is None

    def test_calendar_event_ignores_extra_fields(
        self, calendar_events_data: list[dict]
    ) -> None:
        event = CalendarEvent.model_validate(calendar_events_data[0])
        assert not hasattr(event, "all_day")
        assert not hasattr(event, "workflow_state")
        assert not hasattr(event, "created_at")

    def test_calendar_event_defaults(self) -> None:
        raw = {"id": 1, "title": "Minimal Event"}
        event = CalendarEvent.model_validate(raw)
        assert event.description is None
        assert event.start_at is None
        assert event.end_at is None
        assert event.context_type == ""
        assert event.context_code == ""
