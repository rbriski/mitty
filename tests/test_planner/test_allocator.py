"""Tests for mitty.planner.allocator — study block time allocator.

Parametrized tests verifying that allocate_blocks() produces valid plans
for all time budgets, respecting mandatory block rules (Plan first,
Reflection last, protected retrieval, total <= available_minutes).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mitty.planner.allocator import (
    MIN_BLOCK_MINUTES,
    PLAN_MINUTES,
    REFLECTION_MINUTES,
    StudyBlock,
    allocate_blocks,
)
from mitty.planner.scoring import (
    ScoredOpportunity,
    StudentSignal,
    StudyOpportunity,
    score_opportunities,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 3, 11, 8, 0, 0, tzinfo=UTC)


def _hw(
    *,
    name: str = "Homework",
    course_id: int = 1,
    course_name: str = "Math",
    due_at: datetime | None = None,
    is_missing: bool = False,
    is_late: bool = False,
    current_score: float | None = 90.0,
    previous_score: float | None = None,
    points_possible: float | None = 100.0,
) -> StudyOpportunity:
    return StudyOpportunity(
        opportunity_type="homework",
        name=name,
        course_id=course_id,
        course_name=course_name,
        due_at=due_at,
        is_missing=is_missing,
        is_late=is_late,
        current_score=current_score,
        previous_score=previous_score,
        points_possible=points_possible,
    )


def _assessment(
    *,
    name: str = "Exam",
    course_id: int = 1,
    course_name: str = "Math",
    due_at: datetime | None = None,
    current_score: float | None = 90.0,
    previous_score: float | None = None,
    assessment_type: str = "test",
) -> StudyOpportunity:
    return StudyOpportunity(
        opportunity_type="assessment",
        name=name,
        course_id=course_id,
        course_name=course_name,
        due_at=due_at,
        current_score=current_score,
        previous_score=previous_score,
        assessment_type=assessment_type,
    )


def _signal(
    *,
    preferred_course_ids: list[int] | None = None,
    energy_level: int = 3,
) -> StudentSignal:
    return StudentSignal(
        preferred_course_ids=preferred_course_ids or [],
        energy_level=energy_level,
    )


def _score(
    opps: list[StudyOpportunity], signal: StudentSignal | None = None
) -> list[ScoredOpportunity]:
    """Score a list of opportunities using the real scorer."""
    return score_opportunities(opps, signal or _signal(), NOW)


def _typical_scored() -> list[ScoredOpportunity]:
    """A typical mix of scored opportunities for most tests."""
    return _score(
        [
            _hw(
                name="Math Worksheet",
                course_id=1,
                course_name="Math",
                due_at=NOW + timedelta(days=2),
            ),
            _hw(
                name="English Essay",
                course_id=2,
                course_name="English",
                due_at=NOW + timedelta(days=3),
                current_score=72.0,
            ),
            _hw(
                name="History Reading",
                course_id=3,
                course_name="History",
                due_at=NOW + timedelta(days=5),
            ),
        ]
    )


def _exam_eve_scored() -> list[ScoredOpportunity]:
    """Scored list where an assessment dominates (exam-eve scenario)."""
    return _score(
        [
            _assessment(
                name="Biology Final",
                course_id=4,
                course_name="Biology",
                due_at=NOW + timedelta(hours=20),
            ),
            _hw(
                name="Math Worksheet",
                course_id=1,
                course_name="Math",
                due_at=NOW + timedelta(days=3),
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------


class TestInvariants:
    """Core invariants that must hold for every valid allocation."""

    @pytest.mark.parametrize("minutes", [25, 30, 60, 90, 120, 180])
    def test_plan_always_first(self, minutes: int) -> None:
        blocks = allocate_blocks(_typical_scored(), minutes)
        assert len(blocks) >= 2
        assert blocks[0].block_type == "plan"

    @pytest.mark.parametrize("minutes", [25, 30, 60, 90, 120, 180])
    def test_reflection_always_last(self, minutes: int) -> None:
        blocks = allocate_blocks(_typical_scored(), minutes)
        assert len(blocks) >= 2
        assert blocks[-1].block_type == "reflection"

    @pytest.mark.parametrize("minutes", [5, 10, 15, 25, 30, 60, 90, 120, 180])
    def test_total_never_exceeds_available(self, minutes: int) -> None:
        blocks = allocate_blocks(_typical_scored(), minutes)
        total = sum(b.duration_minutes for b in blocks)
        assert total <= minutes

    @pytest.mark.parametrize("minutes", [25, 30, 60, 90, 120, 180])
    def test_no_block_under_min_duration(self, minutes: int) -> None:
        blocks = allocate_blocks(_typical_scored(), minutes)
        for block in blocks:
            assert block.duration_minutes >= MIN_BLOCK_MINUTES

    def test_empty_scored_still_has_plan_and_reflection(self) -> None:
        blocks = allocate_blocks([], 60)
        assert len(blocks) >= 2
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"

    def test_zero_minutes_returns_empty(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 0)
        assert blocks == []

    def test_below_min_returns_empty(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 3)
        assert blocks == []


# ---------------------------------------------------------------------------
# Very short night (<30 min)
# ---------------------------------------------------------------------------


class TestShortNight:
    """Very short sessions: Plan + Retrieval + Reflection."""

    def test_25_min_session(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 25)
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"
        # Should have exactly 3 blocks: plan, retrieval, reflection
        assert len(blocks) == 3
        types = [b.block_type for b in blocks]
        assert "retrieval" in types
        total = sum(b.duration_minutes for b in blocks)
        assert total <= 25

    def test_15_min_session(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 15)
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"
        total = sum(b.duration_minutes for b in blocks)
        assert total <= 15

    def test_10_min_session(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 10)
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"
        total = sum(b.duration_minutes for b in blocks)
        assert total <= 10

    def test_short_night_plan_5_retrieval_15_reflection_5(self) -> None:
        """Canonical short night: Plan(5) + Retrieval(15) + Reflection(5)."""
        blocks = allocate_blocks(_typical_scored(), 25)
        assert blocks[0].duration_minutes == PLAN_MINUTES
        assert blocks[-1].duration_minutes == REFLECTION_MINUTES
        retrieval = [b for b in blocks if b.block_type == "retrieval"]
        assert len(retrieval) == 1
        assert retrieval[0].duration_minutes == 15


# ---------------------------------------------------------------------------
# Normal sessions (60, 90, 120, 180 min)
# ---------------------------------------------------------------------------


class TestNormalSession:
    """Standard-length sessions with multiple content blocks."""

    @pytest.mark.parametrize("minutes", [60, 90, 120, 180])
    def test_has_retrieval_block(self, minutes: int) -> None:
        """Every normal session must include at least one retrieval block."""
        blocks = allocate_blocks(_typical_scored(), minutes)
        retrieval_blocks = [b for b in blocks if b.block_type == "retrieval"]
        assert len(retrieval_blocks) >= 1

    @pytest.mark.parametrize("minutes", [60, 90, 120, 180])
    def test_retrieval_at_least_15_min(self, minutes: int) -> None:
        """Protected retrieval time must be >= 15 minutes."""
        blocks = allocate_blocks(_typical_scored(), minutes)
        retrieval_blocks = [b for b in blocks if b.block_type == "retrieval"]
        total_retrieval = sum(b.duration_minutes for b in retrieval_blocks)
        assert total_retrieval >= 15

    def test_60_min_produces_multiple_blocks(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 60)
        # Plan + at least one content block + Reflection = at least 3
        assert len(blocks) >= 3

    def test_120_min_produces_more_blocks(self) -> None:
        blocks = allocate_blocks(_typical_scored(), 120)
        assert len(blocks) >= 4


# ---------------------------------------------------------------------------
# Exam-eve
# ---------------------------------------------------------------------------


class TestExamEve:
    """When an assessment dominates, 60%+ of study time goes to it."""

    def test_exam_eve_subject_retrieval_dominates(self) -> None:
        """Plan(5) + subject retrieval (60%+ of study time) + Reflection(5)."""
        blocks = allocate_blocks(_exam_eve_scored(), 90)
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"

        # Find the exam retrieval block
        exam_blocks = [b for b in blocks if "Biology Final" in b.title]
        assert len(exam_blocks) >= 1
        exam_time = sum(b.duration_minutes for b in exam_blocks)

        # Study time = total - plan - reflection
        study_time = 90 - blocks[0].duration_minutes - blocks[-1].duration_minutes
        assert exam_time >= study_time * 0.6

    def test_exam_eve_title_contains_assessment_name(self) -> None:
        blocks = allocate_blocks(_exam_eve_scored(), 60)
        exam_blocks = [b for b in blocks if "Biology Final" in b.title]
        assert len(exam_blocks) >= 1
        assert exam_blocks[0].title == "Study for Biology Final"

    def test_exam_eve_short_session(self) -> None:
        """Even in a 30 min exam-eve session, assessment gets priority."""
        blocks = allocate_blocks(_exam_eve_scored(), 30)
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"
        total = sum(b.duration_minutes for b in blocks)
        assert total <= 30


# ---------------------------------------------------------------------------
# Assessment-driven and grade-risk block titles
# ---------------------------------------------------------------------------


class TestBlockTitles:
    """Block titles should be descriptive and action-oriented."""

    def test_assessment_block_says_study_for(self) -> None:
        scored = _score(
            [
                _assessment(name="Chem Quiz", due_at=NOW + timedelta(days=2)),
            ]
        )
        blocks = allocate_blocks(scored, 60)
        study_blocks = [b for b in blocks if b.block_type not in ("plan", "reflection")]
        titles = [b.title for b in study_blocks]
        assert any("Study for Chem Quiz" in t for t in titles)

    def test_grade_risk_block_says_review(self) -> None:
        scored = _score(
            [
                _hw(
                    name="Algebra HW",
                    course_name="Algebra",
                    current_score=65.0,
                    due_at=NOW + timedelta(days=4),
                ),
            ]
        )
        blocks = allocate_blocks(scored, 90)
        study_blocks = [b for b in blocks if b.block_type not in ("plan", "reflection")]
        titles = [b.title for b in study_blocks]
        # Should have "Review Algebra" for grade-risk course
        assert any("Review" in t and "Algebra" in t for t in titles)

    def test_missing_hw_block_says_complete(self) -> None:
        scored = _score(
            [
                _hw(name="Lost Essay", is_missing=True, due_at=NOW - timedelta(days=1)),
            ]
        )
        blocks = allocate_blocks(scored, 60)
        study_blocks = [b for b in blocks if b.block_type not in ("plan", "reflection")]
        titles = [b.title for b in study_blocks]
        assert any("Complete" in t for t in titles)


# ---------------------------------------------------------------------------
# Energy level affects block duration
# ---------------------------------------------------------------------------


class TestEnergy:
    """Energy level should scale content block durations."""

    def test_low_energy_shorter_blocks(self) -> None:
        blocks_low = allocate_blocks(_typical_scored(), 120, energy=1)
        blocks_normal = allocate_blocks(_typical_scored(), 120, energy=3)

        # Filter to content blocks only
        content_low = [
            b for b in blocks_low if b.block_type not in ("plan", "reflection")
        ]
        content_normal = [
            b for b in blocks_normal if b.block_type not in ("plan", "reflection")
        ]

        assert content_low, "Expected content blocks for low energy"
        assert content_normal, "Expected content blocks for normal energy"
        # Low energy blocks should generally be shorter (or more numerous)
        avg_low = sum(b.duration_minutes for b in content_low) / len(content_low)
        avg_normal = sum(b.duration_minutes for b in content_normal) / len(
            content_normal
        )
        # Low energy should not produce longer average blocks
        assert avg_low <= avg_normal + 1  # small tolerance

    def test_high_energy_longer_blocks(self) -> None:
        blocks_high = allocate_blocks(_typical_scored(), 120, energy=5)
        blocks_normal = allocate_blocks(_typical_scored(), 120, energy=3)

        content_high = [
            b for b in blocks_high if b.block_type not in ("plan", "reflection")
        ]
        content_normal = [
            b for b in blocks_normal if b.block_type not in ("plan", "reflection")
        ]

        assert content_high, "Expected content blocks for high energy"
        assert content_normal, "Expected content blocks for normal energy"
        avg_high = sum(b.duration_minutes for b in content_high) / len(content_high)
        avg_normal = sum(b.duration_minutes for b in content_normal) / len(
            content_normal
        )
        assert avg_high >= avg_normal - 1


# ---------------------------------------------------------------------------
# Parametrized session durations
# ---------------------------------------------------------------------------


class TestParametrizedDurations:
    """Full parametrized sweep across common session lengths."""

    @pytest.mark.parametrize("minutes", [25, 60, 90, 120, 180])
    def test_all_durations_valid(self, minutes: int) -> None:
        """Every session length produces a valid plan."""
        blocks = allocate_blocks(_typical_scored(), minutes)
        assert len(blocks) >= 2
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"
        total = sum(b.duration_minutes for b in blocks)
        assert total <= minutes
        for block in blocks:
            assert block.duration_minutes >= MIN_BLOCK_MINUTES

    @pytest.mark.parametrize("minutes", [25, 60, 90, 120, 180])
    def test_all_durations_exam_eve(self, minutes: int) -> None:
        """Exam-eve plans are valid at every session length."""
        blocks = allocate_blocks(_exam_eve_scored(), minutes)
        assert len(blocks) >= 2
        assert blocks[0].block_type == "plan"
        assert blocks[-1].block_type == "reflection"
        total = sum(b.duration_minutes for b in blocks)
        assert total <= minutes


# ---------------------------------------------------------------------------
# StudyBlock dataclass
# ---------------------------------------------------------------------------


class TestStudyBlock:
    """StudyBlock dataclass has expected fields."""

    def test_fields_present(self) -> None:
        block = StudyBlock(
            block_type="retrieval",
            title="Study for Exam",
            duration_minutes=20,
            course_name="Math",
            reason="test prep",
        )
        assert block.block_type == "retrieval"
        assert block.title == "Study for Exam"
        assert block.duration_minutes == 20
        assert block.course_name == "Math"
        assert block.reason == "test prep"

    def test_optional_course_name(self) -> None:
        block = StudyBlock(
            block_type="plan",
            title="Plan session",
            duration_minutes=5,
        )
        assert block.course_name is None
        assert block.reason == ""

    def test_frozen(self) -> None:
        block = StudyBlock(
            block_type="plan",
            title="Plan",
            duration_minutes=5,
        )
        with pytest.raises(AttributeError):
            block.title = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Pure function — no side effects
# ---------------------------------------------------------------------------


class TestPurity:
    """allocate_blocks must be pure — same inputs, same outputs."""

    def test_deterministic(self) -> None:
        scored = _typical_scored()
        result1 = allocate_blocks(scored, 90, energy=3)
        result2 = allocate_blocks(scored, 90, energy=3)
        assert len(result1) == len(result2)
        for b1, b2 in zip(result1, result2, strict=True):
            assert b1.block_type == b2.block_type
            assert b1.title == b2.title
            assert b1.duration_minutes == b2.duration_minutes

    def test_does_not_mutate_input(self) -> None:
        scored = _typical_scored()
        original_len = len(scored)
        original_scores = [s.score for s in scored]
        allocate_blocks(scored, 90)
        assert len(scored) == original_len
        assert [s.score for s in scored] == original_scores


# ---------------------------------------------------------------------------
# Mastery-aware retrieval concept selection
# ---------------------------------------------------------------------------


class TestMasteryRetrieval:
    """Retrieval block should prefer concepts with highest mastery_gap or
    positive confidence_gap."""

    def test_retrieval_prefers_highest_mastery_gap(self) -> None:
        """When mastery data is present, retrieval block picks the course
        with the highest mastery_gap rather than just the top-scored item."""
        # Top-scored item has no mastery gap; lower-scored has high mastery gap.
        top_scored = StudyOpportunity(
            opportunity_type="homework",
            name="Easy HW",
            course_id=1,
            course_name="Strong",
            due_at=NOW + timedelta(days=2),
            current_score=90.0,
            mastery_gap=0.0,
        )
        lower_scored = StudyOpportunity(
            opportunity_type="homework",
            name="Hard HW",
            course_id=2,
            course_name="Weak",
            due_at=NOW + timedelta(days=4),
            current_score=75.0,
            mastery_gap=0.8,
        )
        scored = _score([top_scored, lower_scored])
        blocks = allocate_blocks(scored, 60)

        retrieval_blocks = [b for b in blocks if b.block_type == "retrieval"]
        assert len(retrieval_blocks) >= 1
        # Retrieval block should target the "Weak" course due to high mastery gap
        assert retrieval_blocks[0].course_name == "Weak"

    def test_retrieval_prefers_positive_confidence_gap(self) -> None:
        """Confidence gap (overconfident) should influence retrieval selection."""
        calibrated = StudyOpportunity(
            opportunity_type="homework",
            name="Calibrated HW",
            course_id=1,
            course_name="Calibrated",
            due_at=NOW + timedelta(days=3),
            current_score=85.0,
            mastery_gap=0.0,
            confidence_gap=0.0,
        )
        overconfident = StudyOpportunity(
            opportunity_type="homework",
            name="Overconfident HW",
            course_id=2,
            course_name="Overconfident",
            due_at=NOW + timedelta(days=3),
            current_score=85.0,
            mastery_gap=0.0,
            confidence_gap=0.5,
        )
        scored = _score([calibrated, overconfident])
        blocks = allocate_blocks(scored, 60)

        retrieval_blocks = [b for b in blocks if b.block_type == "retrieval"]
        assert len(retrieval_blocks) >= 1
        assert retrieval_blocks[0].course_name == "Overconfident"

    def test_retrieval_falls_back_when_no_mastery_data(self) -> None:
        """Without mastery data (all gaps 0), retrieval falls back to top-scored."""
        scored = _typical_scored()
        blocks = allocate_blocks(scored, 60)

        retrieval_blocks = [b for b in blocks if b.block_type == "retrieval"]
        assert len(retrieval_blocks) >= 1
        # Should still produce a valid retrieval block from the top-scored item
        assert retrieval_blocks[0].course_name is not None

    def test_mastery_gap_breaks_tie_over_confidence_gap(self) -> None:
        """When two items have mastery data, higher mastery_gap wins over
        higher confidence_gap."""
        high_mastery = StudyOpportunity(
            opportunity_type="homework",
            name="High Mastery Gap",
            course_id=1,
            course_name="Weak Mastery",
            due_at=NOW + timedelta(days=3),
            current_score=85.0,
            mastery_gap=0.9,
            confidence_gap=0.1,
        )
        high_confidence = StudyOpportunity(
            opportunity_type="homework",
            name="High Confidence Gap",
            course_id=2,
            course_name="Overconfident",
            due_at=NOW + timedelta(days=3),
            current_score=85.0,
            mastery_gap=0.2,
            confidence_gap=0.8,
        )
        scored = _score([high_mastery, high_confidence])
        blocks = allocate_blocks(scored, 60)

        retrieval_blocks = [b for b in blocks if b.block_type == "retrieval"]
        assert len(retrieval_blocks) >= 1
        assert retrieval_blocks[0].course_name == "Weak Mastery"
