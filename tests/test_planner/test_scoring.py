"""Tests for mitty.planner.scoring — priority scoring engine.

Parametrized scenario tests verifying that score_opportunities() produces
deterministic, correctly-ranked results across diverse student situations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mitty.planner.scoring import (
    W_ASSESSMENT_PROXIMITY,
    W_GRADE_RISK,
    W_GRADE_VOLATILITY,
    W_HOMEWORK_URGENCY,
    W_LATE_MISSING,
    W_STUDENT_PREFERENCE,
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
# Test: ScoredOpportunity dataclass
# ---------------------------------------------------------------------------


class TestScoredOpportunity:
    def test_fields_present(self) -> None:
        opp = _hw(name="HW1", due_at=NOW + timedelta(days=2))
        scored = ScoredOpportunity(opportunity=opp, score=0.75, reason="test reason")
        assert scored.opportunity is opp
        assert scored.score == 0.75
        assert scored.reason == "test reason"


# ---------------------------------------------------------------------------
# Test: determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_output(self) -> None:
        opps = [
            _hw(name="HW1", due_at=NOW + timedelta(days=1)),
            _assessment(name="Exam1", due_at=NOW + timedelta(days=2)),
            _hw(name="HW2", due_at=NOW + timedelta(days=5)),
        ]
        signal = _signal()
        result1 = score_opportunities(opps, signal, NOW)
        result2 = score_opportunities(opps, signal, NOW)
        assert [r.score for r in result1] == [r.score for r in result2]
        assert [r.opportunity.name for r in result1] == [
            r.opportunity.name for r in result2
        ]


# ---------------------------------------------------------------------------
# Test: exam tomorrow dominates
# ---------------------------------------------------------------------------


class TestExamTomorrow:
    def test_exam_tomorrow_beats_homework_next_week(self) -> None:
        """An exam tomorrow should score higher than homework due in 7 days."""
        exam = _assessment(
            name="Biology Exam",
            due_at=NOW + timedelta(hours=20),
            course_id=2,
            course_name="Biology",
        )
        hw = _hw(
            name="Math HW",
            due_at=NOW + timedelta(days=7),
            course_id=1,
            course_name="Math",
        )
        results = score_opportunities([exam, hw], _signal(), NOW)
        assert results[0].opportunity.name == "Biology Exam"
        assert results[0].score > results[1].score

    def test_exam_in_2_days_beats_hw_in_5_days(self) -> None:
        exam = _assessment(name="Quiz", due_at=NOW + timedelta(days=2))
        hw = _hw(name="Worksheet", due_at=NOW + timedelta(days=5))
        results = score_opportunities([exam, hw], _signal(), NOW)
        assert results[0].opportunity.name == "Quiz"


# ---------------------------------------------------------------------------
# Test: overdue / missing homework urgency
# ---------------------------------------------------------------------------


class TestLateMissing:
    def test_missing_hw_ranks_high(self) -> None:
        """Missing homework should get high urgency even without a due date."""
        missing = _hw(
            name="Missing HW", is_missing=True, due_at=NOW - timedelta(days=2)
        )
        future_hw = _hw(name="Future HW", due_at=NOW + timedelta(days=3))
        results = score_opportunities([missing, future_hw], _signal(), NOW)
        assert results[0].opportunity.name == "Missing HW"

    def test_late_hw_ranks_above_non_urgent(self) -> None:
        late = _hw(
            name="Late HW",
            is_late=True,
            due_at=NOW - timedelta(days=1),
        )
        chill_hw = _hw(name="Chill HW", due_at=NOW + timedelta(days=10))
        results = score_opportunities([late, chill_hw], _signal(), NOW)
        assert results[0].opportunity.name == "Late HW"


# ---------------------------------------------------------------------------
# Test: grade risk — low grade boosts priority
# ---------------------------------------------------------------------------


class TestGradeRisk:
    def test_low_grade_course_boosted(self) -> None:
        """A homework item in a low-grade course should rank above one in a
        high-grade course, all else being equal."""
        low = _hw(
            name="Low Grade HW",
            course_id=1,
            course_name="Struggling",
            due_at=NOW + timedelta(days=3),
            current_score=62.0,
        )
        high = _hw(
            name="High Grade HW",
            course_id=2,
            course_name="Acing",
            due_at=NOW + timedelta(days=3),
            current_score=97.0,
        )
        results = score_opportunities([low, high], _signal(), NOW)
        assert results[0].opportunity.name == "Low Grade HW"

    def test_none_score_treated_as_neutral(self) -> None:
        """If current_score is None the grade risk factor should be moderate,
        not zero and not maximum."""
        unknown = _hw(
            name="Unknown Grade HW",
            due_at=NOW + timedelta(days=3),
            current_score=None,
        )
        results = score_opportunities([unknown], _signal(), NOW)
        assert len(results) == 1
        assert results[0].score > 0


# ---------------------------------------------------------------------------
# Test: grade volatility
# ---------------------------------------------------------------------------


class TestGradeVolatility:
    def test_dropping_grade_boosts_priority(self) -> None:
        """A course where the grade dropped should rank higher than a stable one."""
        dropping = _hw(
            name="Dropping HW",
            course_id=1,
            course_name="Dropping",
            due_at=NOW + timedelta(days=4),
            current_score=75.0,
            previous_score=85.0,
        )
        stable = _hw(
            name="Stable HW",
            course_id=2,
            course_name="Stable",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
            previous_score=85.0,
        )
        results = score_opportunities([dropping, stable], _signal(), NOW)
        assert results[0].opportunity.name == "Dropping HW"


# ---------------------------------------------------------------------------
# Test: student preference
# ---------------------------------------------------------------------------


class TestStudentPreference:
    def test_preferred_course_gets_boost(self) -> None:
        """If the student signal specifies preferred course IDs, those
        opportunities should get a score boost."""
        preferred = _hw(
            name="Preferred HW",
            course_id=10,
            course_name="Fave",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
        )
        other = _hw(
            name="Other HW",
            course_id=20,
            course_name="Meh",
            due_at=NOW + timedelta(days=4),
            current_score=85.0,
        )
        signal = _signal(preferred_course_ids=[10])
        results = score_opportunities([preferred, other], signal, NOW)
        assert results[0].opportunity.name == "Preferred HW"


# ---------------------------------------------------------------------------
# Test: cold start (empty / minimal data)
# ---------------------------------------------------------------------------


class TestColdStart:
    def test_empty_list(self) -> None:
        results = score_opportunities([], _signal(), NOW)
        assert results == []

    def test_single_item(self) -> None:
        opp = _hw(name="Only HW", due_at=NOW + timedelta(days=2))
        results = score_opportunities([opp], _signal(), NOW)
        assert len(results) == 1
        assert results[0].score > 0

    def test_no_due_dates(self) -> None:
        """Items with no due dates should still be scorable."""
        opp = _hw(name="No Due", due_at=None)
        results = score_opportunities([opp], _signal(), NOW)
        assert len(results) == 1
        assert results[0].score >= 0


# ---------------------------------------------------------------------------
# Test: mixed priorities — realistic scenario
# ---------------------------------------------------------------------------


class TestMixedPriorities:
    def test_realistic_mix(self) -> None:
        """Exam tomorrow > missing homework > hw due in 3 days > hw due in 10 days."""
        exam_tomorrow = _assessment(
            name="Chem Exam",
            due_at=NOW + timedelta(hours=18),
            course_id=1,
            course_name="Chemistry",
            current_score=80.0,
        )
        missing_hw = _hw(
            name="Missing English Essay",
            is_missing=True,
            due_at=NOW - timedelta(days=3),
            course_id=2,
            course_name="English",
            current_score=82.0,
        )
        hw_soon = _hw(
            name="Math Worksheet",
            due_at=NOW + timedelta(days=3),
            course_id=3,
            course_name="Math",
            current_score=88.0,
        )
        hw_later = _hw(
            name="History Reading",
            due_at=NOW + timedelta(days=10),
            course_id=4,
            course_name="History",
            current_score=92.0,
        )
        results = score_opportunities(
            [hw_later, missing_hw, hw_soon, exam_tomorrow],
            _signal(),
            NOW,
        )
        names = [r.opportunity.name for r in results]
        # Exam tomorrow should be first
        assert names[0] == "Chem Exam"
        # Missing homework should be second
        assert names[1] == "Missing English Essay"
        # Near-due HW before far-future HW
        assert names.index("Math Worksheet") < names.index("History Reading")


# ---------------------------------------------------------------------------
# Test: reason strings
# ---------------------------------------------------------------------------


class TestReasonStrings:
    def test_reason_is_human_readable(self) -> None:
        opp = _assessment(
            name="Final Exam",
            due_at=NOW + timedelta(hours=12),
            current_score=72.0,
        )
        results = score_opportunities([opp], _signal(), NOW)
        reason = results[0].reason
        assert isinstance(reason, str)
        assert len(reason) > 10  # non-trivial

    def test_missing_hw_reason_mentions_missing(self) -> None:
        opp = _hw(name="Lost HW", is_missing=True, due_at=NOW - timedelta(days=1))
        results = score_opportunities([opp], _signal(), NOW)
        assert (
            "missing" in results[0].reason.lower()
            or "late" in results[0].reason.lower()
        )


# ---------------------------------------------------------------------------
# Test: weight constants are positive
# ---------------------------------------------------------------------------


class TestWeightConstants:
    def test_all_weights_positive(self) -> None:
        for w in [
            W_HOMEWORK_URGENCY,
            W_ASSESSMENT_PROXIMITY,
            W_LATE_MISSING,
            W_GRADE_RISK,
            W_GRADE_VOLATILITY,
            W_STUDENT_PREFERENCE,
        ]:
            assert w > 0

    def test_assessment_proximity_is_highest(self) -> None:
        """Assessment proximity should be the dominant weight, per the spec
        that tests in <= 3 days dominate."""
        assert W_ASSESSMENT_PROXIMITY >= W_HOMEWORK_URGENCY
        assert W_ASSESSMENT_PROXIMITY >= W_LATE_MISSING
        assert W_ASSESSMENT_PROXIMITY >= W_GRADE_RISK


# ---------------------------------------------------------------------------
# Test: returned list is sorted descending by score
# ---------------------------------------------------------------------------


class TestSorting:
    def test_results_sorted_descending(self) -> None:
        opps = [
            _hw(name="A", due_at=NOW + timedelta(days=10), current_score=95.0),
            _hw(name="B", due_at=NOW + timedelta(days=1), current_score=60.0),
            _assessment(name="C", due_at=NOW + timedelta(days=2), current_score=70.0),
        ]
        results = score_opportunities(opps, _signal(), NOW)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
