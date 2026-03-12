"""Mastery state updater — updates mastery tracking after practice results.

Computes and upserts mastery_level (weighted moving average),
success_rate (rolling window over last 20 attempts),
confidence_self_report (normalized average of confidence_before ratings),
retrieval_count, last_retrieval_at, and next_review_at.

Public API:
    update_mastery(client, user_id, course_id, concept, results) -> MasteryState
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID  # noqa: TC003 — needed at runtime by Pydantic

from pydantic import BaseModel, ConfigDict

from mitty.mastery.scheduler import calculate_next_review

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rolling window size for success_rate calculation.
_ROLLING_WINDOW = 20

# Blend factor: how much weight to give new results vs. existing mastery.
# Higher = more reactive to new results.
_NEW_RESULTS_WEIGHT = 0.7

# confidence_before is rated 1–5 in the schema. Normalize to 0–1.
_CONFIDENCE_MIN = 1.0
_CONFIDENCE_MAX = 5.0


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class MasteryState(BaseModel):
    """Computed mastery state returned by update_mastery."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    course_id: int
    concept: str
    mastery_level: float
    success_rate: float | None
    confidence_self_report: float | None
    retrieval_count: int
    last_retrieval_at: datetime | None
    next_review_at: datetime | None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def update_mastery(
    client: AsyncClient,
    user_id: UUID,
    course_id: int,
    concept: str,
    results: list[dict[str, Any]],
) -> MasteryState:
    """Update mastery state after a batch of practice results.

    Reads the current mastery_state row (if any), computes updated metrics,
    and upserts the row atomically using on_conflict="user_id,course_id,concept".

    Args:
        client: Async Supabase client.
        user_id: The student's user ID.
        course_id: The course ID.
        concept: The concept string.
        results: List of practice result dicts, each with at least
            ``score``, ``is_correct``, and optionally ``confidence_before``.

    Returns:
        The computed MasteryState.
    """
    # 1. Fetch existing mastery state (if any).
    existing = await _fetch_existing(client, user_id, course_id, concept)

    # 2. Extract scores from results.
    scores = [_result_score(r) for r in results]

    # 3. Compute updated fields.
    existing_mastery = existing.get("mastery_level", 0.0) if existing else 0.0
    existing_rate = existing.get("success_rate") if existing else None
    existing_count = existing.get("retrieval_count", 0) if existing else 0
    existing_confidence = existing.get("confidence_self_report") if existing else None

    mastery_level = _compute_mastery_level(scores, existing_mastery)
    success_rate = _compute_success_rate(scores, existing_rate)
    confidence = _compute_confidence_self_report(results)

    # Blend confidence with existing if available.
    if confidence is not None and existing_confidence is not None:
        confidence = (confidence + existing_confidence) / 2.0
    elif confidence is None:
        confidence = existing_confidence

    retrieval_count = existing_count + len(results)
    now = datetime.now(UTC)

    next_review = calculate_next_review(
        mastery_level=mastery_level,
        success_rate=success_rate if success_rate is not None else 0.0,
        retrieval_count=retrieval_count,
        last_retrieval_at=now,
    )

    # 4. Build the row for upsert.
    row = {
        "user_id": str(user_id),
        "course_id": course_id,
        "concept": concept,
        "mastery_level": round(mastery_level, 6),
        "success_rate": round(success_rate, 6) if success_rate is not None else None,
        "confidence_self_report": (
            round(confidence, 6) if confidence is not None else None
        ),
        "retrieval_count": retrieval_count,
        "last_retrieval_at": now.isoformat(),
        "next_review_at": next_review.isoformat(),
        "updated_at": now.isoformat(),
    }

    # 5. Upsert atomically.
    await (
        client.table("mastery_states")
        .upsert(row, on_conflict="user_id,course_id,concept")
        .execute()
    )

    logger.info(
        "Updated mastery for user=%s course=%s concept=%r: "
        "level=%.3f rate=%.3f count=%d",
        user_id,
        course_id,
        concept,
        mastery_level,
        success_rate if success_rate is not None else 0.0,
        retrieval_count,
    )

    return MasteryState(
        user_id=user_id,
        course_id=course_id,
        concept=concept,
        mastery_level=mastery_level,
        success_rate=success_rate,
        confidence_self_report=confidence,
        retrieval_count=retrieval_count,
        last_retrieval_at=now,
        next_review_at=next_review,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _result_score(result: dict[str, Any]) -> float:
    """Extract a 0–1 score from a practice result dict.

    Uses ``score`` if present; otherwise falls back to ``is_correct``
    (True -> 1.0, False -> 0.0). Both null -> 0.0.
    """
    score = result.get("score")
    if score is not None:
        return float(score)

    is_correct = result.get("is_correct")
    if is_correct is True:
        return 1.0
    return 0.0


def _compute_mastery_level(
    scores: list[float],
    existing_mastery: float,
) -> float:
    """Compute mastery level as a weighted moving average.

    Recent scores are weighted more heavily using exponential weighting.
    The result is then blended with the existing mastery level.

    Args:
        scores: List of 0–1 scores from the current batch (oldest first).
        existing_mastery: The current mastery level before this batch.

    Returns:
        Updated mastery level clamped to [0.0, 1.0].
    """
    if not scores:
        return existing_mastery

    # Exponential weights: more recent scores get higher weight.
    # Weight grows as 2^i where i is the position (0-indexed, oldest first).
    weights = [2.0**i for i in range(len(scores))]
    total_weight = sum(weights)
    weighted_avg = (
        sum(s * w for s, w in zip(scores, weights, strict=True)) / total_weight
    )

    # Blend weighted average of new results with existing mastery.
    blended = (
        _NEW_RESULTS_WEIGHT * weighted_avg
        + (1 - _NEW_RESULTS_WEIGHT) * existing_mastery
    )

    return max(0.0, min(1.0, blended))


def _compute_success_rate(
    scores: list[float],
    existing_rate: float | None,
) -> float:
    """Compute rolling success rate over the last N attempts.

    Takes the last ``_ROLLING_WINDOW`` scores and computes the mean.
    If there are more scores than the window, only the most recent are used.

    Args:
        scores: All scores from this batch (oldest first).
        existing_rate: Previous success rate (unused when enough scores exist;
            could be used for blending with small batches in the future).

    Returns:
        Success rate as a float 0.0–1.0.
    """
    if not scores:
        return existing_rate if existing_rate is not None else 0.0

    # Use only the most recent _ROLLING_WINDOW scores.
    window = scores[-_ROLLING_WINDOW:]
    return sum(window) / len(window)


def _compute_confidence_self_report(
    results: list[dict[str, Any]],
) -> float | None:
    """Compute average confidence_before, normalized to 0–1.

    confidence_before is rated 1–5 in the schema. We normalize to [0, 1]
    using: (avg - 1) / (5 - 1).

    Returns None if no results have a confidence_before rating.
    """
    ratings = [
        r["confidence_before"]
        for r in results
        if r.get("confidence_before") is not None
    ]
    if not ratings:
        return None

    avg = sum(ratings) / len(ratings)
    # Normalize from [1, 5] to [0, 1].
    normalized = (avg - _CONFIDENCE_MIN) / (_CONFIDENCE_MAX - _CONFIDENCE_MIN)
    return max(0.0, min(1.0, normalized))


async def _fetch_existing(
    client: AsyncClient,
    user_id: UUID,
    course_id: int,
    concept: str,
) -> dict[str, Any] | None:
    """Fetch the existing mastery_state row, if any.

    Returns the row dict or None if no row exists.
    """
    response = await (
        client.table("mastery_states")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("course_id", course_id)
        .eq("concept", concept)
        .maybe_single()
        .execute()
    )
    return response.data
