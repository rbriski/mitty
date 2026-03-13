"""Tests for mastery_gap and confidence_gap integration in scoring.

Verifies that:
- W_MASTERY_GAP and W_CONFIDENCE_GAP weights exist and are positive
- StudyOpportunity accepts optional mastery_gap and confidence_gap fields
- Scoring factors in mastery_gap and confidence_gap
- Gaps default to 0.0 and scoring is backward compatible
- Higher mastery_gap and positive confidence_gap boost scores
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mitty.planner.scoring import (
    W_CONFIDENCE_GAP,
    W_MASTERY_GAP,
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
    mastery_gap: float = 0.0,
    confidence_gap: float = 0.0,
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
        mastery_gap=mastery_gap,
        confidence_gap=confidence_gap,
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
    mastery_gap: float = 0.0,
    confidence_gap: float = 0.0,
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
        mastery_gap=mastery_gap,
        confidence_gap=confidence_gap,
    )


def _signal(
    *,
    preferred_course_ids: list[int] | None = None,
    confidence_level: int = 3,
    energy_level: int = 3,
    stress_level: int = 3,
) -> StudentSignal:
    return StudentSignal(
        preferred_course_ids=preferred_course_ids or [],
        confidence_level=confidence_level,
        energy_level=energy_level,
        stress_level=stress_level,
    )


# ---------------------------------------------------------------------------
# Test: weight constants exist and are positive
# ---------------------------------------------------------------------------


class TestMasteryWeightConstants:
    def test_mastery_gap_weight_positive(self) -> None:
        assert W_MASTERY_GAP > 0

    def test_confidence_gap_weight_positive(self) -> None:
        assert W_CONFIDENCE_GAP > 0

    def test_mastery_gap_weight_is_float(self) -> None:
        assert isinstance(W_MASTERY_GAP, float)

    def test_confidence_gap_weight_is_float(self) -> None:
        assert isinstance(W_CONFIDENCE_GAP, float)


# ---------------------------------------------------------------------------
# Test: StudyOpportunity accepts mastery_gap and confidence_gap
# ---------------------------------------------------------------------------


class TestStudyOpportunityMasteryFields:
    def test_defaults_to_zero(self) -> None:
        opp = StudyOpportunity(
            opportunity_type="homework",
            name="HW",
            course_id=1,
            course_name="Math",
        )
        assert opp.mastery_gap == 0.0
        assert opp.confidence_gap == 0.0

    def test_custom_values(self) -> None:
        opp = _hw(mastery_gap=0.7, confidence_gap=0.3)
        assert opp.mastery_gap == 0.7
        assert opp.confidence_gap == 0.3


# ---------------------------------------------------------------------------
# Test: backward compatibility — gaps default to 0.0
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_scoring_without_mastery_data(self) -> None:
        """Opportunities without mastery data (gaps=0) still score correctly."""
        opp = _hw(
            name="No mastery HW",
            due_at=NOW + timedelta(days=2),
            mastery_gap=0.0,
            confidence_gap=0.0,
        )
        results = score_opportunities([opp], _signal(), NOW)
        assert len(results) == 1
        assert results[0].score > 0

    def test_zero_gaps_do_not_change_relative_order(self) -> None:
        """With gaps at 0.0, the original scoring factors still determine order."""
        exam_soon = _assessment(
            name="Exam Tomorrow",
            due_at=NOW + timedelta(hours=20),
            course_id=1,
            course_name="Bio",
        )
        hw_later = _hw(
            name="HW Next Week",
            due_at=NOW + timedelta(days=7),
            course_id=2,
            course_name="Math",
        )
        results = score_opportunities([exam_soon, hw_later], _signal(), NOW)
        assert results[0].opportunity.name == "Exam Tomorrow"


# ---------------------------------------------------------------------------
# Test: mastery_gap boosts priority
# ---------------------------------------------------------------------------


class TestMasteryGapScoring:
    def test_high_mastery_gap_ranks_higher(self) -> None:
        """All else being equal, higher mastery_gap should produce a higher score."""
        high_gap = _hw(
            name="High Gap HW",
            course_id=1,
            course_name="Struggling Subject",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            mastery_gap=0.8,
        )
        low_gap = _hw(
            name="Low Gap HW",
            course_id=2,
            course_name="Strong Subject",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            mastery_gap=0.1,
        )
        results = score_opportunities([high_gap, low_gap], _signal(), NOW)
        assert results[0].opportunity.name == "High Gap HW"
        assert results[0].score > results[1].score

    def test_mastery_gap_one_produces_max_factor(self) -> None:
        """mastery_gap of 1.0 should produce the maximum factor contribution."""
        max_gap = _hw(
            name="Max Gap",
            due_at=NOW + timedelta(days=4),
            mastery_gap=1.0,
        )
        no_gap = _hw(
            name="No Gap",
            due_at=NOW + timedelta(days=4),
            mastery_gap=0.0,
        )
        results_max = score_opportunities([max_gap], _signal(), NOW)
        results_none = score_opportunities([no_gap], _signal(), NOW)
        # The score difference should be approximately W_MASTERY_GAP
        diff = results_max[0].score - results_none[0].score
        assert abs(diff - W_MASTERY_GAP) < 0.01


# ---------------------------------------------------------------------------
# Test: confidence_gap boosts priority
# ---------------------------------------------------------------------------


class TestConfidenceGapScoring:
    def test_positive_confidence_gap_ranks_higher(self) -> None:
        """Positive confidence_gap (overconfident) boosts score."""
        overconfident = _hw(
            name="Overconfident HW",
            course_id=1,
            course_name="Course A",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            confidence_gap=0.6,
        )
        calibrated = _hw(
            name="Calibrated HW",
            course_id=2,
            course_name="Course B",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            confidence_gap=0.0,
        )
        results = score_opportunities([overconfident, calibrated], _signal(), NOW)
        assert results[0].opportunity.name == "Overconfident HW"

    def test_negative_confidence_gap_not_penalized_below_zero(self) -> None:
        """Negative confidence_gap (underconfident) should clamp factor to 0."""
        underconfident = _hw(
            name="Underconfident HW",
            due_at=NOW + timedelta(days=4),
            confidence_gap=-0.3,
        )
        results = score_opportunities([underconfident], _signal(), NOW)
        assert len(results) == 1
        assert results[0].score > 0  # still gets non-negative score


# ---------------------------------------------------------------------------
# Test: combined mastery + confidence gap effects
# ---------------------------------------------------------------------------


class TestCombinedGaps:
    def test_both_gaps_produce_highest_boost(self) -> None:
        """An item with both high mastery_gap and positive confidence_gap
        should rank above items with only one gap."""
        both = _hw(
            name="Both Gaps",
            course_id=1,
            course_name="C1",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            mastery_gap=0.7,
            confidence_gap=0.5,
        )
        mastery_only = _hw(
            name="Mastery Only",
            course_id=2,
            course_name="C2",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            mastery_gap=0.7,
            confidence_gap=0.0,
        )
        confidence_only = _hw(
            name="Confidence Only",
            course_id=3,
            course_name="C3",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            mastery_gap=0.0,
            confidence_gap=0.5,
        )
        results = score_opportunities(
            [both, mastery_only, confidence_only], _signal(), NOW
        )
        assert results[0].opportunity.name == "Both Gaps"

    def test_reason_mentions_mastery_gap_when_high(self) -> None:
        """Reason string should mention mastery gap when it's significant."""
        opp = _hw(
            name="Struggling HW",
            due_at=NOW + timedelta(days=3),
            mastery_gap=0.8,
        )
        results = score_opportunities([opp], _signal(), NOW)
        reason = results[0].reason.lower()
        assert "mastery" in reason or "gap" in reason
