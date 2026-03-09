"""Tests for mitty.storage — Supabase async storage functions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.models import Assignment, Course, Enrollment, Submission, Term
from mitty.storage import (
    StorageError,
    create_storage,
    upsert_assignments,
    upsert_courses,
    upsert_enrollments,
    upsert_submissions,
)


def _mock_client() -> AsyncMock:
    """Build a mock AsyncClient with chained table().upsert().execute()."""
    client = AsyncMock()
    # table() returns an object with upsert(), which returns object with execute()
    table_builder = MagicMock()
    upsert_builder = MagicMock()
    execute_result = MagicMock()
    execute_result.data = []

    upsert_builder.execute = AsyncMock(return_value=execute_result)
    table_builder.upsert = MagicMock(return_value=upsert_builder)
    client.table = MagicMock(return_value=table_builder)

    return client


# ------------------------------------------------------------------ #
#  create_storage
# ------------------------------------------------------------------ #


class TestCreateStorage:
    """create_storage delegates to supabase.acreate_client."""

    @patch("mitty.storage.acreate_client", new_callable=AsyncMock)
    async def test_creates_async_client(self, mock_create: AsyncMock) -> None:
        mock_async_client = AsyncMock()
        mock_create.return_value = mock_async_client

        result = await create_storage(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key-123",
        )

        mock_create.assert_awaited_once_with("https://test.supabase.co", "test-key-123")
        assert result is mock_async_client

    @patch("mitty.storage.acreate_client", new_callable=AsyncMock)
    async def test_wraps_error_in_storage_error(self, mock_create: AsyncMock) -> None:
        mock_create.side_effect = Exception("connection refused")

        with pytest.raises(StorageError, match="connection refused"):
            await create_storage(
                supabase_url="https://test.supabase.co",
                supabase_key="bad-key",
            )


# ------------------------------------------------------------------ #
#  upsert_courses
# ------------------------------------------------------------------ #


class TestUpsertCourses:
    """upsert_courses denormalizes Term and upserts to Supabase."""

    async def test_upsert_courses_with_term(self) -> None:
        client = _mock_client()
        term = Term(id=100, name="2025-2026")
        courses = [
            Course(
                id=12345,
                name="AP English",
                course_code="ENG-AP",
                term=term,
                workflow_state="available",
            ),
        ]

        await upsert_courses(client, courses)

        client.table.assert_called_once_with("courses")
        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == 12345
        assert row["name"] == "AP English"
        assert row["course_code"] == "ENG-AP"
        assert row["term_id"] == 100
        assert row["term_name"] == "2025-2026"
        assert row["workflow_state"] == "available"
        assert "updated_at" in row

    async def test_upsert_courses_without_term(self) -> None:
        client = _mock_client()
        courses = [
            Course(
                id=12346,
                name="Honors Chemistry",
                course_code="CHEM-H",
                term=None,
            ),
        ]

        await upsert_courses(client, courses)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["term_id"] is None
        assert row["term_name"] is None

    async def test_upsert_courses_empty_list(self) -> None:
        client = _mock_client()

        await upsert_courses(client, [])

        client.table.assert_not_called()

    async def test_upsert_courses_on_conflict_id(self) -> None:
        client = _mock_client()
        courses = [
            Course(id=1, name="Test", course_code="T"),
        ]

        await upsert_courses(client, courses)

        upsert_call = client.table.return_value.upsert
        kwargs = upsert_call.call_args[1]
        assert kwargs.get("on_conflict") == "id"

    async def test_upsert_courses_api_failure_raises_storage_error(self) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("API timeout")
        )
        courses = [Course(id=1, name="Test", course_code="T")]

        with pytest.raises(StorageError, match="API timeout"):
            await upsert_courses(client, courses)


# ------------------------------------------------------------------ #
#  upsert_assignments
# ------------------------------------------------------------------ #


class TestUpsertAssignments:
    """upsert_assignments flattens course_id-keyed dict and upserts."""

    async def test_upsert_assignments_flattens_dict(self) -> None:
        client = _mock_client()
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(
                    id=67890,
                    name="Essay",
                    course_id=12345,
                    due_at=datetime(2026, 3, 15, 23, 59, 59, tzinfo=UTC),
                    points_possible=50.0,
                    html_url="https://example.com/a/67890",
                ),
            ],
            "12346": [
                Assignment(
                    id=67891,
                    name="Quiz",
                    course_id=12346,
                    points_possible=20.0,
                ),
            ],
        }

        await upsert_assignments(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 2
        ids = {r["id"] for r in rows}
        assert ids == {67890, 67891}

    async def test_upsert_assignments_row_fields(self) -> None:
        client = _mock_client()
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(
                    id=67890,
                    name="Essay",
                    course_id=12345,
                    due_at=datetime(2026, 3, 15, 23, 59, 59, tzinfo=UTC),
                    points_possible=50.0,
                    html_url="https://example.com/a/67890",
                ),
            ],
        }

        await upsert_assignments(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["id"] == 67890
        assert row["name"] == "Essay"
        assert row["course_id"] == 12345
        assert row["due_at"] == "2026-03-15T23:59:59+00:00"
        assert row["points_possible"] == 50.0
        assert row["html_url"] == "https://example.com/a/67890"
        assert "updated_at" in row

    async def test_upsert_assignments_null_fields(self) -> None:
        client = _mock_client()
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(id=1, name="No Due", course_id=12345),
            ],
        }

        await upsert_assignments(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["due_at"] is None
        assert row["points_possible"] is None

    async def test_upsert_assignments_empty_dict(self) -> None:
        client = _mock_client()

        await upsert_assignments(client, {})

        client.table.assert_not_called()

    async def test_upsert_assignments_on_conflict_id(self) -> None:
        client = _mock_client()
        assignments: dict[str, list[Assignment]] = {
            "1": [Assignment(id=1, name="Test", course_id=1)],
        }

        await upsert_assignments(client, assignments)

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "id"

    async def test_upsert_assignments_api_failure_raises_storage_error(
        self,
    ) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("network error")
        )
        assignments: dict[str, list[Assignment]] = {
            "1": [Assignment(id=1, name="Test", course_id=1)],
        }

        with pytest.raises(StorageError, match="network error"):
            await upsert_assignments(client, assignments)


# ------------------------------------------------------------------ #
#  upsert_submissions
# ------------------------------------------------------------------ #


class TestUpsertSubmissions:
    """upsert_submissions extracts submission from assignments and upserts."""

    async def test_upsert_submissions_extracts_from_assignments(self) -> None:
        client = _mock_client()
        sub = Submission(
            score=48.0,
            grade="48",
            submitted_at=datetime(2026, 3, 14, 10, 30, 0, tzinfo=UTC),
            workflow_state="graded",
        )
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(
                    id=67890,
                    name="Essay",
                    course_id=12345,
                    submission=sub,
                ),
            ],
        }

        await upsert_submissions(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row["assignment_id"] == 67890
        assert row["score"] == 48.0
        assert row["grade"] == "48"
        assert row["submitted_at"] == "2026-03-14T10:30:00+00:00"
        assert row["workflow_state"] == "graded"
        assert "updated_at" in row

    async def test_upsert_submissions_skips_none_submission(self) -> None:
        client = _mock_client()
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(
                    id=67892,
                    name="Proposal",
                    course_id=12345,
                    submission=None,
                ),
            ],
        }

        await upsert_submissions(client, assignments)

        # No submissions to upsert, so table() should not be called
        client.table.assert_not_called()

    async def test_upsert_submissions_mixed_some_with_none(self) -> None:
        client = _mock_client()
        sub = Submission(score=10.0, grade="10", workflow_state="graded")
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(id=1, name="A1", course_id=12345, submission=sub),
                Assignment(id=2, name="A2", course_id=12345, submission=None),
                Assignment(id=3, name="A3", course_id=12345, submission=sub),
            ],
        }

        await upsert_submissions(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 2
        assert {r["assignment_id"] for r in rows} == {1, 3}

    async def test_upsert_submissions_null_score_fields(self) -> None:
        client = _mock_client()
        sub = Submission(
            score=None, grade=None, submitted_at=None, workflow_state="unsubmitted"
        )
        assignments: dict[str, list[Assignment]] = {
            "12345": [
                Assignment(id=1, name="A1", course_id=12345, submission=sub),
            ],
        }

        await upsert_submissions(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["score"] is None
        assert row["grade"] is None
        assert row["submitted_at"] is None

    async def test_upsert_submissions_empty_dict(self) -> None:
        client = _mock_client()

        await upsert_submissions(client, {})

        client.table.assert_not_called()

    async def test_upsert_submissions_on_conflict_assignment_id(self) -> None:
        client = _mock_client()
        sub = Submission(score=10.0, workflow_state="graded")
        assignments: dict[str, list[Assignment]] = {
            "1": [Assignment(id=1, name="Test", course_id=1, submission=sub)],
        }

        await upsert_submissions(client, assignments)

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "assignment_id"

    async def test_upsert_submissions_api_failure_raises_storage_error(
        self,
    ) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("db error")
        )
        sub = Submission(score=10.0, workflow_state="graded")
        assignments: dict[str, list[Assignment]] = {
            "1": [Assignment(id=1, name="Test", course_id=1, submission=sub)],
        }

        with pytest.raises(StorageError, match="db error"):
            await upsert_submissions(client, assignments)

    async def test_upsert_submissions_includes_late_and_missing(self) -> None:
        client = _mock_client()
        sub = Submission(
            score=8.0,
            workflow_state="graded",
            late=True,
            missing=False,
        )
        assignments: dict[str, list[Assignment]] = {
            "1": [Assignment(id=1, name="Test", course_id=1, submission=sub)],
        }

        await upsert_submissions(client, assignments)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["late"] is True
        assert row["missing"] is False


# ------------------------------------------------------------------ #
#  upsert_enrollments
# ------------------------------------------------------------------ #


class TestUpsertEnrollments:
    """upsert_enrollments flattens grades dict to individual columns."""

    async def test_upsert_enrollments_with_grades(self) -> None:
        client = _mock_client()
        enrollments = [
            Enrollment(
                id=111,
                course_id=12345,
                type="StudentEnrollment",
                enrollment_state="active",
                grades={
                    "current_score": 96.2,
                    "current_grade": "A",
                    "final_score": 94.8,
                    "final_grade": "A",
                },
            ),
        ]

        await upsert_enrollments(client, enrollments)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == 111
        assert row["course_id"] == 12345
        assert row["type"] == "StudentEnrollment"
        assert row["enrollment_state"] == "active"
        assert row["current_score"] == 96.2
        assert row["current_grade"] == "A"
        assert row["final_score"] == 94.8
        assert row["final_grade"] == "A"
        assert "updated_at" in row

    async def test_upsert_enrollments_null_grades(self) -> None:
        client = _mock_client()
        enrollments = [
            Enrollment(
                id=112,
                course_id=12300,
                type="StudentEnrollment",
                enrollment_state="completed",
                grades=None,
            ),
        ]

        await upsert_enrollments(client, enrollments)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["current_score"] is None
        assert row["current_grade"] is None
        assert row["final_score"] is None
        assert row["final_grade"] is None

    async def test_upsert_enrollments_empty_list(self) -> None:
        client = _mock_client()

        await upsert_enrollments(client, [])

        client.table.assert_not_called()

    async def test_upsert_enrollments_on_conflict_id(self) -> None:
        client = _mock_client()
        enrollments = [
            Enrollment(id=1, course_id=1, type="StudentEnrollment"),
        ]

        await upsert_enrollments(client, enrollments)

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "id"

    async def test_upsert_enrollments_api_failure_raises_storage_error(
        self,
    ) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("permission denied")
        )
        enrollments = [
            Enrollment(id=1, course_id=1, type="StudentEnrollment"),
        ]

        with pytest.raises(StorageError, match="permission denied"):
            await upsert_enrollments(client, enrollments)

    async def test_upsert_enrollments_partial_grades(self) -> None:
        """Grades dict with only some keys still fills all columns."""
        client = _mock_client()
        enrollments = [
            Enrollment(
                id=113,
                course_id=12345,
                type="StudentEnrollment",
                enrollment_state="active",
                grades={"current_score": 85.0},
            ),
        ]

        await upsert_enrollments(client, enrollments)

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["current_score"] == 85.0
        assert row["current_grade"] is None
        assert row["final_score"] is None
        assert row["final_grade"] is None
