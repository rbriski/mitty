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
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    PHASE_ORDER,
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
    phase: SessionPhase = SessionPhase.diagnostic,
    difficulty: float = 0.5,
    concepts: list[str] | None = None,
) -> SessionEngine:
    """Build a SessionEngine with a pre-set state for testing."""
    return SessionEngine(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        course_id=_COURSE_ID,
        concepts=concepts or list(_CONCEPTS),
        initial_difficulty=difficulty,
        initial_phase=phase,
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
