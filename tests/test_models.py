"""Tests for mitty.models — Pydantic data models for Canvas API objects."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mitty.models import Assignment, Course, Enrollment, Submission, Term

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
