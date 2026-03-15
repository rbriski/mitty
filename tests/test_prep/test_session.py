"""Tests for mitty.prep.session — 5-phase adaptive session engine.

Covers: phase transitions (valid + invalid), difficulty adaptation
(increase, decrease, clamped), state serialization, session resume.

Traces: DEC-004 (5 phases), DEC-006 (UUID PKs).
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from mitty.prep.session import (
    DIFFICULTY_STEP,
    FULL_PHASE_DURATIONS,
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    PHASE_ORDER,
    QUICK_PHASE_DURATIONS,
    QUICK_PHASE_ORDER,
    SessionEngine,
    SessionPhase,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_ID = uuid4()
_SESSION_ID = uuid4()
_COURSE_ID = 101
_CONCEPTS = ["polynomial long division", "synthetic division"]


def _make_engine(
    *,
    phase: SessionPhase | None = None,
    difficulty: float = 0.5,
    concepts: list[str] | None = None,
    session_type: str = "full",
) -> SessionEngine:
    """Build a SessionEngine with a pre-set state for testing."""
    return SessionEngine(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        course_id=_COURSE_ID,
        concepts=concepts or list(_CONCEPTS),
        initial_difficulty=difficulty,
        initial_phase=phase,
        session_type=session_type,
    )


# ---------------------------------------------------------------------------
# Phase transitions — valid (parametrized)
# ---------------------------------------------------------------------------


class TestPhaseTransitionsValid:
    """DEC-004: Valid transitions follow the 5-phase order."""

    @pytest.mark.parametrize(
        ("from_phase", "to_phase"),
        [
            (SessionPhase.diagnostic, SessionPhase.focused_practice),
            (SessionPhase.focused_practice, SessionPhase.error_analysis),
            (SessionPhase.error_analysis, SessionPhase.mixed_test),
            (SessionPhase.mixed_test, SessionPhase.calibration),
        ],
    )
    def test_valid_transitions(
        self, from_phase: SessionPhase, to_phase: SessionPhase
    ) -> None:
        engine = _make_engine(phase=from_phase)
        engine.advance_phase()
        assert engine.current_phase == to_phase


# ---------------------------------------------------------------------------
# Phase transitions — invalid
# ---------------------------------------------------------------------------


class TestPhaseTransitionsInvalid:
    """Cannot advance past calibration or skip phases."""

    def test_cannot_advance_past_calibration(self) -> None:
        engine = _make_engine(phase=SessionPhase.calibration)
        with pytest.raises(ValueError, match="[Cc]annot advance"):
            engine.advance_phase()

    def test_phase_order_is_complete(self) -> None:
        """All 5 phases appear in PHASE_ORDER exactly once."""
        assert len(PHASE_ORDER) == 5
        assert set(PHASE_ORDER) == set(SessionPhase)


# ---------------------------------------------------------------------------
# Difficulty adaptation
# ---------------------------------------------------------------------------


class TestDifficultyIncrease:
    """Difficulty increases by DIFFICULTY_STEP after 2 consecutive correct."""

    def test_increases_after_two_correct(self) -> None:
        engine = _make_engine(difficulty=0.5)
        engine.record_answer(correct=True)
        assert engine.state.difficulty == pytest.approx(0.5)
        engine.record_answer(correct=True)
        assert engine.state.difficulty == pytest.approx(0.5 + DIFFICULTY_STEP)


class TestDifficultyDecrease:
    """Difficulty decreases by DIFFICULTY_STEP after 2 consecutive wrong."""

    def test_decreases_after_two_wrong(self) -> None:
        engine = _make_engine(difficulty=0.5)
        engine.record_answer(correct=False)
        assert engine.state.difficulty == pytest.approx(0.5)
        engine.record_answer(correct=False)
        assert engine.state.difficulty == pytest.approx(0.5 - DIFFICULTY_STEP)


class TestDifficultyClamped:
    """Difficulty stays within [MIN_DIFFICULTY, MAX_DIFFICULTY]."""

    def test_clamped_at_max(self) -> None:
        engine = _make_engine(difficulty=MAX_DIFFICULTY)
        engine.record_answer(correct=True)
        engine.record_answer(correct=True)
        assert engine.state.difficulty == pytest.approx(MAX_DIFFICULTY)

    def test_clamped_at_min(self) -> None:
        engine = _make_engine(difficulty=MIN_DIFFICULTY)
        engine.record_answer(correct=False)
        engine.record_answer(correct=False)
        assert engine.state.difficulty == pytest.approx(MIN_DIFFICULTY)

    def test_difficulty_within_bounds_after_many_correct(self) -> None:
        engine = _make_engine(difficulty=0.85)
        for _ in range(20):
            engine.record_answer(correct=True)
        assert MIN_DIFFICULTY <= engine.state.difficulty <= MAX_DIFFICULTY

    def test_difficulty_within_bounds_after_many_wrong(self) -> None:
        engine = _make_engine(difficulty=0.2)
        for _ in range(20):
            engine.record_answer(correct=False)
        assert MIN_DIFFICULTY <= engine.state.difficulty <= MAX_DIFFICULTY


# ---------------------------------------------------------------------------
# Running mastery tracking
# ---------------------------------------------------------------------------


class TestRunningMastery:
    """Record answers update per-concept running mastery."""

    def test_mastery_updates_on_answer(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_answer(correct=True, concept=concept)
        mastery = engine.state.concept_mastery[concept]
        assert mastery["attempted"] == 1
        assert mastery["correct"] == 1
        assert mastery["mastery"] == pytest.approx(1.0)

    def test_mastery_multiple_answers(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_answer(correct=True, concept=concept)
        engine.record_answer(correct=False, concept=concept)
        engine.record_answer(correct=True, concept=concept)
        mastery = engine.state.concept_mastery[concept]
        assert mastery["attempted"] == 3
        assert mastery["correct"] == 2
        assert mastery["mastery"] == pytest.approx(2.0 / 3.0, abs=0.01)


# ---------------------------------------------------------------------------
# State serialization (to JSON and back)
# ---------------------------------------------------------------------------


class TestStateSerialization:
    """State can be serialized to JSON and deserialized exactly."""

    def test_roundtrip_json(self) -> None:
        engine = _make_engine(difficulty=0.65)
        engine.record_answer(correct=True, concept=_CONCEPTS[0])
        engine.record_answer(correct=False, concept=_CONCEPTS[1])

        # Serialize
        state_json = engine.to_json()
        # Must be valid JSON
        parsed = json.loads(state_json)
        assert parsed["phase"] == "diagnostic"
        assert parsed["difficulty"] == pytest.approx(0.65)
        assert parsed["session_id"] == str(_SESSION_ID)

        # Deserialize
        restored = SessionEngine.from_json(state_json)
        assert restored.session_id == engine.session_id
        assert restored.user_id == engine.user_id
        assert restored.current_phase == engine.current_phase
        assert restored.state.difficulty == pytest.approx(engine.state.difficulty)
        assert restored.state.total_problems == engine.state.total_problems
        assert restored.state.total_correct == engine.state.total_correct
        assert (
            restored.state.concept_mastery.keys() == engine.state.concept_mastery.keys()
        )

    def test_to_state_dict_matches_db_state_json(self) -> None:
        """to_state_dict() returns a dict for state_json."""
        engine = _make_engine()
        state_dict = engine.to_state_dict()
        assert isinstance(state_dict, dict)
        assert "phase" in state_dict
        assert "difficulty" in state_dict
        assert "concepts" in state_dict
        assert "concept_mastery" in state_dict


# ---------------------------------------------------------------------------
# Session resume from DB state
# ---------------------------------------------------------------------------


class TestSessionResume:
    """Phase-level resume from persisted state_json."""

    def test_resume_preserves_phase(self) -> None:
        engine = _make_engine(phase=SessionPhase.diagnostic)
        engine.record_answer(correct=True, concept=_CONCEPTS[0])
        engine.record_answer(correct=True, concept=_CONCEPTS[0])
        engine.advance_phase()
        assert engine.current_phase == SessionPhase.focused_practice

        # Simulate DB persistence and resume
        state_json = engine.to_json()
        resumed = SessionEngine.from_json(state_json)

        assert resumed.current_phase == SessionPhase.focused_practice
        assert resumed.state.total_problems == engine.state.total_problems
        assert resumed.state.total_correct == engine.state.total_correct

    def test_resume_preserves_difficulty(self) -> None:
        engine = _make_engine(difficulty=0.5)
        # Two correct -> difficulty increases
        engine.record_answer(correct=True)
        engine.record_answer(correct=True)
        expected_difficulty = 0.5 + DIFFICULTY_STEP

        state_json = engine.to_json()
        resumed = SessionEngine.from_json(state_json)
        assert resumed.state.difficulty == pytest.approx(expected_difficulty)

    def test_resume_preserves_concept_mastery(self) -> None:
        engine = _make_engine()
        engine.record_answer(correct=True, concept=_CONCEPTS[0])
        engine.record_answer(correct=False, concept=_CONCEPTS[1])

        state_json = engine.to_json()
        resumed = SessionEngine.from_json(state_json)

        assert _CONCEPTS[0] in resumed.state.concept_mastery
        assert _CONCEPTS[1] in resumed.state.concept_mastery
        assert resumed.state.concept_mastery[_CONCEPTS[0]]["correct"] == 1
        assert resumed.state.concept_mastery[_CONCEPTS[1]]["correct"] == 0

    def test_resume_from_state_dict(self) -> None:
        """Resume from a dict (as stored in test_prep_sessions.state_json)."""
        engine = _make_engine(phase=SessionPhase.error_analysis, difficulty=0.7)
        engine.record_answer(correct=True, concept=_CONCEPTS[0])

        state_dict = engine.to_state_dict()
        resumed = SessionEngine.from_state_dict(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            state_dict=state_dict,
        )

        assert resumed.session_id == _SESSION_ID
        assert resumed.user_id == _USER_ID
        assert resumed.current_phase == SessionPhase.error_analysis
        assert resumed.state.difficulty == pytest.approx(0.7)
        assert resumed.state.course_id == _COURSE_ID


# ---------------------------------------------------------------------------
# Streak reset on mixed answers
# ---------------------------------------------------------------------------


class TestStreakReset:
    """Consecutive streak resets when the pattern breaks."""

    def test_streak_resets_on_wrong_after_correct(self) -> None:
        engine = _make_engine(difficulty=0.5)
        engine.record_answer(correct=True)
        engine.record_answer(correct=False)
        # Streak is reset; next correct should not trigger increase
        engine.record_answer(correct=True)
        assert engine.state.difficulty == pytest.approx(0.5)

    def test_streak_resets_on_correct_after_wrong(self) -> None:
        engine = _make_engine(difficulty=0.5)
        engine.record_answer(correct=False)
        engine.record_answer(correct=True)
        # Streak is reset; next wrong should not trigger decrease
        engine.record_answer(correct=False)
        assert engine.state.difficulty == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Session type: phase durations & quick mode (US-007 / DEC-004, R3, R6)
# ---------------------------------------------------------------------------


class TestSessionTypeDurations:
    """Phase timing for full (45min) and quick (15min) session modes."""

    def test_full_durations(self) -> None:
        """Full session has 5 phases totalling 45 minutes."""
        engine = _make_engine(session_type="full")
        assert engine.session_type == "full"
        assert engine.phase_durations == FULL_PHASE_DURATIONS
        # Total should be 45 minutes
        assert sum(FULL_PHASE_DURATIONS.values()) == 45
        # Individual durations
        assert FULL_PHASE_DURATIONS[SessionPhase.diagnostic] == 5
        assert FULL_PHASE_DURATIONS[SessionPhase.focused_practice] == 8
        assert FULL_PHASE_DURATIONS[SessionPhase.error_analysis] == 12
        assert FULL_PHASE_DURATIONS[SessionPhase.mixed_test] == 15
        assert FULL_PHASE_DURATIONS[SessionPhase.calibration] == 5

    def test_quick_skips_phases_1_3(self) -> None:
        """Quick session only has mixed_test and calibration phases."""
        engine = _make_engine(session_type="quick")
        assert engine.session_type == "quick"
        assert engine.phase_durations == QUICK_PHASE_DURATIONS
        # Only 2 phases
        assert len(QUICK_PHASE_DURATIONS) == 2
        assert SessionPhase.diagnostic not in QUICK_PHASE_DURATIONS
        assert SessionPhase.focused_practice not in QUICK_PHASE_DURATIONS
        assert SessionPhase.error_analysis not in QUICK_PHASE_DURATIONS
        # Total should be 15 minutes
        assert sum(QUICK_PHASE_DURATIONS.values()) == 15
        assert QUICK_PHASE_DURATIONS[SessionPhase.mixed_test] == 10
        assert QUICK_PHASE_DURATIONS[SessionPhase.calibration] == 5

    def test_quick_starts_at_mixed(self) -> None:
        """Quick session starts at mixed_test, not diagnostic."""
        engine = _make_engine(session_type="quick")
        assert engine.current_phase == SessionPhase.mixed_test
        assert engine.phase_order == QUICK_PHASE_ORDER
        # Can advance to calibration
        engine.advance_phase()
        assert engine.current_phase == SessionPhase.calibration
        # Cannot advance past calibration
        with pytest.raises(ValueError, match="[Cc]annot advance"):
            engine.advance_phase()

    def test_advance_uses_new_durations(self) -> None:
        """advance_phase() returns durations from the correct session type."""
        full_engine = _make_engine(session_type="full")
        assert full_engine.current_phase_duration == 5  # diagnostic
        full_engine.advance_phase()
        assert full_engine.current_phase_duration == 8  # focused_practice
        full_engine.advance_phase()
        assert full_engine.current_phase_duration == 12  # error_analysis
        full_engine.advance_phase()
        assert full_engine.current_phase_duration == 15  # mixed_test
        full_engine.advance_phase()
        assert full_engine.current_phase_duration == 5  # calibration

        quick_engine = _make_engine(session_type="quick")
        assert quick_engine.current_phase_duration == 10  # mixed_test
        quick_engine.advance_phase()
        assert quick_engine.current_phase_duration == 5  # calibration


class TestSessionTypeSerializationRoundtrip:
    """session_type is preserved through serialization/deserialization."""

    def test_full_roundtrip(self) -> None:
        engine = _make_engine(session_type="full")
        state_dict = engine.to_state_dict()
        assert state_dict["session_type"] == "full"

        restored = SessionEngine.from_state_dict(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            state_dict=state_dict,
        )
        assert restored.session_type == "full"
        assert restored.phase_order == PHASE_ORDER

    def test_quick_roundtrip(self) -> None:
        engine = _make_engine(session_type="quick")
        state_dict = engine.to_state_dict()
        assert state_dict["session_type"] == "quick"

        restored = SessionEngine.from_state_dict(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            state_dict=state_dict,
        )
        assert restored.session_type == "quick"
        assert restored.current_phase == SessionPhase.mixed_test
        assert restored.phase_order == QUICK_PHASE_ORDER

    def test_from_state_dict_defaults_to_full(self) -> None:
        """Legacy state dicts without session_type default to full."""
        engine = _make_engine(session_type="full")
        state_dict = engine.to_state_dict()
        del state_dict["session_type"]

        restored = SessionEngine.from_state_dict(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            state_dict=state_dict,
        )
        assert restored.session_type == "full"


# ---------------------------------------------------------------------------
# Confidence tracking (US-009)
# ---------------------------------------------------------------------------


class TestConfidenceRecording:
    """US-009: Record per-concept confidence at phase transitions."""

    def test_record_single_confidence(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_confidence(concept=concept, rating=4)
        assert concept in engine.state.per_concept_confidence
        entries = engine.state.per_concept_confidence[concept]
        assert len(entries) == 1
        assert entries[0]["rating"] == 4
        assert entries[0]["phase"] == "diagnostic"

    def test_record_confidence_at_different_phases(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_confidence(concept=concept, rating=2)
        engine.advance_phase()  # -> focused_practice
        engine.record_confidence(concept=concept, rating=4)
        entries = engine.state.per_concept_confidence[concept]
        assert len(entries) == 2
        assert entries[0]["phase"] == "diagnostic"
        assert entries[1]["phase"] == "focused_practice"

    def test_record_confidence_multiple_concepts(self) -> None:
        engine = _make_engine()
        engine.record_confidence(concept=_CONCEPTS[0], rating=3)
        engine.record_confidence(concept=_CONCEPTS[1], rating=5)
        assert len(engine.state.per_concept_confidence) == 2
        assert engine.state.per_concept_confidence[_CONCEPTS[0]][0]["rating"] == 3
        assert engine.state.per_concept_confidence[_CONCEPTS[1]][0]["rating"] == 5

    def test_record_confidence_rejects_invalid_rating(self) -> None:
        engine = _make_engine()
        with pytest.raises(ValueError, match="1-5"):
            engine.record_confidence(concept=_CONCEPTS[0], rating=0)
        with pytest.raises(ValueError, match="1-5"):
            engine.record_confidence(concept=_CONCEPTS[0], rating=6)

    def test_confidence_custom_phase(self) -> None:
        engine = _make_engine()
        engine.record_confidence(concept=_CONCEPTS[0], rating=3, phase="pre_mixed")
        entries = engine.state.per_concept_confidence[_CONCEPTS[0]]
        assert entries[0]["phase"] == "pre_mixed"


class TestConfidenceVsPerformance:
    """US-009: Confidence vs performance comparison."""

    def test_comparison_with_data(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_confidence(concept=concept, rating=5)
        engine.record_answer(correct=True, concept=concept)
        engine.record_answer(correct=False, concept=concept)
        rows = engine.get_confidence_vs_performance()
        row = next(r for r in rows if r["concept"] == concept)
        assert row["avg_confidence"] == pytest.approx(1.0)
        assert row["accuracy"] == pytest.approx(0.5)
        assert row["gap_label"] == "overconfident"

    def test_comparison_calibrated(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_confidence(concept=concept, rating=3)
        for _ in range(3):
            engine.record_answer(correct=True, concept=concept)
        for _ in range(2):
            engine.record_answer(correct=False, concept=concept)
        rows = engine.get_confidence_vs_performance()
        row = next(r for r in rows if r["concept"] == concept)
        assert row["gap_label"] == "calibrated"

    def test_comparison_underconfident(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_confidence(concept=concept, rating=1)
        for _ in range(4):
            engine.record_answer(correct=True, concept=concept)
        engine.record_answer(correct=False, concept=concept)
        rows = engine.get_confidence_vs_performance()
        row = next(r for r in rows if r["concept"] == concept)
        assert row["gap_label"] == "underconfident"

    def test_comparison_no_confidence(self) -> None:
        engine = _make_engine()
        concept = _CONCEPTS[0]
        engine.record_answer(correct=True, concept=concept)
        rows = engine.get_confidence_vs_performance()
        row = next(r for r in rows if r["concept"] == concept)
        assert row["avg_confidence"] is None
        assert row["gap_label"] is None


class TestConfidenceSerialization:
    """US-009: Confidence data survives serialization roundtrip."""

    def test_roundtrip_preserves_confidence(self) -> None:
        engine = _make_engine()
        engine.record_confidence(concept=_CONCEPTS[0], rating=4)
        engine.record_confidence(concept=_CONCEPTS[1], rating=2)
        state_json = engine.to_json()
        restored = SessionEngine.from_json(state_json)
        assert _CONCEPTS[0] in restored.state.per_concept_confidence
        assert _CONCEPTS[1] in restored.state.per_concept_confidence
        assert restored.state.per_concept_confidence[_CONCEPTS[0]][0]["rating"] == 4
        assert restored.state.per_concept_confidence[_CONCEPTS[1]][0]["rating"] == 2

    def test_state_dict_includes_confidence(self) -> None:
        engine = _make_engine()
        engine.record_confidence(concept=_CONCEPTS[0], rating=3)
        state_dict = engine.to_state_dict()
        assert "per_concept_confidence" in state_dict
        assert _CONCEPTS[0] in state_dict["per_concept_confidence"]

    def test_from_state_dict_without_confidence(self) -> None:
        """Backward compatible: old state dicts without confidence field."""
        engine = _make_engine()
        state_dict = engine.to_state_dict()
        del state_dict["per_concept_confidence"]
        restored = SessionEngine.from_state_dict(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            state_dict=state_dict,
        )
        assert restored.state.per_concept_confidence == {}
