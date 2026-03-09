"""Async Supabase storage — client setup and batch upsert functions.

Transforms Pydantic models from ``mitty.models`` into row dicts and
upserts them into Supabase tables.  All functions are async and raise
``StorageError`` on any Supabase API failure.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from supabase import AsyncClient, acreate_client

if TYPE_CHECKING:
    from mitty.models import Assignment, Course, Enrollment

logger = logging.getLogger(__name__)

# Grade columns flattened from the Enrollment.grades dict.
_GRADE_COLUMNS = ("current_score", "current_grade", "final_score", "final_grade")


class StorageError(Exception):
    """Raised when a Supabase operation fails."""


async def create_storage(
    *,
    supabase_url: str,
    supabase_key: str,
) -> AsyncClient:
    """Create and return an async Supabase client.

    Args:
        supabase_url: Supabase project URL.
        supabase_key: Supabase anon or service-role key.

    Returns:
        An initialised ``AsyncClient`` ready for table operations.

    Raises:
        StorageError: If client creation fails.
    """
    try:
        return await acreate_client(supabase_url, supabase_key)
    except Exception as exc:
        msg = f"Failed to create Supabase client: {exc}"
        raise StorageError(msg) from exc


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


# ------------------------------------------------------------------ #
#  Courses
# ------------------------------------------------------------------ #


async def upsert_courses(
    client: AsyncClient,
    courses: list[Course],
) -> None:
    """Batch upsert courses, denormalising the nested Term.

    The ``term`` field is flattened into ``term_id`` and ``term_name``
    columns.  An ``updated_at`` timestamp is set on every row.

    Args:
        client: Async Supabase client.
        courses: List of Course models to upsert.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not courses:
        return

    rows = []
    for course in courses:
        row: dict = {
            "id": course.id,
            "name": course.name,
            "course_code": course.course_code,
            "workflow_state": course.workflow_state,
            "term_id": course.term.id if course.term else None,
            "term_name": course.term.name if course.term else None,
            "updated_at": _now_iso(),
        }
        rows.append(row)

    try:
        await client.table("courses").upsert(rows, on_conflict="id").execute()
    except Exception as exc:
        msg = f"Failed to upsert courses: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d courses", len(rows))


# ------------------------------------------------------------------ #
#  Assignments
# ------------------------------------------------------------------ #


async def upsert_assignments(
    client: AsyncClient,
    assignments: dict[str, list[Assignment]],
) -> None:
    """Batch upsert assignments from a course_id-keyed dict.

    Flattens the nested dict into a single list of row dicts.
    Submission data is *not* included here (see ``upsert_submissions``).

    Args:
        client: Async Supabase client.
        assignments: Mapping of course_id (str) to assignment lists.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    rows = []
    for assignment_list in assignments.values():
        for assignment in assignment_list:
            row: dict = {
                "id": assignment.id,
                "name": assignment.name,
                "course_id": assignment.course_id,
                "due_at": (
                    assignment.due_at.isoformat() if assignment.due_at else None
                ),
                "points_possible": assignment.points_possible,
                "html_url": assignment.html_url,
                "updated_at": _now_iso(),
            }
            rows.append(row)

    if not rows:
        return

    try:
        await client.table("assignments").upsert(rows, on_conflict="id").execute()
    except Exception as exc:
        msg = f"Failed to upsert assignments: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d assignments", len(rows))


# ------------------------------------------------------------------ #
#  Submissions
# ------------------------------------------------------------------ #


async def upsert_submissions(
    client: AsyncClient,
    assignments: dict[str, list[Assignment]],
) -> None:
    """Batch upsert submissions extracted from assignments.

    Each assignment may carry an optional ``submission``.  Assignments
    without a submission (``None``) are skipped.

    Args:
        client: Async Supabase client.
        assignments: Mapping of course_id (str) to assignment lists.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    rows = []
    for assignment_list in assignments.values():
        for assignment in assignment_list:
            if assignment.submission is None:
                continue
            sub = assignment.submission
            row: dict = {
                "assignment_id": assignment.id,
                "score": sub.score,
                "grade": sub.grade,
                "submitted_at": (
                    sub.submitted_at.isoformat() if sub.submitted_at else None
                ),
                "workflow_state": sub.workflow_state,
                "late": sub.late,
                "missing": sub.missing,
                "updated_at": _now_iso(),
            }
            rows.append(row)

    if not rows:
        return

    try:
        await (
            client.table("submissions")
            .upsert(rows, on_conflict="assignment_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert submissions: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d submissions", len(rows))


# ------------------------------------------------------------------ #
#  Enrollments
# ------------------------------------------------------------------ #


async def upsert_enrollments(
    client: AsyncClient,
    enrollments: list[Enrollment],
) -> None:
    """Batch upsert enrollments, flattening the grades dict.

    The ``grades`` dict is expanded into individual columns:
    ``current_score``, ``current_grade``, ``final_score``, ``final_grade``.
    Missing or ``None`` grades result in ``None`` for all grade columns.

    Args:
        client: Async Supabase client.
        enrollments: List of Enrollment models to upsert.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not enrollments:
        return

    rows = []
    for enrollment in enrollments:
        grades = enrollment.grades or {}
        row: dict = {
            "id": enrollment.id,
            "course_id": enrollment.course_id,
            "type": enrollment.type,
            "enrollment_state": enrollment.enrollment_state,
            "updated_at": _now_iso(),
        }
        for col in _GRADE_COLUMNS:
            row[col] = grades.get(col)
        rows.append(row)

    try:
        await client.table("enrollments").upsert(rows, on_conflict="id").execute()
    except Exception as exc:
        msg = f"Failed to upsert enrollments: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d enrollments", len(rows))
