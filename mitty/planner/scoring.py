"""Priority scoring engine for study opportunities.

Pure, deterministic scoring function that ranks study opportunities (homework,
assessments) using 8 weighted factors. No I/O — only computation.

Public API:
    score_opportunities(opportunities, signal, now) -> list[ScoredOpportunity]

Weight constants (module-level, tunable):
    W_HOMEWORK_URGENCY     — days until due; high for items due in 1–3 days
    W_ASSESSMENT_PROXIMITY — exams/tests within 3 days dominate the score
    W_LATE_MISSING         — overdue/missing homework recovery boost
    W_GRADE_RISK           — courses with lower grades get priority
    W_GRADE_VOLATILITY     — courses where grade is changing (up or down)
    W_STUDENT_PREFERENCE   — student signal (from check-in) boost
    W_MASTERY_GAP          — concepts with low mastery get retrieval priority
    W_CONFIDENCE_GAP       — overconfident concepts (high self-report, low mastery)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime


# ---------------------------------------------------------------------------
# Weight constants — each factor's contribution to the final score.
# All positive; assessment proximity is intentionally highest so that
# "tests in <= 3 days dominate."
# ---------------------------------------------------------------------------

W_HOMEWORK_URGENCY: float = 0.16
W_ASSESSMENT_PROXIMITY: float = 0.30
W_LATE_MISSING: float = 0.16
W_GRADE_RISK: float = 0.12
W_GRADE_VOLATILITY: float = 0.07
W_STUDENT_PREFERENCE: float = 0.06
W_MASTERY_GAP: float = 0.08
W_CONFIDENCE_GAP: float = 0.05

# ---------------------------------------------------------------------------
# Data models (pure, no I/O)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudyOpportunity:
    """A single item a student could study or complete."""

    opportunity_type: Literal["homework", "assessment"]
    name: str
    course_id: int
    course_name: str
    due_at: datetime | None = None
    is_missing: bool = False
    is_late: bool = False
    current_score: float | None = None  # course grade 0–100
    previous_score: float | None = None  # prior snapshot for volatility
    points_possible: float | None = None
    assessment_type: str | None = None  # test, quiz, essay, etc.
    mastery_gap: float = 0.0  # 0–1; higher = weaker mastery on related concepts
    confidence_gap: float = 0.0  # positive = overconfident (self-report > mastery)


@dataclass(frozen=True, slots=True)
class StudentSignal:
    """Lightweight student check-in data relevant to scoring."""

    preferred_course_ids: list[int]
    confidence_level: int = 3  # 1–5
    energy_level: int = 3  # 1–5
    stress_level: int = 3  # 1–5


@dataclass(frozen=True, slots=True)
class ScoredOpportunity:
    """An opportunity annotated with a numeric score and human-readable reason."""

    opportunity: StudyOpportunity
    score: float
    reason: str


# ---------------------------------------------------------------------------
# Factor functions — each returns a float in [0.0, 1.0].
# ---------------------------------------------------------------------------

# Number of days within which deadlines are considered urgent.
_URGENCY_HORIZON_DAYS: int = 7
# Assessment proximity ramps to max within this window.
_ASSESSMENT_CRITICAL_DAYS: int = 3


def _factor_homework_urgency(opp: StudyOpportunity, now: datetime) -> float:
    """Score 0–1 based on how soon homework is due.

    Items due within 1 day → 1.0, within 7 days → linear ramp, further → 0.
    Overdue items get 0.8 (the late/missing factor handles the main boost).
    Only applies to homework.
    """
    if opp.opportunity_type != "homework":
        return 0.0
    if opp.due_at is None:
        return 0.1  # small nudge for undated homework
    delta = opp.due_at - now
    days = delta.total_seconds() / 86400
    if days < 0:
        return 0.8  # overdue — partial urgency
    if days <= 1:
        return 1.0
    if days <= _URGENCY_HORIZON_DAYS:
        return 1.0 - (days - 1) / (_URGENCY_HORIZON_DAYS - 1)
    return 0.0


def _factor_assessment_proximity(opp: StudyOpportunity, now: datetime) -> float:
    """Score 0–1 based on how close an assessment is.

    Assessments within 1 day → 1.0, within 3 days → steep ramp, beyond → taper.
    Non-assessment items return 0.
    """
    if opp.opportunity_type != "assessment":
        return 0.0
    if opp.due_at is None:
        return 0.2  # undated assessment still deserves some attention
    delta = opp.due_at - now
    days = delta.total_seconds() / 86400
    if days < 0:
        return 0.5  # past assessment — moderate (review value)
    if days <= 1:
        return 1.0
    if days <= _ASSESSMENT_CRITICAL_DAYS:
        # Steep ramp: 1.0 at 1 day → 0.7 at 3 days
        return 1.0 - 0.3 * (days - 1) / (_ASSESSMENT_CRITICAL_DAYS - 1)
    if days <= _URGENCY_HORIZON_DAYS:
        # Gentler taper beyond 3 days
        return 0.7 - 0.5 * (days - _ASSESSMENT_CRITICAL_DAYS) / (
            _URGENCY_HORIZON_DAYS - _ASSESSMENT_CRITICAL_DAYS
        )
    return 0.1  # far future — minimal


def _factor_late_missing(opp: StudyOpportunity) -> float:
    """Score 0–1 for overdue or missing homework.

    Missing → 1.0, late → 0.8, otherwise 0.
    """
    if opp.is_missing:
        return 1.0
    if opp.is_late:
        return 0.8
    return 0.0


def _factor_grade_risk(opp: StudyOpportunity) -> float:
    """Score 0–1 inversely proportional to the course grade.

    A 60% course grade → ~0.7 risk, a 95% → ~0.15.
    None → 0.4 (neutral).
    """
    if opp.current_score is None:
        return 0.4  # neutral when unknown
    # Clamp to [0, 100] and invert so lower grades → higher risk.
    clamped = max(0.0, min(100.0, opp.current_score))
    # Map: 100 → 0.2, 50 → 1.0 (linear with floor/ceiling)
    return max(0.1, min(1.0, 1.0 - (clamped - 50.0) / 62.5))


def _factor_grade_volatility(opp: StudyOpportunity) -> float:
    """Score 0–1 based on grade change between snapshots.

    A drop of 10+ points → 1.0, no change → 0, rising → small positive.
    None/None → 0 (no data).
    """
    if opp.current_score is None or opp.previous_score is None:
        return 0.0
    delta = opp.previous_score - opp.current_score  # positive = grade dropped
    if delta > 0:
        # Dropping — scale: 10-point drop → 1.0
        return min(1.0, delta / 10.0)
    if delta < 0:
        # Rising — small positive signal (still some attention warranted)
        return min(0.3, abs(delta) / 20.0)
    return 0.0


def _factor_student_preference(
    opp: StudyOpportunity,
    signal: StudentSignal,
) -> float:
    """Score 0 or 1 if the student marked this course as preferred."""
    if opp.course_id in signal.preferred_course_ids:
        return 1.0
    return 0.0


def _factor_mastery_gap(opp: StudyOpportunity) -> float:
    """Score 0–1 based on the mastery gap for this opportunity's course.

    mastery_gap is pre-computed as 1 - avg_mastery_level for the course,
    clamped to [0, 1]. Higher gap = weaker mastery = more study needed.
    """
    return max(0.0, min(1.0, opp.mastery_gap))


def _factor_confidence_gap(opp: StudyOpportunity) -> float:
    """Score 0–1 based on the confidence gap for this opportunity's course.

    confidence_gap = avg_self_report - avg_mastery_level. Positive means the
    student is overconfident (thinks they know more than they do), which is
    a priority for retrieval practice. Negative gaps clamp to 0.
    """
    return max(0.0, min(1.0, opp.confidence_gap))


# ---------------------------------------------------------------------------
# Reason builder
# ---------------------------------------------------------------------------


def _build_reason(
    opp: StudyOpportunity,
    factors: dict[str, float],
    now: datetime,
) -> str:
    """Build a human-readable string explaining why this item ranked as it did."""
    parts: list[str] = []

    if opp.due_at is not None:
        delta = opp.due_at - now
        hours = delta.total_seconds() / 3600
        if hours < 0:
            parts.append(f"overdue by {abs(hours):.0f}h")
        elif hours < 24:
            parts.append(f"due in {hours:.0f}h")
        else:
            parts.append(f"due in {delta.days}d")

    if opp.is_missing:
        parts.append("missing assignment")
    elif opp.is_late:
        parts.append("late submission")

    if opp.opportunity_type == "assessment":
        label = opp.assessment_type or "assessment"
        parts.append(f"{label} prep")

    if opp.current_score is not None and opp.current_score < 75:
        parts.append(f"grade at risk ({opp.current_score:.0f}%)")

    if (
        opp.current_score is not None
        and opp.previous_score is not None
        and opp.previous_score > opp.current_score
    ):
        drop = opp.previous_score - opp.current_score
        parts.append(f"grade dropped {drop:.0f}pts")

    if factors.get("mastery_gap", 0) >= 0.5:
        parts.append("mastery gap — concepts need review")

    if factors.get("confidence_gap", 0) >= 0.3:
        parts.append("confidence gap — may be overconfident")

    if factors.get("student_preference", 0) > 0:
        parts.append("preferred course")

    course_tag = f"[{opp.course_name}]"
    detail = "; ".join(parts) if parts else "general study"
    return f"{course_tag} {detail}"


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_opportunities(
    opportunities: list[StudyOpportunity],
    signal: StudentSignal,
    now: datetime,
) -> list[ScoredOpportunity]:
    """Score and rank study opportunities.

    Pure function — no I/O, fully deterministic.

    Args:
        opportunities: Items available for study.
        signal: Student check-in data (preferences, energy, etc.).
        now: The current timestamp (injected for determinism).

    Returns:
        A list of ``ScoredOpportunity`` sorted descending by score.
    """
    if not opportunities:
        return []

    scored: list[ScoredOpportunity] = []

    for opp in opportunities:
        factors = {
            "homework_urgency": _factor_homework_urgency(opp, now),
            "assessment_proximity": _factor_assessment_proximity(opp, now),
            "late_missing": _factor_late_missing(opp),
            "grade_risk": _factor_grade_risk(opp),
            "grade_volatility": _factor_grade_volatility(opp),
            "student_preference": _factor_student_preference(opp, signal),
            "mastery_gap": _factor_mastery_gap(opp),
            "confidence_gap": _factor_confidence_gap(opp),
        }

        total = (
            W_HOMEWORK_URGENCY * factors["homework_urgency"]
            + W_ASSESSMENT_PROXIMITY * factors["assessment_proximity"]
            + W_LATE_MISSING * factors["late_missing"]
            + W_GRADE_RISK * factors["grade_risk"]
            + W_GRADE_VOLATILITY * factors["grade_volatility"]
            + W_STUDENT_PREFERENCE * factors["student_preference"]
            + W_MASTERY_GAP * factors["mastery_gap"]
            + W_CONFIDENCE_GAP * factors["confidence_gap"]
        )

        reason = _build_reason(opp, factors, now)
        scored.append(ScoredOpportunity(opportunity=opp, score=total, reason=reason))

    # Sort descending by score, then by name for stability.
    scored.sort(key=lambda s: (-s.score, s.opportunity.name))
    return scored
