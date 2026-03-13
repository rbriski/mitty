"""Mastery dashboard — aggregated per-concept progress view."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    CalibrationStatus,
    MasteryConceptRow,
    MasteryDashboardResponse,
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

    return MasteryDashboardResponse(
        course_id=course_id,
        concepts=sorted_concepts,
    )
