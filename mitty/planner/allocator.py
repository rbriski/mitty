"""Study block time allocator.

Pure, deterministic function that takes ranked opportunities and available
minutes, produces ordered study blocks respecting block type rules.

Public API:
    allocate_blocks(scored, available_minutes, energy) -> list[StudyBlock]

Invariants:
    - Plan block is always first.
    - Reflection block is always last.
    - At least 15 min protected for retrieval/study when budget allows.
    - Total duration never exceeds available_minutes.
    - No block shorter than MIN_BLOCK_MINUTES (5 min).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mitty.planner.scoring import ScoredOpportunity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_BLOCK_MINUTES: int = 5
PLAN_MINUTES: int = 5
REFLECTION_MINUTES: int = 5
MIN_RETRIEVAL_MINUTES: int = 15

# Energy multipliers: energy 1–5 maps to a duration scaling factor.
# Low energy → shorter focused blocks; high energy → longer blocks.
_ENERGY_MULTIPLIER: dict[int, float] = {
    1: 0.6,
    2: 0.8,
    3: 1.0,
    4: 1.15,
    5: 1.3,
}

BlockType = Literal[
    "plan",
    "urgent_deliverable",
    "retrieval",
    "worked_example",
    "deep_explanation",
    "reflection",
]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudyBlock:
    """A single time block in a study plan."""

    block_type: BlockType
    title: str
    duration_minutes: int
    course_name: str | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _energy_factor(energy: int) -> float:
    """Return the duration multiplier for a given energy level (1–5)."""
    return _ENERGY_MULTIPLIER.get(energy, 1.0)


def _has_exam_eve(scored: list[ScoredOpportunity]) -> ScoredOpportunity | None:
    """Return the top assessment if it dominates the list (exam-eve scenario).

    An assessment is considered exam-eve when it is the highest-scored item
    and its type is 'assessment'.
    """
    if not scored:
        return None
    top = scored[0]
    if top.opportunity.opportunity_type == "assessment":
        return top
    return None


def _clamp_duration(minutes: int) -> int:
    """Ensure a block is at least MIN_BLOCK_MINUTES or 0 (dropped)."""
    if minutes < MIN_BLOCK_MINUTES:
        return 0
    return minutes


# ---------------------------------------------------------------------------
# Main allocation function
# ---------------------------------------------------------------------------


def allocate_blocks(
    scored: list[ScoredOpportunity],
    available_minutes: int,
    energy: int = 3,
) -> list[StudyBlock]:
    """Allocate study time into ordered blocks.

    Pure function — no I/O, fully deterministic.

    Args:
        scored: Opportunities ranked by score (descending). Output of
            ``score_opportunities()``.
        available_minutes: Total minutes the student has.
        energy: Energy level 1–5 from student check-in.

    Returns:
        Ordered list of ``StudyBlock`` with Plan first, Reflection last,
        total duration <= ``available_minutes``.
    """
    if available_minutes < MIN_BLOCK_MINUTES:
        return []

    blocks: list[StudyBlock] = []
    remaining = available_minutes

    # --- Mandatory bookends: Plan + Reflection ---
    plan_dur = min(PLAN_MINUTES, remaining)
    remaining -= plan_dur

    reflection_dur = min(REFLECTION_MINUTES, remaining)
    remaining -= reflection_dur

    # Very short night (<30 min total): Plan + Retrieval + Reflection
    if available_minutes < 30:
        retrieval_dur = _clamp_duration(remaining)
        remaining -= retrieval_dur

        blocks.append(
            StudyBlock(
                block_type="plan",
                title="Plan session",
                duration_minutes=plan_dur,
                reason="Set goals and review priorities",
            )
        )
        if retrieval_dur > 0:
            # Pick top opportunity for retrieval focus
            title, course = _retrieval_title(scored)
            blocks.append(
                StudyBlock(
                    block_type="retrieval",
                    title=title,
                    duration_minutes=retrieval_dur,
                    course_name=course,
                    reason="Quick retrieval practice",
                )
            )
        blocks.append(
            StudyBlock(
                block_type="reflection",
                title="Reflect",
                duration_minutes=reflection_dur,
                reason="Review what you learned",
            )
        )
        return blocks

    # --- Exam-eve mode ---
    exam_opp = _has_exam_eve(scored)
    if exam_opp is not None:
        return _allocate_exam_eve(
            exam_opp, scored, plan_dur, reflection_dur, remaining, energy
        )

    # --- Normal allocation ---
    return _allocate_normal(scored, plan_dur, reflection_dur, remaining, energy)


# ---------------------------------------------------------------------------
# Exam-eve allocation
# ---------------------------------------------------------------------------


def _allocate_exam_eve(
    exam_opp: ScoredOpportunity,
    scored: list[ScoredOpportunity],
    plan_dur: int,
    reflection_dur: int,
    remaining: int,
    energy: int,
) -> list[StudyBlock]:
    """Exam-eve: Plan + subject retrieval (60%+ of study time) + Reflection."""
    blocks: list[StudyBlock] = []

    blocks.append(
        StudyBlock(
            block_type="plan",
            title="Plan session",
            duration_minutes=plan_dur,
            reason="Set goals and review priorities",
        )
    )

    # At least 60% of remaining time goes to exam retrieval
    exam_time = max(MIN_RETRIEVAL_MINUTES, int(remaining * 0.6))
    exam_time = min(exam_time, remaining)  # can't exceed what's left

    opp = exam_opp.opportunity
    assessment_label = opp.assessment_type or "assessment"
    blocks.append(
        StudyBlock(
            block_type="retrieval",
            title=f"Study for {opp.name}",
            duration_minutes=exam_time,
            course_name=opp.course_name,
            reason=f"{assessment_label} prep — focused retrieval",
        )
    )
    remaining -= exam_time

    # Fill leftover with other opportunities if enough time
    remaining = _fill_study_blocks(
        blocks, scored[1:], remaining, energy, allow_deep=False
    )

    blocks.append(
        StudyBlock(
            block_type="reflection",
            title="Reflect",
            duration_minutes=reflection_dur,
            reason="Review what you learned",
        )
    )
    return blocks


# ---------------------------------------------------------------------------
# Normal allocation
# ---------------------------------------------------------------------------


def _allocate_normal(
    scored: list[ScoredOpportunity],
    plan_dur: int,
    reflection_dur: int,
    remaining: int,
    energy: int,
) -> list[StudyBlock]:
    """Standard allocation: Plan + content blocks + Reflection."""
    blocks: list[StudyBlock] = []

    blocks.append(
        StudyBlock(
            block_type="plan",
            title="Plan session",
            duration_minutes=plan_dur,
            reason="Set goals and review priorities",
        )
    )

    # Protect retrieval time
    retrieval_budget = max(MIN_RETRIEVAL_MINUTES, min(remaining, MIN_RETRIEVAL_MINUTES))
    retrieval_budget = min(retrieval_budget, remaining)

    # Allocate retrieval block from top opportunity
    if retrieval_budget >= MIN_BLOCK_MINUTES and scored:
        title, course = _retrieval_title(scored)
        blocks.append(
            StudyBlock(
                block_type="retrieval",
                title=title,
                duration_minutes=retrieval_budget,
                course_name=course,
                reason="Protected retrieval practice",
            )
        )
        remaining -= retrieval_budget

    # Fill remaining time with study blocks
    remaining = _fill_study_blocks(blocks, scored, remaining, energy, allow_deep=True)

    blocks.append(
        StudyBlock(
            block_type="reflection",
            title="Reflect",
            duration_minutes=reflection_dur,
            reason="Review what you learned",
        )
    )
    return blocks


# ---------------------------------------------------------------------------
# Block-filling logic
# ---------------------------------------------------------------------------

# Base durations for content block types before energy scaling.
_BASE_CONTENT_DURATION: int = 20
_BASE_DEEP_DURATION: int = 25


def _fill_study_blocks(
    blocks: list[StudyBlock],
    scored: list[ScoredOpportunity],
    remaining: int,
    energy: int,
    *,
    allow_deep: bool,
) -> int:
    """Fill remaining time with content blocks from scored opportunities.

    Mutates ``blocks`` in place. Returns leftover minutes.
    """
    if remaining < MIN_BLOCK_MINUTES or not scored:
        return remaining

    factor = _energy_factor(energy)
    used_courses: set[str] = set()

    for item in scored:
        if remaining < MIN_BLOCK_MINUTES:
            break

        opp = item.opportunity
        # Avoid duplicate course blocks in the same session
        key = f"{opp.course_name}:{opp.name}"
        if key in used_courses:
            continue
        used_courses.add(key)

        # Determine block type and duration
        if opp.opportunity_type == "assessment":
            block_type: BlockType = "retrieval"
            title = f"Study for {opp.name}"
            base_dur = _BASE_CONTENT_DURATION
        elif opp.is_missing or opp.is_late:
            block_type = "urgent_deliverable"
            title = f"Complete {opp.name}"
            base_dur = _BASE_CONTENT_DURATION
        elif allow_deep and opp.current_score is not None and opp.current_score < 75:
            block_type = "deep_explanation"
            title = f"Review {opp.course_name}"
            base_dur = _BASE_DEEP_DURATION
        else:
            block_type = "worked_example"
            title = f"Practice {opp.name}"
            base_dur = _BASE_CONTENT_DURATION

        duration = _clamp_duration(int(base_dur * factor))
        if duration == 0:
            continue

        # Don't exceed remaining
        duration = min(duration, remaining)
        if duration < MIN_BLOCK_MINUTES:
            continue

        blocks.append(
            StudyBlock(
                block_type=block_type,
                title=title,
                duration_minutes=duration,
                course_name=opp.course_name,
                reason=item.reason,
            )
        )
        remaining -= duration

    return remaining


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------


def _retrieval_title(
    scored: list[ScoredOpportunity],
) -> tuple[str, str | None]:
    """Build a retrieval block title from the top-scored opportunity."""
    if not scored:
        return "Retrieval practice", None
    top = scored[0].opportunity
    if top.opportunity_type == "assessment":
        return f"Study for {top.name}", top.course_name
    return f"Review {top.course_name}", top.course_name
