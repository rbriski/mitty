"""SM-2 variant spaced repetition scheduler.

Pure logic module — no I/O. Calculates the next review date for a concept
based on mastery state (mastery level, success rate, retrieval count).

Public API:
    calculate_next_review(mastery_level, success_rate, retrieval_count,
                          last_retrieval_at) -> datetime

Interval progression (with success_rate >= 0.5 and mastery_level >= 0.3):
    retrieval_count 0  -> review now (new concept)
    retrieval_count 1  -> 1 day
    retrieval_count 2  -> 3 days
    retrieval_count 3  -> 7 days
    retrieval_count 4+ -> exponential growth

Overrides:
    - success_rate < 0.5 (incorrect) -> reset to 1 day
    - mastery_level < 0.3 -> always 1 day (daily review)
    - retrieval_count == 0 -> review immediately (now)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Base intervals for the first few correct retrievals (in days).
_BASE_INTERVALS: dict[int, float] = {
    1: 1.0,
    2: 3.0,
    3: 7.0,
}

# For retrieval_count >= 4, we use exponential growth starting from
# the 3rd interval (7 days) with this multiplier per additional retrieval.
_EXPONENTIAL_BASE: float = 7.0
_EXPONENTIAL_MULTIPLIER: float = 2.0

# Maximum interval cap (in days) to prevent runaway exponential growth.
_MAX_INTERVAL_DAYS: float = 180.0

# Thresholds
_LOW_MASTERY_THRESHOLD: float = 0.3
_INCORRECT_THRESHOLD: float = 0.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_next_review(
    mastery_level: float,
    success_rate: float,
    retrieval_count: int,
    last_retrieval_at: datetime | None,
) -> datetime:
    """Calculate the next review datetime for a concept.

    Uses an SM-2–inspired algorithm with fixed early intervals and
    exponential growth for later retrievals.

    Args:
        mastery_level: Current mastery level (0.0–1.0).
        success_rate: Recent success rate (0.0–1.0). Below 0.5 is treated
            as "incorrect" and resets the interval.
        retrieval_count: Total number of prior retrievals.
        last_retrieval_at: Timestamp of the most recent retrieval, or None
            if the concept has never been reviewed.

    Returns:
        A timezone-aware UTC datetime for the next scheduled review.
    """
    now = datetime.now(UTC)

    # New concept — review immediately.
    if retrieval_count == 0:
        return now

    # Anchor: use last_retrieval_at if available, otherwise now.
    anchor = last_retrieval_at if last_retrieval_at is not None else now

    # Incorrect answer -> reset to 1 day.
    if success_rate < _INCORRECT_THRESHOLD:
        return anchor + timedelta(days=1)

    # Low mastery -> always daily.
    if mastery_level < _LOW_MASTERY_THRESHOLD:
        return anchor + timedelta(days=1)

    # Look up or compute the interval.
    interval_days = _compute_interval(retrieval_count, mastery_level, success_rate)

    return anchor + timedelta(days=interval_days)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_interval(
    retrieval_count: int,
    mastery_level: float,
    success_rate: float,
) -> float:
    """Compute the review interval in days.

    For counts 1–3, uses fixed base intervals.
    For count 4+, uses exponential growth scaled by mastery and success rate.
    """
    if retrieval_count in _BASE_INTERVALS:
        return _BASE_INTERVALS[retrieval_count]

    # Exponential growth for retrieval_count >= 4.
    # exponent starts at 1 for count=4, 2 for count=5, etc.
    exponent = retrieval_count - 3
    raw_interval = _EXPONENTIAL_BASE * (_EXPONENTIAL_MULTIPLIER**exponent)

    # Scale by a quality factor derived from mastery and success rate.
    # Both are 0–1; their product gives a 0–1 quality score.
    # We clamp the minimum to 0.5 so intervals don't shrink below base.
    quality = max(0.5, mastery_level * success_rate)
    return min(raw_interval * quality, _MAX_INTERVAL_DAYS)
