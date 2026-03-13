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
    from mitty.chunking import Chunk
    from mitty.models import (
        Assignment,
        CalendarEvent,
        Course,
        DiscussionTopic,
        Enrollment,
        FileMetadata,
        ModuleItem,
        Page,
        Quiz,
    )

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
#  Calendar Events → Assessments
# ------------------------------------------------------------------ #


async def upsert_calendar_events_as_assessments(
    client: AsyncClient,
    events: list[CalendarEvent],
) -> None:
    """Batch upsert classified calendar events as assessment rows.

    Each :class:`~mitty.models.CalendarEvent` is mapped to an ``assessments``
    row with ``source='calendar_event'`` and ``auto_created=True``.  The
    ``canvas_event_id`` column is used for idempotent upserts.

    The course ID is extracted from the event's ``context_code`` field
    (e.g. ``"course_12345"`` -> ``12345``).

    Args:
        client: Async Supabase client.
        events: List of CalendarEvent models that have already been
            classified as assessment-worthy.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not events:
        return

    now = _now_iso()
    rows: list[dict] = []
    for event in events:
        # Extract course_id from context_code like "course_12345"
        course_id: int | None = None
        if event.context_code.startswith("course_"):
            try:
                course_id = int(event.context_code.removeprefix("course_"))
            except ValueError:
                logger.warning(
                    "Cannot parse course_id from context_code=%r, skipping event %d",
                    event.context_code,
                    event.id,
                )
                continue

        if course_id is None:
            logger.debug("Skipping event %d — no course context_code", event.id)
            continue

        row: dict = {
            "course_id": course_id,
            "name": event.title,
            "assessment_type": "calendar_event",
            "scheduled_date": (event.start_at.isoformat() if event.start_at else None),
            "description": event.description,
            "canvas_event_id": event.id,
            "auto_created": True,
            "source": "calendar_event",
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)

    if not rows:
        return

    try:
        await (
            client.table("assessments")
            .upsert(rows, on_conflict="canvas_event_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert calendar events as assessments: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d calendar events as assessments", len(rows))


# ------------------------------------------------------------------ #
#  Assignments → Assessments (via classifier)
# ------------------------------------------------------------------ #


async def upsert_assignments_as_assessments(
    client: AsyncClient,
    assignments: dict[str, list[Assignment]],
) -> None:
    """Classify assignments and upsert matching ones as assessment rows.

    Runs :func:`~mitty.planner.classify.is_assessment_assignment` on each
    assignment name.  Assignments that match are upserted into the
    ``assessments`` table with ``source='canvas_assignment'`` and
    ``auto_created=True``.

    Uses ``on_conflict="canvas_assignment_id"`` for idempotent re-sync.
    Does **not** overwrite assessments created from quizzes or calendar
    events — those use different conflict columns.

    Args:
        client: Async Supabase client.
        assignments: Mapping of course_id (str) to assignment lists
            (same shape as ``fetch_all()`` output).

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    from mitty.planner.classify import is_assessment_assignment

    now = _now_iso()
    rows: list[dict] = []
    for assignment_list in assignments.values():
        for assignment in assignment_list:
            assessment_type = is_assessment_assignment(assignment.name)
            if assessment_type is None:
                continue

            row: dict = {
                "course_id": assignment.course_id,
                "name": assignment.name,
                "assessment_type": assessment_type,
                "scheduled_date": (
                    assignment.due_at.isoformat() if assignment.due_at else None
                ),
                "weight": assignment.points_possible,
                "canvas_assignment_id": assignment.id,
                "auto_created": True,
                "source": "canvas_assignment",
                "created_at": now,
                "updated_at": now,
            }
            rows.append(row)

    if not rows:
        logger.info("No assignments classified as assessments")
        return

    try:
        await (
            client.table("assessments")
            .upsert(rows, on_conflict="canvas_assignment_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert assignments as assessments: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d assignments as assessments", len(rows))


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
    *,
    page_content: dict[int, str] | None = None,
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
        page_content: Optional mapping of ``module_item_id`` to plain-text
            page body, as returned by
            :func:`~mitty.canvas.fetcher.resolve_module_item_pages`.
            Used to populate ``content_text`` on Page-type resources.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    resolved = page_content or {}
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
        content_text = resolved.get(item.id)
        if content_text:
            row["content_text"] = content_text
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
#  Pages → Resources
# ------------------------------------------------------------------ #


async def upsert_pages_as_resources(
    client: AsyncClient,
    pages: list[Page],
    course_id: int,
    *,
    canvas_base_url: str = "https://mitty.instructure.com",
) -> None:
    """Upsert Canvas wiki pages as resource rows.

    Each page is mapped to a resource with ``resource_type='canvas_page'``,
    ``content_text`` set to the (already stripped) plain-text body, and
    ``source_url`` pointing to the page on Canvas.

    Deduplication uses the ``canvas_item_id`` column (unique), set to
    the page's ``page_id`` with a ``1_000_000_000`` offset to avoid collisions
    with module-item IDs.

    Args:
        client: Async Supabase client.
        pages: List of Page models (bodies should already be plain text).
        course_id: The Canvas course ID these pages belong to.
        canvas_base_url: Root URL for building source links.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not pages:
        return

    now = _now_iso()
    rows: list[dict] = []
    for page in pages:
        source_url = f"{canvas_base_url}/courses/{course_id}/pages/{page.url}"
        row: dict = {
            "course_id": course_id,
            "title": page.title,
            "resource_type": "canvas_page",
            "source_url": source_url,
            "content_text": page.body,
            "canvas_item_id": 1_000_000_000 + page.page_id,
            "sort_order": 0,
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)

    try:
        await (
            client.table("resources")
            .upsert(rows, on_conflict="canvas_item_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert pages as resources: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d pages as resources", len(rows))


# ------------------------------------------------------------------ #
#  Chunking: auto-chunk resources with content_text
# ------------------------------------------------------------------ #


async def chunk_and_store_resources(
    client: AsyncClient,
    canvas_item_ids: list[int],
) -> None:
    """Chunk and store text for resources identified by canvas_item_id.

    For each *canvas_item_id*, looks up the resource row, and if it has
    non-empty ``content_text``, runs the async chunking pipeline and
    replaces any existing chunks via :func:`insert_resource_chunks`.

    Resources without ``content_text`` (empty or ``None``) are skipped.

    Args:
        client: Async Supabase client.
        canvas_item_ids: List of ``canvas_item_id`` values whose
            resources should be chunked.

    Raises:
        StorageError: If a Supabase query or chunk insert fails.
    """
    from mitty.chunking import achunk_text

    if not canvas_item_ids:
        return

    # Fetch resources matching the given canvas_item_ids.
    try:
        response = await (
            client.table("resources")
            .select("id,canvas_item_id,content_text")
            .in_("canvas_item_id", canvas_item_ids)
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to query resources for chunking: {exc}"
        raise StorageError(msg) from exc

    chunked_count = 0
    for row in response.data:
        content = row.get("content_text")
        if not content or not content.strip():
            continue

        resource_id = row["id"]
        chunks = await achunk_text(content)
        if chunks:
            await insert_resource_chunks(client, resource_id, chunks)
            chunked_count += 1

    logger.info(
        "Chunked %d resources (of %d candidates)",
        chunked_count,
        len(canvas_item_ids),
    )


# ------------------------------------------------------------------ #
#  Files → Resources
# ------------------------------------------------------------------ #


async def upsert_files_as_resources(
    client: AsyncClient,
    files: list[FileMetadata],
    course_id: int,
) -> None:
    """Upsert Canvas file metadata as resource rows.

    Each file is mapped to a resource with ``resource_type='file'``,
    ``source_url`` set to the file's download URL, and ``title`` set
    to ``display_name``.  No file content is downloaded or stored.

    Deduplication uses the ``canvas_item_id`` column, set to the
    file's Canvas ID.

    Args:
        client: Async Supabase client.
        files: List of FileMetadata models to upsert.
        course_id: The Canvas course ID these files belong to.

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not files:
        return

    now = _now_iso()
    rows: list[dict] = []
    for file in files:
        row: dict = {
            "course_id": course_id,
            "title": file.display_name,
            "resource_type": "file",
            "source_url": file.url or None,
            "canvas_item_id": file.id,
            "sort_order": 0,
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)

    try:
        await (
            client.table("resources")
            .upsert(rows, on_conflict="canvas_item_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert files as resources: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d files as resources", len(rows))


# ------------------------------------------------------------------ #
#  Discussion Topics → Resources
# ------------------------------------------------------------------ #

# Offset for discussion topic canvas_item_id to avoid collisions with
# module-item IDs (raw) and page IDs (1_000_000_000 offset).
_DISCUSSION_ID_OFFSET = 2_000_000_000


async def upsert_discussions_as_resources(
    client: AsyncClient,
    topics: list[DiscussionTopic],
    course_id: int,
    *,
    canvas_base_url: str = "https://mitty.instructure.com",
) -> list[int]:
    """Upsert Canvas discussion topics as resource rows.

    Each topic is mapped to a resource with ``resource_type='discussion'``,
    ``content_text`` set to the (already stripped) plain-text message, and
    ``source_url`` pointing to the topic on Canvas.

    Deduplication uses the ``canvas_item_id`` column (unique), set to
    the topic's ``id`` with a ``2_000_000_000`` offset to avoid collisions
    with module-item IDs and page IDs.

    Args:
        client: Async Supabase client.
        topics: List of DiscussionTopic models (messages should already
            be plain text).
        course_id: The Canvas course ID these topics belong to.
        canvas_base_url: Root URL for building source links.

    Returns:
        List of canvas_item_ids that were upserted (for downstream chunking).

    Raises:
        StorageError: If the Supabase upsert fails.
    """
    if not topics:
        return []

    now = _now_iso()
    rows: list[dict] = []
    canvas_item_ids: list[int] = []
    for topic in topics:
        source_url = (
            topic.html_url
            or f"{canvas_base_url}/courses/{course_id}/discussion_topics/{topic.id}"
        )
        canvas_item_id = _DISCUSSION_ID_OFFSET + topic.id
        row: dict = {
            "course_id": course_id,
            "title": topic.title,
            "resource_type": "discussion",
            "source_url": source_url,
            "content_text": topic.message,
            "canvas_item_id": canvas_item_id,
            "sort_order": 0,
            "created_at": now,
            "updated_at": now,
        }
        rows.append(row)
        canvas_item_ids.append(canvas_item_id)

    try:
        await (
            client.table("resources")
            .upsert(rows, on_conflict="canvas_item_id")
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to upsert discussions as resources: {exc}"
        raise StorageError(msg) from exc

    logger.info("Upserted %d discussions as resources", len(rows))
    return canvas_item_ids


# ------------------------------------------------------------------ #
#  Resource Chunks
# ------------------------------------------------------------------ #


async def insert_resource_chunks(
    client: AsyncClient,
    resource_id: int,
    chunks: list[Chunk],
) -> None:
    """Insert chunked text rows for a resource.

    Deletes any existing chunks for the given *resource_id* first
    (full replace strategy), then inserts the new chunks.

    Args:
        client: Async Supabase client.
        resource_id: The ID of the parent resource.
        chunks: List of :class:`~mitty.chunking.Chunk` objects to store.

    Raises:
        StorageError: If the Supabase delete or insert fails.
    """
    if not chunks:
        return

    # Delete existing chunks for this resource (idempotent re-chunk).
    try:
        await (
            client.table("resource_chunks")
            .delete()
            .eq("resource_id", resource_id)
            .execute()
        )
    except Exception as exc:
        msg = f"Failed to delete existing chunks for resource {resource_id}: {exc}"
        raise StorageError(msg) from exc

    now = _now_iso()
    rows: list[dict] = []
    for chunk in chunks:
        rows.append(
            {
                "resource_id": resource_id,
                "chunk_index": chunk.chunk_index,
                "content_text": chunk.content_text,
                "token_count": chunk.token_count,
                "created_at": now,
            }
        )

    try:
        await client.table("resource_chunks").insert(rows).execute()
    except Exception as exc:
        logger.critical(
            "Chunks deleted but insert failed for resource %d — "
            "re-run ingestion to recover: %s",
            resource_id,
            exc,
        )
        msg = f"Failed to insert resource chunks for resource {resource_id}: {exc}"
        raise StorageError(msg) from exc

    logger.info("Inserted %d chunks for resource %d", len(rows), resource_id)


# ------------------------------------------------------------------ #
#  Orchestrator
# ------------------------------------------------------------------ #


async def store_all(
    client: AsyncClient,
    data: dict,
) -> None:
    """Persist all scraped data to Supabase in FK-safe order.

    Calls upsert/insert functions sequentially in dependency order:

    1. courses (parent for everything)
    2. enrollments
    3. assignments -> submissions
    4. grade_snapshots
    5. quizzes -> assessments
    6. module_items -> resources
    7. pages -> resources
    8. files -> resources
    9. discussion_topics -> resources
    10. chunk resources with content_text (pages + discussions)
    11. calendar_events -> assessments (filtered by classifier)
    12. assignments -> assessments (filtered by classifier)

    Args:
        client: Async Supabase client.
        data: Dict with keys matching ``fetch_all()`` output shape.

    Raises:
        StorageError: If any upsert/insert step fails.
    """
    from mitty.canvas.classify import is_assessment_event

    courses = data.get("courses", [])
    assignments = data.get("assignments", {})
    enrollments = data.get("enrollments", [])
    quizzes = data.get("quizzes", {})
    modules_data = data.get("modules", {})
    pages = data.get("pages", {})
    files = data.get("files", {})
    discussion_topics = data.get("discussion_topics", {})
    calendar_events = data.get("calendar_events", [])

    # Phase 1: existing core data
    steps: list[tuple[str, object, list]] = [
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

    # Phase 2: quizzes as assessments (per-course)
    for course_id_str, quiz_list in quizzes.items():
        step_name = f"upsert_quizzes_as_assessments[{course_id_str}]"
        logger.info("store_all: starting %s", step_name)
        try:
            await upsert_quizzes_as_assessments(client, quiz_list, int(course_id_str))
        except StorageError:
            raise
        except Exception as exc:
            msg = f"store_all failed at step '{step_name}': {exc}"
            raise StorageError(msg) from exc

    # Phase 2: module items as resources (per-course, per-module)
    for course_id_str, mod_data in modules_data.items():
        course_modules = mod_data.get("modules", [])
        module_items = mod_data.get("module_items", {})
        resolved_page_content = mod_data.get("resolved_page_content", {})
        for mod in course_modules:
            items = module_items.get(mod.id, [])
            if not items:
                continue
            step_name = f"upsert_module_items_as_resources[{course_id_str}/{mod.id}]"
            logger.info("store_all: starting %s", step_name)
            try:
                await upsert_module_items_as_resources(
                    client,
                    items,
                    int(course_id_str),
                    mod.name,
                    page_content=resolved_page_content,
                )
            except StorageError:
                raise
            except Exception as exc:
                msg = f"store_all failed at step '{step_name}': {exc}"
                raise StorageError(msg) from exc

    # Phase 2: pages as resources (per-course)
    page_canvas_item_ids: list[int] = []
    for course_id_str, page_list in pages.items():
        step_name = f"upsert_pages_as_resources[{course_id_str}]"
        logger.info("store_all: starting %s", step_name)
        try:
            await upsert_pages_as_resources(client, page_list, int(course_id_str))
        except StorageError:
            raise
        except Exception as exc:
            msg = f"store_all failed at step '{step_name}': {exc}"
            raise StorageError(msg) from exc
        # Collect canvas_item_ids for pages that have content
        for page in page_list:
            if page.body and page.body.strip():
                page_canvas_item_ids.append(1_000_000_000 + page.page_id)

    # Phase 2: files as resources (per-course)
    for course_id_str, file_list in files.items():
        step_name = f"upsert_files_as_resources[{course_id_str}]"
        logger.info("store_all: starting %s", step_name)
        try:
            await upsert_files_as_resources(client, file_list, int(course_id_str))
        except StorageError:
            raise
        except Exception as exc:
            msg = f"store_all failed at step '{step_name}': {exc}"
            raise StorageError(msg) from exc

    # Phase 4: discussion topics as resources (per-course)
    discussion_canvas_item_ids: list[int] = []
    for course_id_str, topic_list in discussion_topics.items():
        step_name = f"upsert_discussions_as_resources[{course_id_str}]"
        logger.info("store_all: starting %s", step_name)
        try:
            ids = await upsert_discussions_as_resources(
                client, topic_list, int(course_id_str)
            )
            # Collect IDs for topics that have content for chunking
            for topic, cid in zip(topic_list, ids, strict=True):
                if topic.message and topic.message.strip():
                    discussion_canvas_item_ids.append(cid)
        except StorageError:
            raise
        except Exception as exc:
            msg = f"store_all failed at step '{step_name}': {exc}"
            raise StorageError(msg) from exc

    # Chunk resources with content_text (pages + discussions)
    all_chunkable_ids = page_canvas_item_ids + discussion_canvas_item_ids
    if all_chunkable_ids:
        step_name = "chunk_and_store_resources"
        logger.info("store_all: starting %s", step_name)
        try:
            await chunk_and_store_resources(client, all_chunkable_ids)
        except StorageError:
            raise
        except Exception as exc:
            msg = f"store_all failed at step '{step_name}': {exc}"
            raise StorageError(msg) from exc

    # Phase 2: calendar events as assessments (global, filtered)
    if not calendar_events:
        assessment_events = []
    else:
        assessment_events = [e for e in calendar_events if is_assessment_event(e.title)]
    step_name = "upsert_calendar_events_as_assessments"
    logger.info("store_all: starting %s", step_name)
    try:
        await upsert_calendar_events_as_assessments(client, assessment_events)
    except StorageError:
        raise
    except Exception as exc:
        msg = f"store_all failed at step '{step_name}': {exc}"
        raise StorageError(msg) from exc

    # Phase 2: assignments as assessments (via classifier)
    step_name = "upsert_assignments_as_assessments"
    logger.info("store_all: starting %s", step_name)
    try:
        await upsert_assignments_as_assessments(client, assignments)
    except StorageError:
        raise
    except Exception as exc:
        msg = f"store_all failed at step '{step_name}': {exc}"
        raise StorageError(msg) from exc
