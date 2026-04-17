"""Mastery dashboard — aggregated per-concept progress view."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    CalibrationStatus,
    MasteryConceptRow,
    MasteryDashboardResponse,
    SessionHistoryEntry,
    SessionHistoryResponse,
    UpcomingAssessmentResponse,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

router = APIRouter(prefix="/mastery-dashboard", tags=["mastery_dashboard"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
SupaClient = Annotated["AsyncClient", Depends(get_user_client)]

SortField = Literal["mastery_level", "next_review_at", "calibration_gap"]

# Calibration thresholds: gap > 0.2 = over_confident, gap < -0.2 = under_confident
_OVER_THRESHOLD = 0.2
_UNDER_THRESHOLD = -0.2


def _compute_calibration(
    mastery_level: float,
    confidence_self_report: float | None,
) -> tuple[float | None, CalibrationStatus]:
    """Return (calibration_gap, calibration_status)."""
    if confidence_self_report is None:
        return None, "unknown"

    gap = confidence_self_report - mastery_level
    if gap > _OVER_THRESHOLD:
        return gap, "over_confident"
    if gap < _UNDER_THRESHOLD:
        return gap, "under_confident"
    return gap, "well_calibrated"


def _sort_concepts(
    concepts: list[MasteryConceptRow],
    sort_by: SortField,
) -> list[MasteryConceptRow]:
    """Sort concept rows; None values sort last."""
    if sort_by == "mastery_level":
        return sorted(concepts, key=lambda c: c.mastery_level)
    if sort_by == "next_review_at":
        return sorted(
            concepts,
            key=lambda c: (
                c.next_review_at is None,
                c.next_review_at or "",
            ),
        )
    # calibration_gap
    return sorted(
        concepts,
        key=lambda c: (
            c.calibration_gap is None,
            c.calibration_gap if c.calibration_gap is not None else 0.0,
        ),
    )


# ---------------------------------------------------------------------------
# Trend computation helpers
# ---------------------------------------------------------------------------

_TREND_THRESHOLD = 5.0  # percentage-point change to count as improving/declining


def _compute_trend_text(sessions: list[SessionHistoryEntry]) -> str | None:
    """Compute trend text from session accuracies.

    Requires at least 3 sessions. Compares oldest vs newest accuracy
    in the list (which is ordered newest-first from DB).
    """
    if len(sessions) < 3:
        return None

    # Sessions are ordered newest-first; oldest is last
    newest_accuracy = sessions[0].accuracy
    oldest_accuracy = sessions[-1].accuracy
    delta = newest_accuracy - oldest_accuracy

    count = len(sessions)
    if delta > _TREND_THRESHOLD:
        return f"Improving: +{delta:.0f}% over {count} sessions"
    if delta < -_TREND_THRESHOLD:
        return f"Declining: {delta:.0f}% over {count} sessions"
    return f"Steady over {count} sessions"


async def _concepts_from_homework(
    client: AsyncClient,
    user_id: str,
    course_id: int,
) -> list[MasteryConceptRow]:
    """Extract concepts from homework analyses when no mastery data exists.

    Queries homework_analyses for assignments in this course and builds
    placeholder MasteryConceptRow entries (mastery_level=0) so the UI
    has real concepts to work with.
    """
    # Find all assignment IDs for this course
    assign_result = await (
        client.table("assignments").select("id").eq("course_id", course_id).execute()
    )
    assignment_ids = [r["id"] for r in (assign_result.data or [])]
    if not assignment_ids:
        return []

    # Fetch homework analyses for those assignments
    ha_result = await (
        client.table("homework_analyses")
        .select("analysis_json")
        .eq("user_id", user_id)
        .in_("assignment_id", assignment_ids)
        .execute()
    )
    ha_rows = ha_result.data or []

    seen: set[str] = set()
    concepts: list[MasteryConceptRow] = []
    for ha_row in ha_rows:
        aj = ha_row.get("analysis_json") or {}
        for prob in aj.get("per_problem", []):
            concept = prob.get("concept")
            if concept and concept not in seen:
                seen.add(concept)
                concepts.append(
                    MasteryConceptRow(
                        concept=concept,
                        mastery_level=0.0,
                        calibration_status="unknown",
                        has_resources=False,
                        retrieval_count=0,
                    )
                )
    return concepts


@router.get(
    "/upcoming",
    response_model=UpcomingAssessmentResponse | None,
)
async def get_upcoming_assessment(
    current_user: CurrentUser,
    client: SupaClient,
    course_id: int | None = Query(default=None),  # noqa: B008
) -> UpcomingAssessmentResponse | None:
    """Return the nearest future test/quiz assessment with concepts."""
    user_id = current_user["user_id"]
    now_iso = datetime.now(tz=UTC).isoformat()

    # When no course_id provided, restrict to courses the user is enrolled in
    enrolled_course_ids: list[int] | None = None
    if course_id is None:
        enroll_result = await (
            client.table("enrollments")
            .select("course_id")
            .eq("user_id", user_id)
            .eq("enrollment_state", "active")
            .execute()
        )
        enrolled_course_ids = [r["course_id"] for r in (enroll_result.data or [])]
        if not enrolled_course_ids:
            return None

    # Build query: future assessments of type test/quiz, ordered nearest-first
    query = (
        client.table("assessments")
        .select("*")
        .in_("assessment_type", ["test", "quiz"])
        .gt("scheduled_date", now_iso)
        .order("scheduled_date")
        .limit(1)
    )
    if course_id is not None:
        query = query.eq("course_id", course_id)
    elif enrolled_course_ids:
        query = query.in_("course_id", enrolled_course_ids)

    result = await query.execute()
    rows = result.data or []

    if not rows:
        return None

    assessment = rows[0]

    # Extract concepts from homework analyses related to this assessment.
    # Strategy: parse chapter number from assessment name (e.g. "Chapter 8 Quiz"
    # or "CH6 Quiz"), find homework assignments for that chapter (e.g. "(8.1)
    # Homework"), and pull concepts from their analyses.
    concepts: list[str] = []
    assessment_name = assessment.get("name", "")
    a_course_id = assessment["course_id"]

    # Parse chapter number(s) from assessment name
    chapter_matches = re.findall(
        r"(?:ch(?:apter)?|chapters?)\s*(\d+)", assessment_name, re.IGNORECASE
    )
    # Also handle ranges like "Chapter 6-7 Test" or "Chapters 6-7 Test"
    range_matches = re.findall(
        r"(?:ch(?:apters?)?)\s*(\d+)\s*[-–]\s*(\d+)", assessment_name, re.IGNORECASE
    )
    chapters: set[str] = set(chapter_matches)
    for start, end in range_matches:
        for ch in range(int(start), int(end) + 1):
            chapters.add(str(ch))

    if chapters:
        # Find homework assignments matching chapter patterns (e.g. "(8.1)")
        assign_names_result = await (
            client.table("assignments")
            .select("id, name")
            .eq("course_id", a_course_id)
            .execute()
        )
        chapter_hw_ids: list[int] = []
        for row in assign_names_result.data or []:
            name = row.get("name", "")
            for ch in chapters:
                if re.match(rf"\({ch}\.\d", name):
                    chapter_hw_ids.append(row["id"])
                    break

        if chapter_hw_ids:
            ha_result = await (
                client.table("homework_analyses")
                .select("analysis_json")
                .eq("user_id", user_id)
                .in_("assignment_id", chapter_hw_ids)
                .execute()
            )
            seen: set[str] = set()
            for ha_row in ha_result.data or []:
                aj = ha_row.get("analysis_json") or {}
                for prob in aj.get("per_problem", []):
                    concept = prob.get("concept")
                    if concept and concept not in seen:
                        seen.add(concept)
                        concepts.append(concept)

    # Fallback: try canvas_assignment_id direct link — look up the internal
    # assignment ID first since homework_analyses.assignment_id references
    # assignments.id (not the Canvas ID).
    if not concepts:
        canvas_assignment_id = assessment.get("canvas_assignment_id")
        if canvas_assignment_id is not None:
            assign_lookup = await (
                client.table("assignments")
                .select("id")
                .eq("canvas_assignment_id", canvas_assignment_id)
                .limit(1)
                .execute()
            )
            internal_id = assign_lookup.data[0]["id"] if assign_lookup.data else None
            if internal_id is not None:
                ha_result = await (
                    client.table("homework_analyses")
                    .select("analysis_json")
                    .eq("assignment_id", internal_id)
                    .eq("user_id", user_id)
                    .execute()
                )
                seen_fb: set[str] = set()
                for ha_row in ha_result.data or []:
                    aj = ha_row.get("analysis_json") or {}
                    for prob in aj.get("per_problem", []):
                        concept = prob.get("concept")
                        if concept and concept not in seen_fb:
                            seen_fb.add(concept)
                            concepts.append(concept)

    return UpcomingAssessmentResponse(
        assessment_id=assessment["id"],
        name=assessment["name"],
        scheduled_date=assessment["scheduled_date"],
        assessment_type=assessment["assessment_type"],
        course_id=assessment["course_id"],
        concepts=concepts,
    )


@router.get("/session-history", response_model=SessionHistoryResponse)
async def get_session_history(
    current_user: CurrentUser,
    client: SupaClient,
    course_id: int = Query(),  # noqa: B008
) -> SessionHistoryResponse:
    """Return the last 5 completed test prep sessions for a course with trend."""
    result = (
        await client.table("test_prep_sessions")
        .select("*")
        .eq("user_id", current_user["user_id"])
        .eq("course_id", course_id)
        .not_.is_("completed_at", "null")
        .order("started_at", desc=True)
        .limit(5)
        .execute()
    )
    rows = result.data or []

    sessions: list[SessionHistoryEntry] = []
    for row in rows:
        total = row.get("total_problems", 0)
        correct = row.get("total_correct", 0)
        accuracy = (correct / total * 100.0) if total > 0 else 0.0

        sessions.append(
            SessionHistoryEntry(
                session_id=str(row["id"]),
                started_at=row["started_at"],
                total_problems=total,
                total_correct=correct,
                accuracy=round(accuracy, 1),
                duration_seconds=row.get("duration_seconds"),
                phase_reached=row.get("phase_reached"),
                session_type=row.get("session_type", "full"),
            )
        )

    trend_text = _compute_trend_text(sessions)

    return SessionHistoryResponse(sessions=sessions, trend_text=trend_text)


@router.get("/{course_id}", response_model=MasteryDashboardResponse)
async def get_mastery_dashboard(
    course_id: int,
    current_user: CurrentUser,
    client: SupaClient,
    sort_by: SortField = Query(default="mastery_level"),  # noqa: B008
) -> MasteryDashboardResponse:
    """Return aggregated mastery data for a course with calibration indicators."""
    # Fetch mastery states for this user + course
    mastery_result = (
        await client.table("mastery_states")
        .select("*")
        .eq("user_id", current_user["user_id"])
        .eq("course_id", course_id)
        .execute()
    )
    mastery_rows = mastery_result.data or []

    # Fetch resources for this course (used for coverage check)
    resource_result = (
        await client.table("resources")
        .select("id,title")
        .eq("course_id", course_id)
        .execute()
    )
    resource_rows = resource_result.data or []
    resource_titles_lower = {
        r["title"].lower() for r in resource_rows if r.get("title")
    }

    # Build concept rows with calibration and resource coverage
    concepts: list[MasteryConceptRow] = []
    for row in mastery_rows:
        gap, status = _compute_calibration(
            row["mastery_level"],
            row.get("confidence_self_report"),
        )

        # Check if any resource title contains the concept name (word-boundary match)
        concept_lower = row["concept"].lower()
        pattern = re.compile(rf"\b{re.escape(concept_lower)}\b")
        has_resources = any(pattern.search(title) for title in resource_titles_lower)

        concepts.append(
            MasteryConceptRow(
                concept=row["concept"],
                mastery_level=row["mastery_level"],
                confidence_self_report=row.get("confidence_self_report"),
                calibration_gap=gap,
                calibration_status=status,
                next_review_at=row.get("next_review_at"),
                last_retrieval_at=row.get("last_retrieval_at"),
                retrieval_count=row.get("retrieval_count", 0),
                success_rate=row.get("success_rate"),
                has_resources=has_resources,
            )
        )

    sorted_concepts = _sort_concepts(concepts, sort_by)

    # Fallback: if no mastery_states, extract concepts from homework analyses
    if not sorted_concepts:
        fallback_concepts = await _concepts_from_homework(
            client, current_user["user_id"], course_id
        )
        sorted_concepts = _sort_concepts(fallback_concepts, sort_by)

    return MasteryDashboardResponse(
        course_id=course_id,
        concepts=sorted_concepts,
    )
