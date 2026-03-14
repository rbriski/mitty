"""Study plan generator orchestrator.

Reads inputs from Supabase (student signal, assignments, submissions,
assessments, enrollments, grade snapshots, mastery states), delegates to the
scoring engine and block allocator, and writes the resulting study_plan +
study_blocks rows back to Supabase.

Public API:
    generate_plan(client, user_id, plan_date) -> StudyPlan

Errors:
    PlanGenerationError — raised when generation cannot proceed (stale signal,
        missing critical data, conflicting active/completed plan).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from mitty.planner.allocator import StudyBlock, allocate_blocks
from mitty.planner.scoring import (
    StudentSignal,
    StudyOpportunity,
    score_opportunities,
)

if TYPE_CHECKING:
    from mitty.ai.client import AIClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# Maximum age of a student signal for it to be usable.
_SIGNAL_MAX_AGE = timedelta(hours=24)

# Per-block timeout for guide compilation (seconds).
_GUIDE_TIMEOUT_S: float = 15.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PlanGenerationError(Exception):
    """Raised when plan generation cannot proceed."""

    def __init__(self, message: str, *, code: str = "GENERATION_FAILED") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudyPlan:
    """Result of plan generation — the plan row + its blocks."""

    plan_id: int
    user_id: str
    plan_date: date
    total_minutes: int
    status: str
    blocks: list[StudyBlock]


# ---------------------------------------------------------------------------
# Supabase read helpers
# ---------------------------------------------------------------------------


async def _read_latest_signal(
    client: AsyncClient,
    user_id: str,
    plan_date: date,
) -> dict[str, Any]:
    """Fetch the most recent student signal within 24 hours of plan_date.

    Raises:
        PlanGenerationError: If no signal exists within the window.
    """
    # Compute the 24h window ending at end-of-day of plan_date.
    cutoff = (
        datetime(plan_date.year, plan_date.month, plan_date.day, tzinfo=UTC)
        - _SIGNAL_MAX_AGE
    )
    cutoff_iso = cutoff.isoformat()

    response = await (
        client.table("student_signals")
        .select("*")
        .eq("user_id", user_id)
        .gte("recorded_at", cutoff_iso)
        .order("recorded_at", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        msg = (
            f"No student signal found for user {user_id} within 24h of "
            f"{plan_date}. Ask the student to complete a check-in first."
        )
        raise PlanGenerationError(msg, code="NO_SIGNAL")

    return response.data[0]


async def _read_critical(
    client: AsyncClient,
    table: str,
    label: str,
    *,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read rows from a critical table — raises on empty or error.

    Args:
        client: Supabase async client.
        table: Table name.
        label: Human-readable label for error messages.
        filters: Optional eq-filters to apply.

    Raises:
        PlanGenerationError: If the query returns no data or fails.
    """
    try:
        query = client.table(table).select("*")
        for col, val in (filters or {}).items():
            query = query.eq(col, val)
        response = await query.execute()
    except Exception as exc:
        msg = f"Failed to read {label}: {exc}"
        raise PlanGenerationError(msg) from exc

    if not response.data:
        msg = f"No {label} found — cannot generate plan."
        raise PlanGenerationError(msg)

    return response.data


async def _read_non_critical(
    client: AsyncClient,
    table: str,
    label: str,
    *,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read rows from a non-critical table — returns [] with warning on failure.

    Args:
        client: Supabase async client.
        table: Table name.
        label: Human-readable label for log messages.
        filters: Optional eq-filters to apply.

    Returns:
        List of row dicts, or [] if the query fails or returns nothing.
    """
    try:
        query = client.table(table).select("*")
        for col, val in (filters or {}).items():
            query = query.eq(col, val)
        response = await query.execute()
    except Exception as exc:
        logger.warning("Failed to read %s (non-critical, continuing): %s", label, exc)
        return []

    if not response.data:
        logger.warning("No %s found — plan quality may be reduced.", label)
        return []

    return response.data


# ---------------------------------------------------------------------------
# Existing plan check
# ---------------------------------------------------------------------------


async def _check_existing_plan(
    client: AsyncClient,
    user_id: str,
    plan_date: date,
) -> None:
    """Check for an existing plan on the same date.

    - Draft plans are deleted (replaced).
    - Active or completed plans cause an error.

    Raises:
        PlanGenerationError: If an active or completed plan exists.
    """
    plan_date_iso = plan_date.isoformat()
    response = await (
        client.table("study_plans")
        .select("id,status")
        .eq("user_id", user_id)
        .eq("plan_date", plan_date_iso)
        .execute()
    )

    for plan in response.data or []:
        status = plan["status"]
        plan_id = plan["id"]
        if status in ("active", "completed"):
            msg = (
                f"A plan with status '{status}' already exists for "
                f"{plan_date} (plan_id={plan_id}). Cannot replace."
            )
            raise PlanGenerationError(msg, code="PLAN_EXISTS")

        if status == "draft":
            logger.info("Replacing existing draft plan %d for %s", plan_id, plan_date)
            # Delete child blocks first, then the plan.
            await client.table("study_blocks").delete().eq("plan_id", plan_id).execute()
            await client.table("study_plans").delete().eq("id", plan_id).execute()


# ---------------------------------------------------------------------------
# Opportunity builders
# ---------------------------------------------------------------------------


def _build_course_lookup(
    enrollments: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Build a course_id -> enrollment dict for quick lookup."""
    result: dict[int, dict[str, Any]] = {}
    for e in enrollments:
        cid = e["course_id"]
        result[cid] = e
    return result


def _compute_mastery_gaps(
    mastery_states: list[dict[str, Any]],
) -> dict[int, tuple[float, float]]:
    """Compute per-course mastery_gap and confidence_gap from mastery_states.

    mastery_gap   = 1 - avg(mastery_level) across all concepts for the course.
    confidence_gap = avg(confidence_self_report) - avg(mastery_level).
                     Positive means overconfident.

    Returns:
        Dict of course_id -> (mastery_gap, confidence_gap).
        Courses with no mastery data are absent from the dict.
    """
    # Accumulate per-course totals.
    course_totals: dict[int, dict[str, float]] = {}

    for ms in mastery_states:
        cid = ms.get("course_id")
        if cid is None:
            continue

        mastery_level = ms.get("mastery_level")
        if mastery_level is None:
            continue

        if cid not in course_totals:
            course_totals[cid] = {
                "mastery_sum": 0.0,
                "confidence_sum": 0.0,
                "count": 0.0,
                "confidence_count": 0.0,
            }

        totals = course_totals[cid]
        totals["mastery_sum"] += float(mastery_level)
        totals["count"] += 1.0

        confidence = ms.get("confidence_self_report")
        if confidence is not None:
            totals["confidence_sum"] += float(confidence)
            totals["confidence_count"] += 1.0

    result: dict[int, tuple[float, float]] = {}
    for cid, totals in course_totals.items():
        if totals["count"] == 0:
            continue

        avg_mastery = totals["mastery_sum"] / totals["count"]
        mastery_gap = max(0.0, min(1.0, 1.0 - avg_mastery))

        if totals["confidence_count"] > 0:
            avg_confidence = totals["confidence_sum"] / totals["confidence_count"]
            confidence_gap = avg_confidence - avg_mastery
        else:
            confidence_gap = 0.0

        result[cid] = (mastery_gap, confidence_gap)

    return result


def _build_opportunities(
    assignments: list[dict[str, Any]],
    submissions_by_assignment: dict[int, dict[str, Any]],
    assessments: list[dict[str, Any]],
    enrollment_lookup: dict[int, dict[str, Any]],
    course_names: dict[int, str],
    grade_snapshots: list[dict[str, Any]],
    now: datetime,
    mastery_gaps: dict[int, tuple[float, float]] | None = None,
) -> list[StudyOpportunity]:
    """Convert raw Supabase rows into StudyOpportunity objects."""
    opportunities: list[StudyOpportunity] = []
    _gaps = mastery_gaps or {}

    # Build a previous-score lookup from grade snapshots.
    # Sort by scraped_at desc so the first per course is "current" and the
    # second is "previous".
    sorted_snapshots = sorted(
        grade_snapshots,
        key=lambda s: s.get("scraped_at", ""),
        reverse=True,
    )
    _prev_scores: dict[int, float | None] = {}
    _seen_courses: dict[int, int] = {}  # course_id -> count
    for snap in sorted_snapshots:
        cid = snap["course_id"]
        count = _seen_courses.get(cid, 0)
        if count == 1:
            # Second snapshot = previous score
            _prev_scores[cid] = snap.get("current_score")
        _seen_courses[cid] = count + 1

    # Homework opportunities from assignments + submissions.
    # Skip assignments that are already graded/scored, from non-academic
    # courses (no grade), or stale overdue items (> 7 days past due).
    for asn in assignments:
        course_id = asn["course_id"]
        enrollment = enrollment_lookup.get(course_id, {})

        # Skip non-academic courses (clubs, etc.) — no grade means not graded.
        if enrollment.get("current_score") is None:
            continue

        course_name = course_names.get(course_id, f"Course {course_id}")
        sub = submissions_by_assignment.get(asn["id"], {})

        # Already graded or scored — nothing to study for.
        if sub.get("score") is not None or sub.get("workflow_state") == "graded":
            continue

        due_at_raw = asn.get("due_at")
        due_at: datetime | None = None
        if due_at_raw:
            try:
                if isinstance(due_at_raw, str):
                    due_at = datetime.fromisoformat(due_at_raw)
                else:
                    due_at = due_at_raw
            except (ValueError, TypeError):
                logger.warning(
                    "Malformed due_at for assignment %s: %r",
                    asn.get("name"),
                    due_at_raw,
                )
                due_at = None
            # Ensure timezone-aware for scoring arithmetic
            if due_at is not None and due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=UTC)

        # Skip stale overdue items — more than 7 days past due is not actionable.
        if due_at is not None:
            days_overdue = (now - due_at).total_seconds() / 86400
            if days_overdue > 7:
                continue

        course_mg, course_cg = _gaps.get(course_id, (0.0, 0.0))
        opportunities.append(
            StudyOpportunity(
                opportunity_type="homework",
                name=asn["name"],
                course_id=course_id,
                course_name=course_name,
                due_at=due_at,
                is_missing=sub.get("missing", False),
                is_late=sub.get("late", False),
                current_score=enrollment.get("current_score"),
                previous_score=_prev_scores.get(course_id),
                points_possible=asn.get("points_possible"),
                mastery_gap=course_mg,
                confidence_gap=course_cg,
            )
        )

    # Assessment opportunities — only from academic courses, skip past assessments.
    for assess in assessments:
        course_id = assess["course_id"]
        enrollment = enrollment_lookup.get(course_id, {})

        # Skip non-academic courses.
        if enrollment.get("current_score") is None:
            continue

        course_name = course_names.get(course_id, f"Course {course_id}")

        scheduled_raw = assess.get("scheduled_date")
        scheduled_at: datetime | None = None
        if scheduled_raw:
            try:
                if isinstance(scheduled_raw, str):
                    scheduled_at = datetime.fromisoformat(scheduled_raw)
                else:
                    scheduled_at = scheduled_raw
            except (ValueError, TypeError):
                logger.warning(
                    "Malformed scheduled_date for assessment %s: %r",
                    assess.get("name"),
                    scheduled_raw,
                )
                scheduled_at = None
            if scheduled_at is not None and scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)

        # Skip past assessments — can't study for a test that already happened.
        if scheduled_at is not None and scheduled_at < now:
            continue

        # Skip assessments whose linked assignment is already graded/scored.
        linked_asn_id = assess.get("canvas_assignment_id")
        if linked_asn_id is not None:
            sub = submissions_by_assignment.get(linked_asn_id, {})
            if sub.get("score") is not None or sub.get("workflow_state") == "graded":
                continue

        assess_mg, assess_cg = _gaps.get(course_id, (0.0, 0.0))
        opportunities.append(
            StudyOpportunity(
                opportunity_type="assessment",
                name=assess["name"],
                course_id=course_id,
                course_name=course_name,
                due_at=scheduled_at,
                current_score=enrollment.get("current_score"),
                previous_score=_prev_scores.get(course_id),
                assessment_type=assess.get("assessment_type"),
                mastery_gap=assess_mg,
                confidence_gap=assess_cg,
            )
        )

    return opportunities


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


async def _write_plan(
    client: AsyncClient,
    user_id: str,
    plan_date: date,
    total_minutes: int,
) -> int:
    """Insert a study_plan row and return its id."""
    now_iso = datetime.now(UTC).isoformat()
    row = {
        "user_id": user_id,
        "plan_date": plan_date.isoformat(),
        "total_minutes": total_minutes,
        "status": "draft",
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    response = await client.table("study_plans").insert(row).execute()
    if not response.data:
        raise PlanGenerationError("Failed to insert study plan — no data returned.")
    return response.data[0]["id"]


async def _write_blocks(
    client: AsyncClient,
    plan_id: int,
    blocks: list[StudyBlock],
    course_id_lookup: dict[str, int],
) -> list[dict[str, Any]]:
    """Insert study_block rows for a plan.

    Returns:
        The inserted rows (with server-assigned ``id`` values).
    """
    if not blocks:
        return []

    rows: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        row: dict[str, Any] = {
            "plan_id": plan_id,
            "block_type": block.block_type,
            "title": block.title,
            "description": block.reason,
            "target_minutes": block.duration_minutes,
            "sort_order": idx,
            "status": "pending",
        }
        # Resolve course_id from course_name if available.
        if block.course_name and block.course_name in course_id_lookup:
            row["course_id"] = course_id_lookup[block.course_name]
        rows.append(row)

    response = await client.table("study_blocks").insert(rows).execute()
    return response.data or []


# ---------------------------------------------------------------------------
# Guide compilation helpers (DEC-003, DEC-005)
# ---------------------------------------------------------------------------


async def _compile_and_persist_guide(
    ai_client: AIClient | None,
    client: AsyncClient,
    block_row: dict[str, Any],
    user_id: str,
) -> None:
    """Compile a single block guide and persist it to study_block_guides.

    Wrapped by asyncio.wait_for in the caller so it respects the per-block
    timeout.  Any exception is caught by the caller's gather(return_exceptions).
    """
    from mitty.guides.compiler import compile_block_guide

    block_id = block_row["id"]
    block_type = block_row.get("block_type")
    if block_type is None:
        logger.debug("Skipping guide for block %d — no block_type", block_id)
        return
    course_id = block_row.get("course_id")

    if course_id is None:
        logger.debug(
            "Skipping guide for block %d — no course_id",
            block_id,
        )
        return

    guide = await compile_block_guide(
        ai_client=ai_client,
        client=client,
        block_type=block_type,
        course_id=course_id,
        user_id=user_id,
        block_id=block_id,
    )

    # Persist to study_block_guides.
    now_iso = datetime.now(UTC).isoformat()
    row: dict[str, Any] = {
        "block_id": guide.block_id,
        "concepts_json": guide.concepts_json,
        "source_bundle_json": guide.source_bundle_json,
        "steps_json": guide.steps_json,
        "warmup_items_json": guide.warmup_items_json,
        "exit_items_json": guide.exit_items_json,
        "completion_criteria_json": guide.completion_criteria_json,
        "success_criteria_json": guide.success_criteria_json,
        "guide_version": guide.guide_version,
        "generated_at": now_iso,
    }
    await (
        client.table("study_block_guides").upsert(row, on_conflict="block_id").execute()
    )


async def _compile_block_guides(
    ai_client: AIClient | None,
    client: AsyncClient,
    block_rows: list[dict[str, Any]],
    user_id: str,
) -> None:
    """Compile guides for all blocks in parallel with per-block timeout.

    Uses ``asyncio.gather(return_exceptions=True)`` so individual failures
    never fail plan generation (DEC-005).
    """
    if not block_rows:
        return

    tasks = [
        asyncio.wait_for(
            _compile_and_persist_guide(ai_client, client, row, user_id),
            timeout=_GUIDE_TIMEOUT_S,
        )
        for row in block_rows
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    succeeded = 0
    for row, result in zip(block_rows, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "Guide compilation failed for block %d: %s",
                row.get("id", "?"),
                result,
            )
        else:
            succeeded += 1

    logger.info(
        "Guide compilation: %d/%d succeeded",
        succeeded,
        len(block_rows),
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def generate_plan(
    client: AsyncClient,
    user_id: str,
    plan_date: date,
    *,
    ai_client: AIClient | None = None,
) -> StudyPlan:
    """Orchestrate full study plan generation.

    Flow:
        1. Read latest student signal (must be within 24h).
        2. Read critical data (assignments, enrollments) — fail if missing.
        3. Read non-critical data (grade_snapshots, mastery_states) — warn only.
        4. Read submissions and assessments.
        5. Check for existing plan on same date (replace draft, error on active).
        6. Build study opportunities from raw data.
        7. Score opportunities via scoring engine.
        8. Allocate blocks via allocator.
        9. Write study_plan row, then study_block rows.
        10. Compile block guides in parallel (non-blocking, DEC-003/DEC-005).

    Args:
        client: Async Supabase client (service-role recommended).
        user_id: The user's UUID string.
        plan_date: The date to generate the plan for.
        ai_client: Optional AIClient for guide compilation.  When ``None``,
            guide compilation is skipped entirely.

    Returns:
        A ``StudyPlan`` with the persisted plan_id and blocks.

    Raises:
        PlanGenerationError: If critical data is missing, signal is stale,
            or a non-replaceable plan already exists.
    """
    t_start = time.monotonic()
    logger.info("Generating plan for user=%s date=%s", user_id, plan_date)

    # 1. Read student signal.
    signal_row = await _read_latest_signal(client, user_id, plan_date)
    logger.debug("Signal: %s", signal_row)

    # 2. Critical reads.
    assignments_data = await _read_critical(client, "assignments", "assignments")
    enrollments_data = await _read_critical(client, "enrollments", "enrollments")

    # 3. Non-critical reads.
    grade_snapshots = await _read_non_critical(
        client, "grade_snapshots", "grade snapshots"
    )
    mastery_states_data = await _read_non_critical(
        client,
        "mastery_states",
        "mastery states",
        filters={"user_id": user_id},
    )

    # 4. Submissions (non-critical — missing subs just means no late/missing flags).
    submissions_data = await _read_non_critical(client, "submissions", "submissions")
    submissions_by_assignment: dict[int, dict[str, Any]] = {
        s["assignment_id"]: s for s in submissions_data
    }

    # Assessments (non-critical — plan still works without them).
    assessments_data = await _read_non_critical(client, "assessments", "assessments")

    # 5. Check for existing plan.
    await _check_existing_plan(client, user_id, plan_date)

    # Build course name lookup from enrollments + a separate courses read.
    course_ids = list({e["course_id"] for e in enrollments_data})
    course_names: dict[int, str] = {}
    try:
        courses_resp = await (
            client.table("courses").select("id,name").in_("id", course_ids).execute()
        )
        course_names = {c["id"]: c["name"] for c in (courses_resp.data or [])}
    except Exception:
        logger.warning("Failed to read course names — using fallback IDs.")

    enrollment_lookup = _build_course_lookup(enrollments_data)

    # 6. Build opportunities.
    now = datetime.now(UTC)
    mastery_gap_lookup = _compute_mastery_gaps(mastery_states_data)
    opportunities = _build_opportunities(
        assignments_data,
        submissions_by_assignment,
        assessments_data,
        enrollment_lookup,
        course_names,
        grade_snapshots,
        now,
        mastery_gaps=mastery_gap_lookup,
    )
    logger.debug("Built %d study opportunities", len(opportunities))

    # 7. Score.
    preferred_ids = (signal_row.get("preferences") or {}).get(
        "preferred_course_ids", []
    )
    signal = StudentSignal(
        preferred_course_ids=preferred_ids,
        confidence_level=signal_row.get("confidence_level", 3),
        energy_level=signal_row.get("energy_level", 3),
        stress_level=signal_row.get("stress_level", 3),
    )
    scored = score_opportunities(opportunities, signal, now)
    logger.debug(
        "Scored %d opportunities: top=%s",
        len(scored),
        scored[0].opportunity.name if scored else "none",
    )

    # 8. Allocate blocks.
    available_minutes = signal_row.get("available_minutes")
    if available_minutes is None:
        raise PlanGenerationError(
            "Student signal is missing 'available_minutes' — cannot allocate blocks."
        )
    blocks = allocate_blocks(scored, available_minutes, signal.energy_level)
    total_minutes = sum(b.duration_minutes for b in blocks)

    # 9. Write plan + blocks (clean up plan on block write failure).
    plan_id = await _write_plan(client, user_id, plan_date, total_minutes)

    # Build course_name -> course_id reverse lookup for block writes.
    course_id_lookup: dict[str, int] = {v: k for k, v in course_names.items()}
    try:
        block_rows = await _write_blocks(client, plan_id, blocks, course_id_lookup)
    except Exception as exc:
        logger.error(
            "Failed to write blocks for plan %d, cleaning up: %s",
            plan_id,
            exc,
        )
        await client.table("study_plans").delete().eq("id", plan_id).execute()
        raise PlanGenerationError(f"Failed to write study blocks: {exc}") from exc

    # 10. Compile block guides in parallel (non-blocking).
    if ai_client is not None and block_rows:
        await _compile_block_guides(ai_client, client, block_rows, user_id)

    elapsed = time.monotonic() - t_start
    logger.info(
        "Plan generated: plan_id=%d, blocks=%d, total_minutes=%d, "
        "opportunities=%d, elapsed=%.2fs",
        plan_id,
        len(blocks),
        total_minutes,
        len(opportunities),
        elapsed,
    )

    return StudyPlan(
        plan_id=plan_id,
        user_id=user_id,
        plan_date=plan_date,
        total_minutes=total_minutes,
        status="draft",
        blocks=blocks,
    )
