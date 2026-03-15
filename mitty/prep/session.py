"""5-phase adaptive session engine for test prep.

Manages the full session lifecycle: diagnostic -> focused_practice ->
error_analysis -> mixed_test -> calibration.  Adapts difficulty based
on student performance (+-0.15 on 2 consecutive correct/wrong, clamped
to [0.1, 0.95]).  Tracks running per-concept mastery.  Serializes
state to JSON for DB persistence (``test_prep_sessions.state_json``)
and supports phase-level resume.

Phase 3 (error_analysis) alternates between two subtypes (US-010, R6):
- ``find_the_mistake``: LLM generates a worked solution with one
  deliberate error; the student identifies and explains it.
- ``review_own_errors``: pulls a wrong answer from Phases 1-2 and
  presents it for ungraded self-explanation reflection.

Traces: DEC-004 (5 session phases), DEC-006 (UUID PKs),
        DEC-008 (server-authoritative state), US-010 (error analysis).

Public API:
    SessionEngine        — main engine class
    SessionPhase         — phase enum
    SessionState         — mutable session state dataclass
    PHASE_ORDER          — ordered list of phases (full mode)
    QUICK_PHASE_ORDER    — ordered list of phases (quick mode)
    FULL_PHASE_DURATIONS — phase durations in minutes (full 45min session)
    QUICK_PHASE_DURATIONS— phase durations in minutes (quick 15min session)
    DIFFICULTY_STEP      — per-adjustment difficulty delta (0.15)
    MIN_DIFFICULTY       — lower clamp (0.1)
    MAX_DIFFICULTY       — upper clamp (0.95)
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (DEC-004 / difficulty adaptation spec)
# ---------------------------------------------------------------------------

DIFFICULTY_STEP: float = 0.15
"""Difficulty adjustment per 2-streak event."""

MIN_DIFFICULTY: float = 0.1
"""Lower bound for difficulty (clamped)."""

MAX_DIFFICULTY: float = 0.95
"""Upper bound for difficulty (clamped)."""

STREAK_THRESHOLD: int = 2
"""Consecutive correct/wrong answers required to trigger adjustment."""


# ---------------------------------------------------------------------------
# Session phases (DEC-004)
# ---------------------------------------------------------------------------


class SessionPhase(enum.StrEnum):
    """5 ordered phases of an adaptive test prep session."""

    diagnostic = "diagnostic"
    focused_practice = "focused_practice"
    error_analysis = "error_analysis"
    mixed_test = "mixed_test"
    calibration = "calibration"


PHASE_ORDER: list[SessionPhase] = [
    SessionPhase.diagnostic,
    SessionPhase.focused_practice,
    SessionPhase.error_analysis,
    SessionPhase.mixed_test,
    SessionPhase.calibration,
]
"""Canonical phase ordering for full sessions.  ``advance_phase()`` follows this."""

QUICK_PHASE_ORDER: list[SessionPhase] = [
    SessionPhase.mixed_test,
    SessionPhase.calibration,
]
"""Phase ordering for quick sessions (skip phases 1-3)."""

# ---------------------------------------------------------------------------
# Phase durations (minutes) — DEC-004, R3, R6
# ---------------------------------------------------------------------------

FULL_PHASE_DURATIONS: dict[SessionPhase, int] = {
    SessionPhase.diagnostic: 5,
    SessionPhase.focused_practice: 8,
    SessionPhase.error_analysis: 12,
    SessionPhase.mixed_test: 15,
    SessionPhase.calibration: 5,
}
"""Phase durations for a full 45-minute session."""

QUICK_PHASE_DURATIONS: dict[SessionPhase, int] = {
    SessionPhase.mixed_test: 10,
    SessionPhase.calibration: 5,
}
"""Phase durations for a quick 15-minute session."""


# ---------------------------------------------------------------------------
# Mutable session state
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """Mutable state that the session engine tracks and persists.

    Stored as ``test_prep_sessions.state_json`` in the database.
    """

    phase: SessionPhase
    difficulty: float
    course_id: int
    concepts: list[str]
    concept_mastery: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_problems: int = 0
    total_correct: int = 0
    consecutive_correct: int = 0
    consecutive_wrong: int = 0

    # Per-phase counters
    phase_problems: dict[str, int] = field(default_factory=dict)
    phase_correct: dict[str, int] = field(default_factory=dict)

    # Per-concept confidence ratings at phase transitions (US-009 / DEC-008, R5)
    # Structure: { concept: [ {phase, rating, timestamp}, ... ] }
    per_concept_confidence: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )

    # Wrong answers from Phases 1-2 for review_own_errors (US-010)
    # Keys: problem_id, concept, problem_json, student_answer, feedback
    wrong_answers: list[dict[str, Any]] = field(default_factory=list)

    # Counter for alternating error_analysis subtypes in Phase 3 (US-010)
    error_analysis_count: int = 0


# ---------------------------------------------------------------------------
# Session engine
# ---------------------------------------------------------------------------


class SessionEngine:
    """Manages a single adaptive test prep session.

    Supports two session types:
    - ``"full"`` (45 min): all 5 phases (diagnostic -> calibration).
    - ``"quick"`` (15 min): mixed_test + calibration only.

    Args:
        session_id: UUID primary key (DEC-006).
        user_id: Student's UUID.
        course_id: Canvas course ID.
        concepts: List of concepts being tested.
        initial_difficulty: Starting difficulty (default 0.5).
        initial_phase: Starting phase (auto-set for quick mode).
        session_type: ``"full"`` or ``"quick"`` (default ``"full"``).
    """

    def __init__(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        course_id: int,
        concepts: list[str],
        initial_difficulty: float = 0.5,
        initial_phase: SessionPhase | None = None,
        session_type: str = "full",
    ) -> None:
        if session_type not in ("full", "quick"):
            msg = f"session_type must be 'full' or 'quick', got {session_type!r}"
            raise ValueError(msg)

        self._session_id = session_id
        self._user_id = user_id
        self._session_type = session_type

        # Derive phase order and durations from session type
        if session_type == "quick":
            self._phase_order = list(QUICK_PHASE_ORDER)
            self._phase_durations = dict(QUICK_PHASE_DURATIONS)
            default_phase = SessionPhase.mixed_test
        else:
            self._phase_order = list(PHASE_ORDER)
            self._phase_durations = dict(FULL_PHASE_DURATIONS)
            default_phase = SessionPhase.diagnostic

        start_phase = initial_phase if initial_phase is not None else default_phase

        clamped = _clamp_difficulty(initial_difficulty)
        self._state = SessionState(
            phase=start_phase,
            difficulty=clamped,
            course_id=course_id,
            concepts=list(concepts),
        )

    # -- Properties ----------------------------------------------------------

    @property
    def session_id(self) -> UUID:
        return self._session_id

    @property
    def user_id(self) -> UUID:
        return self._user_id

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def current_phase(self) -> SessionPhase:
        return self._state.phase

    @property
    def session_type(self) -> str:
        """Session type: ``"full"`` or ``"quick"``."""
        return self._session_type

    @property
    def phase_order(self) -> list[SessionPhase]:
        """Ordered phases for this session type."""
        return list(self._phase_order)

    @property
    def phase_durations(self) -> dict[SessionPhase, int]:
        """Phase durations (minutes) for this session type."""
        return dict(self._phase_durations)

    @property
    def current_phase_duration(self) -> int:
        """Duration in minutes for the current phase."""
        return self._phase_durations[self._state.phase]

    # -- Phase transitions ---------------------------------------------------

    def advance_phase(self) -> SessionPhase:
        """Move to the next phase in the session's phase order.

        Returns:
            The new current phase.

        Raises:
            ValueError: If already at the final phase (calibration).
        """
        current_idx = self._phase_order.index(self._state.phase)
        if current_idx >= len(self._phase_order) - 1:
            msg = f"Cannot advance past the final phase ({self._state.phase.value!r})"
            raise ValueError(msg)

        new_phase = self._phase_order[current_idx + 1]
        logger.info(
            "Session %s: phase %s -> %s",
            self._session_id,
            self._state.phase.value,
            new_phase.value,
        )
        self._state.phase = new_phase
        # Reset consecutive streaks on phase change
        self._state.consecutive_correct = 0
        self._state.consecutive_wrong = 0
        return new_phase

    # -- Answer recording & difficulty adaptation ----------------------------

    def record_answer(
        self,
        *,
        correct: bool,
        concept: str | None = None,
    ) -> None:
        """Record a student answer and adapt difficulty.

        Difficulty increases by DIFFICULTY_STEP after STREAK_THRESHOLD
        consecutive correct answers, and decreases by the same amount
        after STREAK_THRESHOLD consecutive wrong answers.  Clamped to
        [MIN_DIFFICULTY, MAX_DIFFICULTY].

        If *concept* is provided, running per-concept mastery is updated.

        Args:
            correct: Whether the answer was correct.
            concept: Optional concept the problem belongs to.
        """
        self._state.total_problems += 1

        # Per-phase counters
        phase_key = self._state.phase.value
        self._state.phase_problems[phase_key] = (
            self._state.phase_problems.get(phase_key, 0) + 1
        )

        if correct:
            self._state.total_correct += 1
            self._state.phase_correct[phase_key] = (
                self._state.phase_correct.get(phase_key, 0) + 1
            )
            self._state.consecutive_correct += 1
            self._state.consecutive_wrong = 0
        else:
            self._state.consecutive_wrong += 1
            self._state.consecutive_correct = 0

        # Difficulty adaptation
        if self._state.consecutive_correct >= STREAK_THRESHOLD:
            self._state.difficulty = _clamp_difficulty(
                self._state.difficulty + DIFFICULTY_STEP
            )
            self._state.consecutive_correct = 0
            logger.debug(
                "Session %s: difficulty increased to %.2f",
                self._session_id,
                self._state.difficulty,
            )

        if self._state.consecutive_wrong >= STREAK_THRESHOLD:
            self._state.difficulty = _clamp_difficulty(
                self._state.difficulty - DIFFICULTY_STEP
            )
            self._state.consecutive_wrong = 0
            logger.debug(
                "Session %s: difficulty decreased to %.2f",
                self._session_id,
                self._state.difficulty,
            )

        # Per-concept mastery
        if concept is not None:
            self._update_concept_mastery(concept, correct)

    def _update_concept_mastery(self, concept: str, correct: bool) -> None:
        """Update running mastery for a single concept."""
        entry = self._state.concept_mastery.setdefault(
            concept,
            {"attempted": 0, "correct": 0, "mastery": 0.0},
        )
        entry["attempted"] += 1
        if correct:
            entry["correct"] += 1
        entry["mastery"] = entry["correct"] / entry["attempted"]

    # -- Error analysis subtypes (US-010, R6) ---------------------------------

    def record_wrong_answer(
        self,
        *,
        problem_id: int | str,
        concept: str,
        problem_json: dict[str, Any],
        student_answer: str,
        feedback: str,
        difficulty: float,
    ) -> None:
        """Record a wrong answer for potential review in Phase 3.

        Only recorded during Phases 1 (diagnostic) and 2 (focused_practice)
        so Phase 3 can present them as review_own_errors reflections.
        """
        if self._state.phase not in (
            SessionPhase.diagnostic,
            SessionPhase.focused_practice,
        ):
            return

        self._state.wrong_answers.append(
            {
                "problem_id": str(problem_id),
                "concept": concept,
                "problem_json": problem_json,
                "student_answer": student_answer,
                "feedback": feedback,
                "difficulty": difficulty,
            }
        )
        logger.debug(
            "Session %s: recorded wrong answer (concept=%s, total=%d)",
            self._session_id,
            concept,
            len(self._state.wrong_answers),
        )

    def get_error_analysis_subtype(self) -> str:
        """Return the next error analysis subtype, alternating between them.

        Alternation order (US-010, R6 desirable difficulty effect):
        - Even count -> ``find_the_mistake`` (LLM-generated)
        - Odd count  -> ``review_own_errors`` (if wrong answers available)

        Falls back to ``find_the_mistake`` if no wrong answers are
        available for review.

        Side effect: increments the internal counter.

        Returns:
            ``"find_the_mistake"`` or ``"review_own_errors"``.
        """
        count = self._state.error_analysis_count
        self._state.error_analysis_count += 1

        if count % 2 == 1 and self._state.wrong_answers:
            return "review_own_errors"
        return "find_the_mistake"

    def pop_wrong_answer(self) -> dict[str, Any] | None:
        """Remove and return the next wrong answer for review.

        Returns ``None`` if no wrong answers remain.
        """
        if self._state.wrong_answers:
            return self._state.wrong_answers.pop(0)
        return None

    # -- Confidence tracking (US-009 / DEC-008, R5) --------------------------

    def record_confidence(
        self,
        *,
        concept: str,
        rating: int,
        phase: str | None = None,
    ) -> None:
        """Record a confidence self-rating (1-5) for a concept.

        Called at phase transitions so we can compare confidence vs
        actual performance.  Stored in ``state_json.per_concept_confidence``.

        Args:
            concept: The concept being rated.
            rating: Student confidence 1-5.
            phase: Phase label (defaults to current phase).
        """
        if rating < 1 or rating > 5:
            msg = f"Confidence rating must be 1-5, got {rating}"
            raise ValueError(msg)

        phase_label = phase or self._state.phase.value
        entry = {
            "phase": phase_label,
            "rating": rating,
        }
        self._state.per_concept_confidence.setdefault(concept, []).append(entry)
        logger.debug(
            "Session %s: confidence %s=%d at phase %s",
            self._session_id,
            concept,
            rating,
            phase_label,
        )

    def get_confidence_vs_performance(self) -> list[dict[str, Any]]:
        """Build a comparison of confidence ratings vs actual performance.

        Returns a list of dicts with concept, confidence checkpoints,
        and actual mastery for the summary/calibration view.
        """
        rows: list[dict[str, Any]] = []
        all_concepts = set(self._state.per_concept_confidence.keys()) | set(
            self._state.concept_mastery.keys()
        )
        for concept in sorted(all_concepts):
            checkpoints = self._state.per_concept_confidence.get(concept, [])
            mastery = self._state.concept_mastery.get(concept, {})
            attempted = mastery.get("attempted", 0)
            correct = mastery.get("correct", 0)
            accuracy = mastery.get("mastery", 0.0)

            # Compute average confidence (normalised to 0-1 scale)
            ratings = [c["rating"] for c in checkpoints]
            avg_confidence = (sum(ratings) / len(ratings) / 5.0) if ratings else None

            gap = None
            gap_label = None
            if avg_confidence is not None and attempted > 0:
                gap = avg_confidence - accuracy
                if abs(gap) < 0.15:
                    gap_label = "calibrated"
                elif gap > 0:
                    gap_label = "overconfident"
                else:
                    gap_label = "underconfident"

            rows.append(
                {
                    "concept": concept,
                    "checkpoints": checkpoints,
                    "attempted": attempted,
                    "correct": correct,
                    "accuracy": round(accuracy, 3),
                    "avg_confidence": (
                        round(avg_confidence, 3) if avg_confidence is not None else None
                    ),
                    "gap": round(gap, 3) if gap is not None else None,
                    "gap_label": gap_label,
                }
            )
        return rows

    # -- Serialization -------------------------------------------------------

    def to_state_dict(self) -> dict[str, Any]:
        """Produce a dict suitable for ``test_prep_sessions.state_json``.

        This dict captures the full mutable state needed to resume a
        session from the database.
        """
        return {
            "session_id": str(self._session_id),
            "user_id": str(self._user_id),
            "course_id": self._state.course_id,
            "session_type": self._session_type,
            "phase": self._state.phase.value,
            "difficulty": self._state.difficulty,
            "concepts": self._state.concepts,
            "concept_mastery": self._state.concept_mastery,
            "total_problems": self._state.total_problems,
            "total_correct": self._state.total_correct,
            "consecutive_correct": self._state.consecutive_correct,
            "consecutive_wrong": self._state.consecutive_wrong,
            "phase_problems": self._state.phase_problems,
            "phase_correct": self._state.phase_correct,
            "per_concept_confidence": self._state.per_concept_confidence,
            "wrong_answers": self._state.wrong_answers,
            "error_analysis_count": self._state.error_analysis_count,
        }

    def to_json(self) -> str:
        """Serialize session state to a JSON string."""
        return json.dumps(self.to_state_dict())

    @classmethod
    def from_state_dict(
        cls,
        *,
        session_id: UUID,
        user_id: UUID,
        state_dict: dict[str, Any],
    ) -> SessionEngine:
        """Restore a SessionEngine from a persisted state dict.

        This supports phase-level resume from the database.

        Args:
            session_id: The session UUID.
            user_id: The student UUID.
            state_dict: The dict previously returned by ``to_state_dict()``.

        Returns:
            A fully reconstituted SessionEngine.
        """
        session_type = state_dict.get("session_type", "full")
        engine = cls(
            session_id=session_id,
            user_id=user_id,
            course_id=state_dict["course_id"],
            concepts=state_dict["concepts"],
            initial_difficulty=state_dict["difficulty"],
            initial_phase=SessionPhase(state_dict["phase"]),
            session_type=session_type,
        )
        engine._state.concept_mastery = dict(state_dict.get("concept_mastery", {}))
        engine._state.total_problems = state_dict.get("total_problems", 0)
        engine._state.total_correct = state_dict.get("total_correct", 0)
        engine._state.consecutive_correct = state_dict.get("consecutive_correct", 0)
        engine._state.consecutive_wrong = state_dict.get("consecutive_wrong", 0)
        engine._state.phase_problems = dict(state_dict.get("phase_problems", {}))
        engine._state.phase_correct = dict(state_dict.get("phase_correct", {}))
        engine._state.per_concept_confidence = {
            k: list(v) for k, v in state_dict.get("per_concept_confidence", {}).items()
        }
        engine._state.wrong_answers = list(state_dict.get("wrong_answers", []))
        engine._state.error_analysis_count = state_dict.get("error_analysis_count", 0)
        return engine

    @classmethod
    def from_json(cls, json_str: str) -> SessionEngine:
        """Deserialize a SessionEngine from a JSON string.

        Args:
            json_str: JSON string previously returned by ``to_json()``.

        Returns:
            A fully reconstituted SessionEngine.
        """
        data = json.loads(json_str)
        return cls.from_state_dict(
            session_id=UUID(data["session_id"]),
            user_id=UUID(data["user_id"]),
            state_dict=data,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp_difficulty(value: float) -> float:
    """Clamp difficulty to [MIN_DIFFICULTY, MAX_DIFFICULTY]."""
    return max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, value))
