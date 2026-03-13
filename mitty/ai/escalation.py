"""Heuristic escalation detector for student struggle signals.

Detects three signals:
- **repeated_failure**: 3+ incorrect answers on the same concept recently.
- **avoidance**: 3+ consecutive days with no completed study blocks.
- **confidence_crash**: significant session-over-session confidence drop.

Public API:
    check_escalations(...)  -> list[Escalation]
    check_repeated_failure(...) -> Escalation | None
    check_avoidance(...) -> Escalation | None
    check_confidence_crash(...) -> Escalation | None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — suggested action strings
# ---------------------------------------------------------------------------

_ACTION_REPEATED_FAILURE = (
    "This topic might need a different approach — consider reviewing "
    "the source material or asking your teacher for help."
)
_ACTION_AVOIDANCE = (
    "We noticed you haven't studied in a few days. "
    "Would you like to start with something light?"
)
_ACTION_CONFIDENCE_CRASH = (
    "Your confidence on this topic has dropped. "
    "Let's try some easier practice to rebuild."
)

# Lookback window for repeated failure queries.
_FAILURE_LOOKBACK_DAYS = 7


# ---------------------------------------------------------------------------
# Escalation dataclass
# ---------------------------------------------------------------------------


@dataclass
class Escalation:
    """A detected escalation signal."""

    signal_type: str  # 'repeated_failure', 'avoidance', 'confidence_crash'
    concept: str | None
    context_data: dict[str, Any] = field(default_factory=dict)
    suggested_action: str = ""


# ---------------------------------------------------------------------------
# Signal: repeated failure
# ---------------------------------------------------------------------------


async def check_repeated_failure(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str,
    threshold: int = 3,
) -> Escalation | None:
    """Check if student has ``threshold``+ incorrect answers on the same concept.

    Queries practice_results for this user/course/concept where ``is_correct``
    is false within the last 7 days.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=_FAILURE_LOOKBACK_DAYS)).isoformat()

    response = await (
        client.table("practice_results")
        .select("id")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .eq("concept", concept)
        .eq("is_correct", False)
        .gte("created_at", cutoff)
        .execute()
    )

    results = response.data or []
    failure_count = len(results)

    if failure_count >= threshold:
        logger.info(
            "Repeated failure detected: user=%s concept=%r count=%d",
            user_id,
            concept,
            failure_count,
        )
        return Escalation(
            signal_type="repeated_failure",
            concept=concept,
            context_data={
                "failure_count": failure_count,
                "course_id": course_id,
                "lookback_days": _FAILURE_LOOKBACK_DAYS,
            },
            suggested_action=_ACTION_REPEATED_FAILURE,
        )

    return None


# ---------------------------------------------------------------------------
# Signal: avoidance
# ---------------------------------------------------------------------------


async def check_avoidance(
    client: AsyncClient,
    user_id: str,
    threshold_days: int = 3,
) -> Escalation | None:
    """Check if student has skipped study blocks for ``threshold_days``+ days.

    Looks at study_plans for the user and checks whether any study_blocks
    were completed in the last ``threshold_days`` days.
    """
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=threshold_days)).isoformat()

    # Find plans for this user in the lookback window.
    plans_resp = await (
        client.table("study_plans")
        .select("id, plan_date")
        .eq("user_id", user_id)
        .gte("plan_date", cutoff)
        .execute()
    )
    plans = plans_resp.data or []

    if not plans:
        # No plans at all in the window — treat as avoidance.
        logger.info(
            "Avoidance detected (no plans): user=%s threshold=%d days",
            user_id,
            threshold_days,
        )
        return Escalation(
            signal_type="avoidance",
            concept=None,
            context_data={
                "days_without_activity": threshold_days,
                "reason": "no_plans",
            },
            suggested_action=_ACTION_AVOIDANCE,
        )

    # Check if any blocks in those plans were completed.
    # Filter by the user's plan IDs so we don't see other users' blocks
    # (study_blocks has no user_id column and no RLS).
    plan_ids = [p["id"] for p in plans]
    blocks: list[dict[str, Any]] = []
    for pid in plan_ids:
        blocks_resp = await (
            client.table("study_blocks")
            .select("completed_at")
            .eq("plan_id", pid)
            .eq("status", "completed")
            .gte("completed_at", cutoff)
            .limit(1)
            .execute()
        )
        if blocks_resp.data:
            blocks.extend(blocks_resp.data)
            break  # One completed block is enough to dismiss avoidance

    if not blocks:
        logger.info(
            "Avoidance detected (no completed blocks): user=%s threshold=%d days",
            user_id,
            threshold_days,
        )
        return Escalation(
            signal_type="avoidance",
            concept=None,
            context_data={
                "days_without_activity": threshold_days,
                "reason": "no_completed_blocks",
            },
            suggested_action=_ACTION_AVOIDANCE,
        )

    return None


# ---------------------------------------------------------------------------
# Signal: confidence crash
# ---------------------------------------------------------------------------


async def check_confidence_crash(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str,
    drop_threshold: float = 0.3,
) -> Escalation | None:
    """Check if confidence dropped significantly between recent sessions.

    Compares the average ``confidence_before`` of the 5 most recent
    practice results against the 5 before those. ``mastery_states`` is a
    single-row-per-concept table (upserted), so it cannot provide
    historical snapshots — we use ``practice_results`` instead.
    """
    response = await (
        client.table("practice_results")
        .select("confidence_before, created_at")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .eq("concept", concept)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    records = response.data or []

    # Filter to those with confidence ratings.
    rated = [r for r in records if r.get("confidence_before") is not None]

    if len(rated) < 4:
        return None

    # Split into recent half and older half.
    mid = len(rated) // 2
    recent_avg = sum(r["confidence_before"] for r in rated[:mid]) / mid
    older_avg = sum(r["confidence_before"] for r in rated[mid:]) / (len(rated) - mid)

    # Normalize from [1, 5] to [0, 1] before comparing.
    current_confidence = max(0.0, min(1.0, (recent_avg - 1.0) / 4.0))
    previous_confidence = max(0.0, min(1.0, (older_avg - 1.0) / 4.0))

    drop = previous_confidence - current_confidence

    if drop >= drop_threshold:
        logger.info(
            "Confidence crash detected: user=%s concept=%r drop=%.3f",
            user_id,
            concept,
            drop,
        )
        return Escalation(
            signal_type="confidence_crash",
            concept=concept,
            context_data={
                "drop": drop,
                "current_confidence": current_confidence,
                "previous_confidence": previous_confidence,
                "course_id": course_id,
            },
            suggested_action=_ACTION_CONFIDENCE_CRASH,
        )

    return None


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------


async def _is_duplicate(
    client: AsyncClient,
    user_id: str,
    signal_type: str,
    concept: str | None,
) -> bool:
    """Check if same (user_id, signal_type, concept) exists within 24h."""
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()

    query = (
        client.table("escalation_log")
        .select("id")
        .eq("user_id", user_id)
        .eq("signal_type", signal_type)
        .gte("created_at", cutoff)
    )

    if concept is not None:
        query = query.eq("concept", concept)
    else:
        query = query.is_("concept", None)

    response = await query.execute()
    existing = response.data or []
    return len(existing) > 0


# ---------------------------------------------------------------------------
# Write escalation to log
# ---------------------------------------------------------------------------


async def _write_escalation(
    client: AsyncClient,
    user_id: str,
    escalation: Escalation,
) -> None:
    """Insert an escalation record into the escalation_log table."""
    row = {
        "user_id": user_id,
        "signal_type": escalation.signal_type,
        "concept": escalation.concept,
        "context_data": escalation.context_data,
        "suggested_action": escalation.suggested_action,
        "acknowledged": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await client.table("escalation_log").insert(row).execute()

    logger.info(
        "Wrote escalation to log: user=%s signal=%s concept=%r",
        user_id,
        escalation.signal_type,
        escalation.concept,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def check_escalations(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str | None = None,
) -> list[Escalation]:
    """Run all applicable signals and return triggered escalations.

    Runs repeated_failure and confidence_crash when ``concept`` is provided.
    Always runs avoidance (no concept needed).
    Deduplicates: skips any signal+concept that was already escalated within 24h.
    Writes new escalations to the escalation_log table.
    """
    candidates: list[Escalation] = []

    # Concept-dependent signals.
    if concept is not None:
        repeated = await check_repeated_failure(client, user_id, course_id, concept)
        if repeated is not None:
            candidates.append(repeated)

        crash = await check_confidence_crash(client, user_id, course_id, concept)
        if crash is not None:
            candidates.append(crash)

    # Concept-independent signals.
    avoidance = await check_avoidance(client, user_id)
    if avoidance is not None:
        candidates.append(avoidance)

    # Deduplicate and write.
    new_escalations: list[Escalation] = []
    for esc in candidates:
        if await _is_duplicate(client, user_id, esc.signal_type, esc.concept):
            logger.debug(
                "Skipping duplicate escalation: signal=%s concept=%r",
                esc.signal_type,
                esc.concept,
            )
            continue

        await _write_escalation(client, user_id, esc)
        new_escalations.append(esc)

    return new_escalations
