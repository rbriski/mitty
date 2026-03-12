"""Tests for mitty.storage — Supabase async storage functions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.models import (
    Assignment,
    Course,
    Enrollment,
    FileMetadata,
    ModuleItem,
    Page,
    Quiz,
    Submission,
    Term,
)
from mitty.storage import (
    StorageError,
    _get_latest_snapshots,
    create_storage,
    insert_grade_snapshots,
    store_all,
    upsert_assignments,
    upsert_courses,
    upsert_enrollments,
    upsert_files_as_resources,
    upsert_module_items_as_resources,
    upsert_pages_as_resources,
    upsert_quizzes_as_assessments,
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


def _mock_snapshot_client(
    *, select_data: list[dict] | None = None, insert_fail: bool = False
) -> AsyncMock:
    """Build a mock client supporting both select chain and insert chain.

    The select chain: table().select().in_().order().execute()
    The insert chain: table().insert().execute()
    """
    client = AsyncMock()

    select_result = MagicMock()
    select_result.data = select_data if select_data is not None else []

    insert_result = MagicMock()
    insert_result.data = []

    # Build a flexible table mock that supports both chains
    table_mock = MagicMock()

    # Select chain
    select_builder = MagicMock()
    in_builder = MagicMock()
    order_builder = MagicMock()
    order_builder.execute = AsyncMock(return_value=select_result)
    in_builder.order = MagicMock(return_value=order_builder)
    select_builder.in_ = MagicMock(return_value=in_builder)
    table_mock.select = MagicMock(return_value=select_builder)

    # Insert chain
    insert_builder = MagicMock()
    if insert_fail:
        insert_builder.execute = AsyncMock(side_effect=Exception("insert failed"))
    else:
        insert_builder.execute = AsyncMock(return_value=insert_result)
    table_mock.insert = MagicMock(return_value=insert_builder)

    client.table = MagicMock(return_value=table_mock)

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


# ------------------------------------------------------------------ #
#  upsert_quizzes_as_assessments
# ------------------------------------------------------------------ #


class TestUpsertQuizzesAsAssessments:
    """upsert_quizzes_as_assessments maps Quiz models to assessment rows."""

    async def test_upsert_quizzes_maps_to_assessments(self) -> None:
        """Each quiz becomes an assessment row with correct fields."""
        client = _mock_client()
        quizzes = [
            Quiz(
                id=5001,
                title="Chapter 5 Quiz",
                quiz_type="assignment",
                due_at=datetime(2026, 4, 10, 23, 59, 59, tzinfo=UTC),
                points_possible=25.0,
                time_limit=30,
                assignment_id=67900,
                description="<p>Quiz on chapters 4-5.</p>",
            ),
        ]

        await upsert_quizzes_as_assessments(client, quizzes, course_id=12345)

        client.table.assert_called_once_with("assessments")
        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row["course_id"] == 12345
        assert row["name"] == "Chapter 5 Quiz"
        assert row["assessment_type"] == "quiz"
        assert row["source"] == "canvas_quiz"
        assert row["canvas_quiz_id"] == 5001
        assert row["canvas_assignment_id"] == 67900
        assert row["scheduled_date"] == "2026-04-10T23:59:59+00:00"
        assert row["weight"] == 25.0
        assert row["description"] == "<p>Quiz on chapters 4-5.</p>"
        assert row["auto_created"] is True
        assert "created_at" in row
        assert "updated_at" in row

    async def test_upsert_quizzes_links_assignment_id(self) -> None:
        """Quiz with assignment_id sets canvas_assignment_id; without omits it."""
        client = _mock_client()
        quizzes = [
            Quiz(id=5001, title="Linked Quiz", assignment_id=67900),
            Quiz(id=5002, title="Unlinked Quiz", assignment_id=None),
        ]

        await upsert_quizzes_as_assessments(client, quizzes, course_id=12345)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 2

        linked = next(r for r in rows if r["canvas_quiz_id"] == 5001)
        unlinked = next(r for r in rows if r["canvas_quiz_id"] == 5002)
        assert linked["canvas_assignment_id"] == 67900
        assert "canvas_assignment_id" not in unlinked

    async def test_upsert_quizzes_idempotent_resync(self) -> None:
        """Upsert uses on_conflict='canvas_quiz_id' for idempotent re-sync."""
        client = _mock_client()
        quizzes = [Quiz(id=5001, title="Quiz 1")]

        await upsert_quizzes_as_assessments(client, quizzes, course_id=12345)

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "canvas_quiz_id"

    async def test_upsert_quizzes_empty_list(self) -> None:
        """Empty quiz list short-circuits without API calls."""
        client = _mock_client()

        await upsert_quizzes_as_assessments(client, [], course_id=12345)

        client.table.assert_not_called()

    async def test_upsert_quizzes_api_failure_raises_storage_error(self) -> None:
        """Supabase failure is wrapped in StorageError."""
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("db timeout")
        )
        quizzes = [Quiz(id=5001, title="Quiz 1")]

        with pytest.raises(StorageError, match="db timeout"):
            await upsert_quizzes_as_assessments(client, quizzes, course_id=12345)


# ------------------------------------------------------------------ #
#  _get_latest_snapshots
# ------------------------------------------------------------------ #


class TestGetLatestSnapshots:
    """_get_latest_snapshots fetches the most recent snapshot per enrollment."""

    async def test_returns_latest_per_enrollment(self) -> None:
        """Multiple rows per enrollment — only the first (most recent) kept."""
        client = _mock_snapshot_client(
            select_data=[
                # enrollment 1: most recent (appears first due to ORDER BY)
                {
                    "enrollment_id": 1,
                    "current_score": 95.0,
                    "current_grade": "A",
                    "final_score": 90.0,
                    "final_grade": "A-",
                },
                # enrollment 1: older snapshot (should be ignored)
                {
                    "enrollment_id": 1,
                    "current_score": 80.0,
                    "current_grade": "B-",
                    "final_score": 78.0,
                    "final_grade": "C+",
                },
                # enrollment 2: only one snapshot
                {
                    "enrollment_id": 2,
                    "current_score": 88.0,
                    "current_grade": "B+",
                    "final_score": 85.0,
                    "final_grade": "B",
                },
            ],
        )

        result = await _get_latest_snapshots(client, [1, 2])

        assert len(result) == 2
        assert result[1] == {
            "current_score": 95.0,
            "current_grade": "A",
            "final_score": 90.0,
            "final_grade": "A-",
        }
        assert result[2] == {
            "current_score": 88.0,
            "current_grade": "B+",
            "final_score": 85.0,
            "final_grade": "B",
        }

    async def test_empty_enrollment_ids_returns_empty_dict(self) -> None:
        """Empty list should short-circuit, no API calls."""
        client = _mock_snapshot_client()

        result = await _get_latest_snapshots(client, [])

        assert result == {}
        client.table.assert_not_called()

    async def test_no_snapshots_returns_empty_dict(self) -> None:
        """Enrollments with no prior snapshots → empty dict."""
        client = _mock_snapshot_client(select_data=[])

        result = await _get_latest_snapshots(client, [1, 2, 3])

        assert result == {}

    async def test_queries_correct_table_and_columns(self) -> None:
        """Verify the select chain calls the right table/columns/ordering."""
        client = _mock_snapshot_client(select_data=[])

        await _get_latest_snapshots(client, [10, 20])

        client.table.assert_called_once_with("grade_snapshots")
        table_mock = client.table.return_value
        table_mock.select.assert_called_once_with(
            "enrollment_id,current_score,current_grade,final_score,final_grade"
        )
        table_mock.select.return_value.in_.assert_called_once_with(
            "enrollment_id", [10, 20]
        )
        table_mock.select.return_value.in_.return_value.order.assert_called_once_with(
            "scraped_at", desc=True
        )

    async def test_api_failure_raises_storage_error(self) -> None:
        """Select chain failure is wrapped in StorageError."""
        client = _mock_snapshot_client()
        # Make the execute() call on the select chain fail
        table_mock = client.table.return_value
        table_mock.select.return_value.in_.return_value.order.return_value.execute = (
            AsyncMock(side_effect=Exception("select failed"))
        )

        with pytest.raises(StorageError, match="select failed"):
            await _get_latest_snapshots(client, [1])

    async def test_null_grade_fields_preserved(self) -> None:
        """Snapshot rows with None grade values are preserved correctly."""
        client = _mock_snapshot_client(
            select_data=[
                {
                    "enrollment_id": 1,
                    "current_score": None,
                    "current_grade": None,
                    "final_score": None,
                    "final_grade": None,
                },
            ],
        )

        result = await _get_latest_snapshots(client, [1])

        assert result[1] == {
            "current_score": None,
            "current_grade": None,
            "final_score": None,
            "final_grade": None,
        }


# ------------------------------------------------------------------ #
#  insert_grade_snapshots
# ------------------------------------------------------------------ #


class TestInsertGradeSnapshots:
    """insert_grade_snapshots compares grades and inserts only changes."""

    async def test_first_scrape_inserts_all(self) -> None:
        """No prior snapshots → all enrollments are inserted."""
        client = _mock_snapshot_client(select_data=[])
        enrollments = [
            Enrollment(
                id=1,
                course_id=100,
                type="StudentEnrollment",
                grades={
                    "current_score": 95.0,
                    "current_grade": "A",
                    "final_score": 90.0,
                    "final_grade": "A-",
                },
            ),
            Enrollment(
                id=2,
                course_id=200,
                type="StudentEnrollment",
                grades={
                    "current_score": 80.0,
                    "current_grade": "B-",
                    "final_score": 78.0,
                    "final_grade": "C+",
                },
            ),
        ]

        await insert_grade_snapshots(client, enrollments)

        # insert was called
        table_mock = client.table.return_value
        table_mock.insert.assert_called_once()
        rows = table_mock.insert.call_args[0][0]
        assert len(rows) == 2

        # Check row content
        row_by_eid = {r["enrollment_id"]: r for r in rows}
        assert row_by_eid[1]["course_id"] == 100
        assert row_by_eid[1]["current_score"] == 95.0
        assert row_by_eid[1]["current_grade"] == "A"
        assert row_by_eid[1]["final_score"] == 90.0
        assert row_by_eid[1]["final_grade"] == "A-"
        assert "scraped_at" in row_by_eid[1]

        assert row_by_eid[2]["course_id"] == 200
        assert row_by_eid[2]["current_score"] == 80.0

    async def test_no_change_skips_insert(self) -> None:
        """Latest snapshot matches current grades → nothing inserted."""
        client = _mock_snapshot_client(
            select_data=[
                {
                    "enrollment_id": 1,
                    "current_score": 95.0,
                    "current_grade": "A",
                    "final_score": 90.0,
                    "final_grade": "A-",
                },
            ],
        )
        enrollments = [
            Enrollment(
                id=1,
                course_id=100,
                type="StudentEnrollment",
                grades={
                    "current_score": 95.0,
                    "current_grade": "A",
                    "final_score": 90.0,
                    "final_grade": "A-",
                },
            ),
        ]

        await insert_grade_snapshots(client, enrollments)

        # insert should NOT be called since grades haven't changed
        table_mock = client.table.return_value
        table_mock.insert.assert_not_called()

    async def test_partial_change_inserts_changed_only(self) -> None:
        """Mix of changed and unchanged enrollments → only changed inserted."""
        client = _mock_snapshot_client(
            select_data=[
                # enrollment 1: unchanged
                {
                    "enrollment_id": 1,
                    "current_score": 95.0,
                    "current_grade": "A",
                    "final_score": 90.0,
                    "final_grade": "A-",
                },
                # enrollment 2: will be different
                {
                    "enrollment_id": 2,
                    "current_score": 80.0,
                    "current_grade": "B-",
                    "final_score": 78.0,
                    "final_grade": "C+",
                },
            ],
        )
        enrollments = [
            # Enrollment 1: same grades as snapshot
            Enrollment(
                id=1,
                course_id=100,
                type="StudentEnrollment",
                grades={
                    "current_score": 95.0,
                    "current_grade": "A",
                    "final_score": 90.0,
                    "final_grade": "A-",
                },
            ),
            # Enrollment 2: grades changed (score went up)
            Enrollment(
                id=2,
                course_id=200,
                type="StudentEnrollment",
                grades={
                    "current_score": 85.0,
                    "current_grade": "B",
                    "final_score": 82.0,
                    "final_grade": "B-",
                },
            ),
        ]

        await insert_grade_snapshots(client, enrollments)

        table_mock = client.table.return_value
        table_mock.insert.assert_called_once()
        rows = table_mock.insert.call_args[0][0]
        assert len(rows) == 1
        assert rows[0]["enrollment_id"] == 2
        assert rows[0]["current_score"] == 85.0

    async def test_empty_enrollments_skips(self) -> None:
        """Empty enrollments list → no API calls at all."""
        client = _mock_snapshot_client()

        await insert_grade_snapshots(client, [])

        client.table.assert_not_called()

    async def test_api_failure_raises_storage_error(self) -> None:
        """Insert failure is wrapped in StorageError."""
        client = _mock_snapshot_client(select_data=[], insert_fail=True)
        enrollments = [
            Enrollment(
                id=1,
                course_id=100,
                type="StudentEnrollment",
                grades={"current_score": 95.0},
            ),
        ]

        with pytest.raises(StorageError, match="insert failed"):
            await insert_grade_snapshots(client, enrollments)

    async def test_null_grades_handled(self) -> None:
        """Enrollment with grades=None vs snapshot with all None → no change."""
        client = _mock_snapshot_client(
            select_data=[
                {
                    "enrollment_id": 1,
                    "current_score": None,
                    "current_grade": None,
                    "final_score": None,
                    "final_grade": None,
                },
            ],
        )
        enrollments = [
            Enrollment(
                id=1,
                course_id=100,
                type="StudentEnrollment",
                grades=None,  # All grade columns will be None
            ),
        ]

        await insert_grade_snapshots(client, enrollments)

        # grades=None maps to all None, which matches the snapshot → skip
        table_mock = client.table.return_value
        table_mock.insert.assert_not_called()

    async def test_null_grades_first_scrape_inserts(self) -> None:
        """Enrollment with grades=None on first scrape → inserts with all None."""
        client = _mock_snapshot_client(select_data=[])
        enrollments = [
            Enrollment(
                id=1,
                course_id=100,
                type="StudentEnrollment",
                grades=None,
            ),
        ]

        await insert_grade_snapshots(client, enrollments)

        table_mock = client.table.return_value
        table_mock.insert.assert_called_once()
        rows = table_mock.insert.call_args[0][0]
        assert len(rows) == 1
        assert rows[0]["current_score"] is None
        assert rows[0]["current_grade"] is None
        assert rows[0]["final_score"] is None
        assert rows[0]["final_grade"] is None

    async def test_snapshot_row_includes_required_fields(self) -> None:
        """Each inserted row has enrollment_id, course_id, scraped_at, grades."""
        client = _mock_snapshot_client(select_data=[])
        enrollments = [
            Enrollment(
                id=42,
                course_id=999,
                type="StudentEnrollment",
                grades={
                    "current_score": 100.0,
                    "current_grade": "A+",
                    "final_score": 100.0,
                    "final_grade": "A+",
                },
            ),
        ]

        await insert_grade_snapshots(client, enrollments)

        table_mock = client.table.return_value
        rows = table_mock.insert.call_args[0][0]
        row = rows[0]

        # Required fields
        assert row["enrollment_id"] == 42
        assert row["course_id"] == 999
        assert "scraped_at" in row
        assert row["current_score"] == 100.0
        assert row["current_grade"] == "A+"
        assert row["final_score"] == 100.0
        assert row["final_grade"] == "A+"


# ------------------------------------------------------------------ #
#  store_all
# ------------------------------------------------------------------ #

# Patch targets for store_all tests.
_STORE_ALL_PATCHES = {
    "upsert_courses": "mitty.storage.upsert_courses",
    "upsert_enrollments": "mitty.storage.upsert_enrollments",
    "upsert_assignments": "mitty.storage.upsert_assignments",
    "upsert_submissions": "mitty.storage.upsert_submissions",
    "insert_grade_snapshots": "mitty.storage.insert_grade_snapshots",
}


class TestStoreAll:
    """store_all orchestrates all upserts in FK-safe order."""

    async def test_calls_all_upserts_in_order(self) -> None:
        """Full success path: all 5 functions called in correct FK order."""
        call_order: list[str] = []

        async def _track(name: str) -> AsyncMock:
            async def _side_effect(*_args: object, **_kwargs: object) -> None:
                call_order.append(name)

            return _side_effect

        client = AsyncMock()
        courses = [Course(id=1, name="AP English", course_code="ENG")]
        enrollments = [Enrollment(id=10, course_id=1, type="StudentEnrollment")]
        assignments: dict[str, list[Assignment]] = {
            "1": [Assignment(id=100, name="Essay", course_id=1)],
        }

        with (
            patch(
                _STORE_ALL_PATCHES["upsert_courses"],
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: call_order.append("upsert_courses"),
            ) as mock_courses,
            patch(
                _STORE_ALL_PATCHES["upsert_enrollments"],
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: call_order.append("upsert_enrollments"),
            ) as mock_enrollments,
            patch(
                _STORE_ALL_PATCHES["upsert_assignments"],
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: call_order.append("upsert_assignments"),
            ) as mock_assignments,
            patch(
                _STORE_ALL_PATCHES["upsert_submissions"],
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: call_order.append("upsert_submissions"),
            ) as mock_submissions,
            patch(
                _STORE_ALL_PATCHES["insert_grade_snapshots"],
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: call_order.append(
                    "insert_grade_snapshots"
                ),
            ) as mock_snapshots,
        ):
            await store_all(
                client,
                {
                    "courses": courses,
                    "assignments": assignments,
                    "enrollments": enrollments,
                },
            )

        # Verify FK-safe order
        assert call_order == [
            "upsert_courses",
            "upsert_enrollments",
            "upsert_assignments",
            "upsert_submissions",
            "insert_grade_snapshots",
        ]

        # Verify correct args passed
        mock_courses.assert_awaited_once_with(client, courses)
        mock_enrollments.assert_awaited_once_with(client, enrollments)
        mock_assignments.assert_awaited_once_with(client, assignments)
        mock_submissions.assert_awaited_once_with(client, assignments)
        mock_snapshots.assert_awaited_once_with(client, enrollments)

    async def test_failure_mid_sequence_raises_storage_error(self) -> None:
        """If a middle step fails, StorageError propagates."""
        client = AsyncMock()

        with (
            patch(
                _STORE_ALL_PATCHES["upsert_courses"],
                new_callable=AsyncMock,
            ),
            patch(
                _STORE_ALL_PATCHES["upsert_enrollments"],
                new_callable=AsyncMock,
            ),
            patch(
                _STORE_ALL_PATCHES["upsert_assignments"],
                new_callable=AsyncMock,
                side_effect=StorageError("Failed to upsert assignments: timeout"),
            ),
            patch(
                _STORE_ALL_PATCHES["upsert_submissions"],
                new_callable=AsyncMock,
            ) as mock_submissions,
            patch(
                _STORE_ALL_PATCHES["insert_grade_snapshots"],
                new_callable=AsyncMock,
            ) as mock_snapshots,
        ):
            with pytest.raises(StorageError, match="upsert assignments"):
                await store_all(
                    client,
                    {
                        "courses": [Course(id=1, name="Test", course_code="T")],
                        "assignments": {"1": [Assignment(id=1, name="A", course_id=1)]},
                        "enrollments": [
                            Enrollment(id=1, course_id=1, type="StudentEnrollment")
                        ],
                    },
                )

            # Steps after failure should NOT be called
            mock_submissions.assert_not_awaited()
            mock_snapshots.assert_not_awaited()

    async def test_empty_data_succeeds_silently(self) -> None:
        """Empty/missing keys don't cause errors."""
        client = AsyncMock()

        with (
            patch(
                _STORE_ALL_PATCHES["upsert_courses"],
                new_callable=AsyncMock,
            ) as mock_courses,
            patch(
                _STORE_ALL_PATCHES["upsert_enrollments"],
                new_callable=AsyncMock,
            ) as mock_enrollments,
            patch(
                _STORE_ALL_PATCHES["upsert_assignments"],
                new_callable=AsyncMock,
            ) as mock_assignments,
            patch(
                _STORE_ALL_PATCHES["upsert_submissions"],
                new_callable=AsyncMock,
            ) as mock_submissions,
            patch(
                _STORE_ALL_PATCHES["insert_grade_snapshots"],
                new_callable=AsyncMock,
            ) as mock_snapshots,
        ):
            # Completely empty dict
            await store_all(client, {})

            # All functions still called (with empty data)
            mock_courses.assert_awaited_once_with(client, [])
            mock_enrollments.assert_awaited_once_with(client, [])
            mock_assignments.assert_awaited_once_with(client, {})
            mock_submissions.assert_awaited_once_with(client, {})
            mock_snapshots.assert_awaited_once_with(client, [])

    async def test_ignores_errors_key(self) -> None:
        """The 'errors' key from fetch_all output is ignored."""
        client = AsyncMock()

        with (
            patch(
                _STORE_ALL_PATCHES["upsert_courses"],
                new_callable=AsyncMock,
            ) as mock_courses,
            patch(
                _STORE_ALL_PATCHES["upsert_enrollments"],
                new_callable=AsyncMock,
            ),
            patch(
                _STORE_ALL_PATCHES["upsert_assignments"],
                new_callable=AsyncMock,
            ),
            patch(
                _STORE_ALL_PATCHES["upsert_submissions"],
                new_callable=AsyncMock,
            ),
            patch(
                _STORE_ALL_PATCHES["insert_grade_snapshots"],
                new_callable=AsyncMock,
            ),
        ):
            courses = [Course(id=1, name="Test", course_code="T")]
            await store_all(
                client,
                {
                    "courses": courses,
                    "errors": ["some error that should be ignored"],
                },
            )

            # Should proceed normally, courses called with data
            mock_courses.assert_awaited_once_with(client, courses)


# ------------------------------------------------------------------ #
#  upsert_module_items_as_resources
# ------------------------------------------------------------------ #


def _make_module_item(
    item_id: int,
    module_id: int,
    title: str,
    item_type: str,
    position: int = 1,
    *,
    page_url: str | None = None,
    external_url: str | None = None,
) -> ModuleItem:
    """Create a ModuleItem instance for testing."""
    return ModuleItem(
        id=item_id,
        module_id=module_id,
        title=title,
        type=item_type,
        position=position,
        page_url=page_url,
        external_url=external_url,
    )


class TestUpsertModuleItemsAsResources:
    """upsert_module_items_as_resources maps ModuleItems to resource rows."""

    async def test_upsert_module_items_maps_types(self) -> None:
        """Page, File, ExternalUrl, Assignment are mapped to correct types."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Intro Page", "Page", page_url="intro-page"),
            _make_module_item(2, 100, "Rubric.pdf", "File"),
            _make_module_item(
                3,
                100,
                "External Link",
                "ExternalUrl",
                external_url="https://example.com",
            ),
            _make_module_item(4, 100, "HW 1", "Assignment"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 4
        type_map = {r["canvas_item_id"]: r["resource_type"] for r in rows}
        assert type_map[1] == "canvas_page"
        assert type_map[2] == "file"
        assert type_map[3] == "link"
        assert type_map[4] == "link"

    async def test_upsert_module_items_denormalizes_module_name(self) -> None:
        """Each row carries the module_name from the parent module."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Intro", "Page", page_url="intro"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1: Rhetoric"
        )

        rows = client.table.return_value.upsert.call_args[0][0]
        row = rows[0]
        assert row["module_name"] == "Unit 1: Rhetoric"
        assert row["canvas_module_id"] == 100
        assert row["course_id"] == 12345
        assert row["title"] == "Intro"

    async def test_upsert_module_items_idempotent(self) -> None:
        """Upsert uses on_conflict='canvas_item_id' for idempotency."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Page", "Page", page_url="p"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "canvas_item_id"

    async def test_skips_unknown_item_types(self) -> None:
        """SubHeader and other unknown types are silently skipped."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Header", "SubHeader"),
            _make_module_item(2, 100, "Page", "Page", page_url="p"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        assert rows[0]["canvas_item_id"] == 2

    async def test_empty_items_skips_upsert(self) -> None:
        """Empty items list does not call upsert."""
        client = _mock_client()

        await upsert_module_items_as_resources(
            client, [], course_id=12345, module_name="Unit 1"
        )

        client.table.assert_not_called()

    async def test_all_unknown_types_skips_upsert(self) -> None:
        """If all items are SubHeaders, no upsert happens."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Header", "SubHeader"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        client.table.assert_not_called()

    async def test_module_position_set_from_item(self) -> None:
        """module_position is taken from the item's position field."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Page", "Page", position=7, page_url="p"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        rows = client.table.return_value.upsert.call_args[0][0]
        assert rows[0]["module_position"] == 7
        assert rows[0]["sort_order"] == 7

    async def test_source_url_prefers_external_url(self) -> None:
        """ExternalUrl items use external_url as source_url."""
        client = _mock_client()
        items = [
            _make_module_item(
                1,
                100,
                "Link",
                "ExternalUrl",
                external_url="https://example.com",
            ),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        rows = client.table.return_value.upsert.call_args[0][0]
        assert rows[0]["source_url"] == "https://example.com"

    async def test_source_url_falls_back_to_page_url(self) -> None:
        """Page items use page_url as source_url."""
        client = _mock_client()
        items = [
            _make_module_item(1, 100, "Page", "Page", page_url="my-page"),
        ]

        await upsert_module_items_as_resources(
            client, items, course_id=12345, module_name="Unit 1"
        )

        rows = client.table.return_value.upsert.call_args[0][0]
        assert rows[0]["source_url"] == "my-page"

    async def test_api_failure_raises_storage_error(self) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("db error")
        )
        items = [
            _make_module_item(1, 100, "Page", "Page", page_url="p"),
        ]

        with pytest.raises(StorageError, match="db error"):
            await upsert_module_items_as_resources(
                client, items, course_id=12345, module_name="Unit 1"
            )


# ------------------------------------------------------------------ #
#  upsert_pages_as_resources
# ------------------------------------------------------------------ #


class TestUpsertPagesAsResources:
    """upsert_pages_as_resources maps Page models to resource rows."""

    async def test_upsert_pages_stores_plain_text(self) -> None:
        client = _mock_client()
        pages = [
            Page(
                page_id=8001,
                title="Course Syllabus",
                body="AP English Language\nWelcome to AP English.",
                url="course-syllabus",
            ),
        ]

        await upsert_pages_as_resources(client, pages, course_id=12345)

        client.table.assert_called_once_with("resources")
        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row["course_id"] == 12345
        assert row["title"] == "Course Syllabus"
        assert row["resource_type"] == "canvas_page"
        assert row["content_text"] == "AP English Language\nWelcome to AP English."
        assert row["source_url"] == (
            "https://mitty.instructure.com/courses/12345/pages/course-syllabus"
        )
        assert row["canvas_item_id"] == 9_000_000 + 8001
        assert "updated_at" in row
        assert "created_at" in row

    async def test_upsert_pages_null_body(self) -> None:
        client = _mock_client()
        pages = [
            Page(page_id=8002, title="Empty Page", body=None, url="empty-page"),
        ]

        await upsert_pages_as_resources(client, pages, course_id=12345)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert rows[0]["content_text"] is None

    async def test_upsert_pages_empty_list(self) -> None:
        client = _mock_client()

        await upsert_pages_as_resources(client, [], course_id=12345)

        client.table.assert_not_called()

    async def test_upsert_pages_on_conflict_canvas_item_id(self) -> None:
        client = _mock_client()
        pages = [
            Page(page_id=8001, title="Test", url="test"),
        ]

        await upsert_pages_as_resources(client, pages, course_id=1)

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "canvas_item_id"

    async def test_upsert_pages_api_failure_raises_storage_error(self) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("db error")
        )
        pages = [Page(page_id=8001, title="Test", url="test")]

        with pytest.raises(StorageError, match="db error"):
            await upsert_pages_as_resources(client, pages, course_id=1)

    async def test_upsert_pages_multiple(self) -> None:
        client = _mock_client()
        pages = [
            Page(page_id=8001, title="Page A", body="Text A", url="page-a"),
            Page(page_id=8002, title="Page B", body="Text B", url="page-b"),
        ]

        await upsert_pages_as_resources(client, pages, course_id=42)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 2
        ids = {r["canvas_item_id"] for r in rows}
        assert ids == {9_000_000 + 8001, 9_000_000 + 8002}


# ------------------------------------------------------------------ #
#  upsert_files_as_resources
# ------------------------------------------------------------------ #


class TestUpsertFilesAsResources:
    """upsert_files_as_resources maps FileMetadata models to resource rows."""

    async def test_upsert_files_stores_metadata_only(self) -> None:
        """File metadata is stored as resource rows without content."""
        client = _mock_client()
        files = [
            FileMetadata(
                id=9001,
                display_name="Unit1_Study_Guide.pdf",
                content_type="application/pdf",
                size=245760,
                url="https://mitty.instructure.com/files/9001/download",
                folder_id=4001,
            ),
        ]

        await upsert_files_as_resources(client, files, course_id=12345)

        client.table.assert_called_once_with("resources")
        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert row["course_id"] == 12345
        assert row["title"] == "Unit1_Study_Guide.pdf"
        assert row["resource_type"] == "file"
        assert row["source_url"] == "https://mitty.instructure.com/files/9001/download"
        assert row["canvas_item_id"] == 9001
        assert "updated_at" in row
        assert "created_at" in row
        # No content_text key — metadata only
        assert "content_text" not in row

    async def test_upsert_files_empty_list(self) -> None:
        """Empty files list does not call upsert."""
        client = _mock_client()

        await upsert_files_as_resources(client, [], course_id=12345)

        client.table.assert_not_called()

    async def test_upsert_files_on_conflict_canvas_item_id(self) -> None:
        """Upsert uses on_conflict='canvas_item_id' for dedup."""
        client = _mock_client()
        files = [
            FileMetadata(id=9001, display_name="test.pdf"),
        ]

        await upsert_files_as_resources(client, files, course_id=1)

        kwargs = client.table.return_value.upsert.call_args[1]
        assert kwargs.get("on_conflict") == "canvas_item_id"

    async def test_upsert_files_empty_url_becomes_none(self) -> None:
        """Files with empty URL string get source_url=None."""
        client = _mock_client()
        files = [
            FileMetadata(id=9003, display_name="sample.txt", url=""),
        ]

        await upsert_files_as_resources(client, files, course_id=12345)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert rows[0]["source_url"] is None

    async def test_upsert_files_multiple(self) -> None:
        """Multiple files are batched into a single upsert."""
        client = _mock_client()
        files = [
            FileMetadata(
                id=9001,
                display_name="file_a.pdf",
                url="https://example.com/a",
            ),
            FileMetadata(
                id=9002,
                display_name="file_b.docx",
                url="https://example.com/b",
            ),
        ]

        await upsert_files_as_resources(client, files, course_id=42)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 2
        ids = {r["canvas_item_id"] for r in rows}
        assert ids == {9001, 9002}

    async def test_upsert_files_api_failure_raises_storage_error(self) -> None:
        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("db error")
        )
        files = [FileMetadata(id=9001, display_name="test.pdf")]

        with pytest.raises(StorageError, match="db error"):
            await upsert_files_as_resources(client, files, course_id=1)
