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
    from mitty.models import Assignment, Course, Enrollment, ModuleItem, Quiz

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


# ------------------------------------------------------------------ #
#  Quizzes → Assessments
# ------------------------------------------------------------------ #


async def upsert_quizzes_as_assessments(
    client: AsyncClient,
    quizzes: list[Quiz],
    course_id: int,
) -> None:
    """Batch upsert quizzes as assessment rows.

    Each :class:`~mitty.models.Quiz` is mapped to an ``assessments`` row
    with ``assessment_type='quiz'``, ``source='canvas_quiz'``, and
    ``canvas_quiz_id`` set to the quiz's Canvas ID.  If the quiz has an
    ``assignment_id``, ``canvas_assignment_id`` is set for cross-linking.

    Upserts on ``canvas_quiz_id`` for idempotent re-sync.

    Args:
        client: Async Supabase client.
        quizzes: List of Quiz models to upsert.
        course_id: The Canvas course ID these quizzes belong to.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not quizzes:
        return

    now = _now_iso()
    rows = []
    for quiz in quizzes:
        row: dict = {
            "course_id": course_id,
            "name": quiz.title,
            "assessment_type": "quiz",
            "scheduled_date": (quiz.due_at.isoformat() if quiz.due_at else None),
            "weight": quiz.points_possible,
            "description": quiz.description,
            "canvas_quiz_id": quiz.id,
            "auto_created": True,
            "source": "canvas_quiz",
            "created_at": now,
            "updated_at": now,
        }
        if quiz.assignment_id is not None:
            row["canvas_assignment_id"] = quiz.assignment_id
        rows.append(row)

    try:
        await (
            client.table("assessments")
            .upsert(rows, on_conflict="canvas_quiz_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert quizzes as assessments: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d quizzes as assessments", len(rows))


# ------------------------------------------------------------------ #
#  Grade Snapshots
# ------------------------------------------------------------------ #


async def _get_latest_snapshots(
    client: AsyncClient,
    enrollment_ids: list[int],
) -> dict[int, dict]:
    """Fetch the most recent grade snapshot per enrollment.

    Queries the ``grade_snapshots`` table for the given enrollment IDs,
    ordered by ``scraped_at`` descending, and returns a dict mapping each
    enrollment ID to its latest grade field values.

    Args:
        client: Async Supabase client.
        enrollment_ids: Enrollment IDs to look up.

    Returns:
        Mapping of enrollment_id -> dict with grade field values.
        Enrollments without a prior snapshot are absent from the dict.

    Raises:
        StorageError: If the Supabase query fails.
    """
    if not enrollment_ids:
        return {}

    try:
        response = await (
            client.table("grade_snapshots")
            .select("enrollment_id,current_score,current_grade,final_score,final_grade")
            .in_("enrollment_id", enrollment_ids)
            .order("scraped_at", desc=True)
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to fetch latest snapshots: {exc}"
        raise StorageError(msg) from exc

    # Group by enrollment_id, keep only the first (most recent) per enrollment.
    latest: dict[int, dict] = {}
    for row in response.data:
        eid = row["enrollment_id"]
        if eid not in latest:
            latest[eid] = {col: row.get(col) for col in _GRADE_COLUMNS}
    return latest


async def insert_grade_snapshots(
    client: AsyncClient,
    enrollments: list[Enrollment],
) -> None:
    """Insert grade snapshots only for enrollments whose grades changed.

    Compares each enrollment's current grades against the most recent
    stored snapshot.  A new row is inserted only when at least one grade
    field differs.  First-time scrapes (no prior snapshot) always insert.

    Args:
        client: Async Supabase client.
        enrollments: List of Enrollment models with current grades.

    Raises:
        StorageError: If the Supabase insert fails.
    """
    if not enrollments:
        return

    enrollment_ids = [e.id for e in enrollments]
    latest = await _get_latest_snapshots(client, enrollment_ids)

    now = _now_iso()
    rows: list[dict] = []
    for enrollment in enrollments:
        current_grades = {
            col: (enrollment.grades or {}).get(col) for col in _GRADE_COLUMNS
        }
        previous = latest.get(enrollment.id)

        if previous is not None and current_grades == previous:
            continue  # No change — skip

        rows.append(
            {
                "enrollment_id": enrollment.id,
                "course_id": enrollment.course_id,
                "scraped_at": now,
                **current_grades,
            }
        )

    if not rows:
        logger.info("No grade changes detected, skipping snapshot insert")
        return

    try:
        await client.table("grade_snapshots").insert(rows).execute()
    except Exception as exc:
        msg = f"Failed to insert grade snapshots: {exc}"
        raise StorageError(msg) from exc

    logger.info("Inserted %d grade snapshots", len(rows))


# ------------------------------------------------------------------ #
#  Module Items → Resources
# ------------------------------------------------------------------ #

# Map Canvas module item types to our resource_type values.
_ITEM_TYPE_MAP: dict[str, str] = {
    "Page": "canvas_page",
    "File": "file",
    "ExternalUrl": "link",
    "Assignment": "link",
}


async def upsert_module_items_as_resources(
    client: AsyncClient,
    items: list[ModuleItem],
    course_id: int,
    module_name: str,
) -> None:
    """Upsert module items as resource rows.

    Each :class:`~mitty.models.ModuleItem` is mapped to a resource row with
    the appropriate ``resource_type`` derived from the item's Canvas type.
    Items whose type is not in the mapping (e.g. ``SubHeader``) are skipped.

    Args:
        client: Async Supabase client.
        items: List of ModuleItem models to upsert.
        course_id: The Canvas course ID these items belong to.
        module_name: The human-readable name of the parent module
            (denormalized into each row).

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    rows: list[dict] = []
    now = _now_iso()
    for item in items:
        resource_type = _ITEM_TYPE_MAP.get(item.type)
        if resource_type is None:
            continue

        row: dict = {
            "course_id": course_id,
            "title": item.title,
            "resource_type": resource_type,
            "source_url": item.external_url or item.page_url,
            "canvas_module_id": item.module_id,
            "canvas_item_id": item.id,
            "module_name": module_name,
            "module_position": item.position,
            "sort_order": item.position,
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)

    if not rows:
        return

    try:
        await (
            client.table("resources")
            .upsert(rows, on_conflict="canvas_item_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert module items as resources: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d module item resources", len(rows))


# ------------------------------------------------------------------ #
#  Orchestrator
# ------------------------------------------------------------------ #


async def store_all(
    client: AsyncClient,
    data: dict,
) -> None:
    """Persist all scraped data to Supabase in FK-safe order.

    Calls upsert/insert functions sequentially in dependency order:
    courses -> enrollments -> assignments -> submissions -> grade_snapshots.

    Args:
        client: Async Supabase client.
        data: Dict with keys "courses", "assignments", "enrollments"
              (same shape as ``fetch_all()`` output).

    Raises:
        StorageError: If any upsert/insert step fails.
    """
    courses = data.get("courses", [])
    assignments = data.get("assignments", {})
    enrollments = data.get("enrollments", [])

    steps = [
        ("upsert_courses", upsert_courses, [client, courses]),
        ("upsert_enrollments", upsert_enrollments, [client, enrollments]),
        ("upsert_assignments", upsert_assignments, [client, assignments]),
        ("upsert_submissions", upsert_submissions, [client, assignments]),
        ("insert_grade_snapshots", insert_grade_snapshots, [client, enrollments]),
    ]

    for step_name, func, args in steps:
        logger.info("store_all: starting %s", step_name)
        try:
            await func(*args)
        except StorageError:
            raise
        except Exception as exc:
            msg = f"store_all failed at step '{step_name}': {exc}"
            raise StorageError(msg) from exc
