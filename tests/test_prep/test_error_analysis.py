"""Tests for US-010 error analysis enhancements.

Covers:
- find_the_mistake problem subtype in generator
- review_own_errors builder (no LLM)
- SessionEngine Phase 3 alternation logic
- Wrong answer recording and pop
- Serialization round-trip with new fields

Traces: US-010, R6 (desirable difficulty).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from mitty.ai.errors import AIClientError
from mitty.prep.generator import (
    GeneratedProblem,
    ProblemType,
    build_review_own_errors,
    generate_problem,
)
from mitty.prep.session import SessionEngine, SessionPhase

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
    session_type: str = "full",
) -> SessionEngine:
    return SessionEngine(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        course_id=_COURSE_ID,
        concepts=list(_CONCEPTS),
        initial_difficulty=difficulty,
        initial_phase=phase,
        session_type=session_type,
    )


def _build_mock_ai(response: GeneratedProblem) -> AsyncMock:
    ai = AsyncMock()
    ai.call_structured = AsyncMock(return_value=response)
    ai._model = "claude-sonnet-4-20250514"
    return ai


def _sample_wrong_answer() -> dict:
    return {
        "problem_id": "42",
        "concept": "polynomial long division",
        "problem_json": {
            "prompt": "Divide 2x^3 + 3x^2 - x + 5 by x - 2.",
            "correct_answer": "2x^2 + 7x + 13, R31",
            "explanation": "Using synthetic division, bring down 2...",
        },
        "student_answer": "2x^2 + 7x + 13, R27",
        "feedback": "The correct answer is: 2x^2 + 7x + 13, R31",
        "difficulty": 0.6,
    }


# ---------------------------------------------------------------------------
# ProblemType enum includes new subtypes
# ---------------------------------------------------------------------------


class TestProblemTypeEnum:
    """ProblemType enum has all 8 required types including US-010 additions."""

    def test_has_find_the_mistake(self) -> None:
        assert "find_the_mistake" in {t.value for t in ProblemType}

    def test_has_review_own_errors(self) -> None:
        assert "review_own_errors" in {t.value for t in ProblemType}

    def test_total_count(self) -> None:
        assert len(ProblemType) == 8


# ---------------------------------------------------------------------------
# find_the_mistake generation via LLM
# ---------------------------------------------------------------------------


class TestFindTheMistake:
    """find_the_mistake uses the LLM generator like other problem types."""

    async def test_generate_find_the_mistake(self) -> None:
        mock_response = GeneratedProblem(
            prompt=(
                "A student solved the equation 2x + 5 = 11 as follows:\n"
                "Step 1: 2x = 11 - 5 = 6\n"
                "Step 2: x = 6 / 2 = 4\n"  # deliberately wrong step 2
                "Step 3: x = 4\n"
                "Find the error."
            ),
            choices=None,
            correct_answer="Step 2 is wrong: 6/2 = 3, not 4.",
            explanation="The arithmetic in step 2 is incorrect. 6/2 = 3.",
            hint="Check the arithmetic in each step carefully.",
        )
        ai = _build_mock_ai(mock_response)

        result = await generate_problem(
            concept="linear equations",
            difficulty=0.5,
            problem_type="find_the_mistake",
            ai_client=ai,
        )

        assert result["type"] == "find_the_mistake"
        assert result["concept"] == "linear equations"
        assert "Find the error" in result["prompt"]
        assert result["correct_answer"] is not None
        assert result["explanation"] is not None

    async def test_find_the_mistake_fallback(self) -> None:
        ai = AsyncMock()
        ai.call_structured = AsyncMock(
            side_effect=AIClientError("unavailable", status_code=503)
        )
        ai._model = "claude-sonnet-4-20250514"

        result = await generate_problem(
            concept="linear equations",
            difficulty=0.5,
            problem_type="find_the_mistake",
            ai_client=ai,
        )

        assert result["type"] == "find_the_mistake"
        assert result["is_fallback"] is True


# ---------------------------------------------------------------------------
# review_own_errors builder (no LLM)
# ---------------------------------------------------------------------------


class TestReviewOwnErrors:
    """build_review_own_errors produces reflection problems from wrong answers."""

    def test_builds_reflection_from_wrong_answer(self) -> None:
        wrong = _sample_wrong_answer()
        result = build_review_own_errors(wrong_answer=wrong)

        assert result["type"] == "review_own_errors"
        assert result["is_reflection"] is True
        assert result["concept"] == "polynomial long division"
        assert result["difficulty"] == 0.6
        assert "Your answer:" in result["prompt"]
        assert "2x^2 + 7x + 13, R27" in result["prompt"]
        assert "Correct answer:" in result["prompt"]
        assert result["choices"] is None

    def test_includes_feedback_in_prompt(self) -> None:
        wrong = _sample_wrong_answer()
        result = build_review_own_errors(wrong_answer=wrong)
        assert "Feedback:" in result["prompt"]

    def test_handles_missing_feedback(self) -> None:
        wrong = _sample_wrong_answer()
        wrong["feedback"] = ""
        result = build_review_own_errors(wrong_answer=wrong)
        assert "Feedback:" not in result["prompt"]
        assert result["is_reflection"] is True

    def test_includes_correct_answer_and_explanation(self) -> None:
        wrong = _sample_wrong_answer()
        result = build_review_own_errors(wrong_answer=wrong)
        assert result["correct_answer"] == "2x^2 + 7x + 13, R31"
        assert "synthetic division" in result["explanation"]

    def test_handles_minimal_wrong_answer(self) -> None:
        """Handles a wrong answer with minimal/missing fields."""
        wrong = {
            "problem_json": {},
            "student_answer": "something",
            "feedback": "",
        }
        result = build_review_own_errors(wrong_answer=wrong)
        assert result["type"] == "review_own_errors"
        assert result["is_reflection"] is True
        assert result["concept"] == "unknown"


# ---------------------------------------------------------------------------
# SessionEngine: wrong answer recording
# ---------------------------------------------------------------------------


class TestWrongAnswerRecording:
    """Wrong answers are recorded only during Phases 1-2."""

    def test_records_in_diagnostic(self) -> None:
        engine = _make_engine(phase=SessionPhase.diagnostic)
        engine.record_wrong_answer(
            problem_id=1,
            concept="algebra",
            problem_json={"prompt": "test"},
            student_answer="wrong",
            feedback="nope",
            difficulty=0.5,
        )
        assert len(engine.state.wrong_answers) == 1
        assert engine.state.wrong_answers[0]["concept"] == "algebra"

    def test_records_in_focused_practice(self) -> None:
        engine = _make_engine(phase=SessionPhase.focused_practice)
        engine.record_wrong_answer(
            problem_id=2,
            concept="trig",
            problem_json={"prompt": "test"},
            student_answer="wrong",
            feedback="nope",
            difficulty=0.5,
        )
        assert len(engine.state.wrong_answers) == 1

    def test_ignores_in_error_analysis(self) -> None:
        engine = _make_engine(phase=SessionPhase.error_analysis)
        engine.record_wrong_answer(
            problem_id=3,
            concept="calc",
            problem_json={"prompt": "test"},
            student_answer="wrong",
            feedback="nope",
            difficulty=0.5,
        )
        assert len(engine.state.wrong_answers) == 0

    def test_ignores_in_mixed_test(self) -> None:
        engine = _make_engine(phase=SessionPhase.mixed_test)
        engine.record_wrong_answer(
            problem_id=4,
            concept="calc",
            problem_json={"prompt": "test"},
            student_answer="wrong",
            feedback="nope",
            difficulty=0.5,
        )
        assert len(engine.state.wrong_answers) == 0


# ---------------------------------------------------------------------------
# SessionEngine: error analysis subtype alternation
# ---------------------------------------------------------------------------


class TestErrorAnalysisSubtype:
    """Phase 3 alternates between find_the_mistake and review_own_errors."""

    def test_first_is_find_the_mistake(self) -> None:
        engine = _make_engine(phase=SessionPhase.error_analysis)
        assert engine.get_error_analysis_subtype() == "find_the_mistake"

    def test_second_is_review_own_errors_when_available(self) -> None:
        engine = _make_engine(phase=SessionPhase.error_analysis)
        engine.state.wrong_answers.append(_sample_wrong_answer())
        # First call: find_the_mistake (count=0, even)
        engine.get_error_analysis_subtype()
        # Second call: review_own_errors (count=1, odd, wrong answers available)
        assert engine.get_error_analysis_subtype() == "review_own_errors"

    def test_falls_back_to_find_the_mistake_when_no_wrong_answers(self) -> None:
        engine = _make_engine(phase=SessionPhase.error_analysis)
        # First call: find_the_mistake
        engine.get_error_analysis_subtype()
        # Second call: no wrong answers, falls back to find_the_mistake
        assert engine.get_error_analysis_subtype() == "find_the_mistake"

    def test_alternation_pattern(self) -> None:
        engine = _make_engine(phase=SessionPhase.error_analysis)
        # Add two wrong answers
        engine.state.wrong_answers.append(_sample_wrong_answer())
        engine.state.wrong_answers.append(_sample_wrong_answer())

        subtypes = [engine.get_error_analysis_subtype() for _ in range(4)]
        assert subtypes == [
            "find_the_mistake",  # count=0: even
            "review_own_errors",  # count=1: odd, has wrong answers
            "find_the_mistake",  # count=2: even
            "review_own_errors",  # count=3: odd, has wrong answers
        ]

    def test_counter_increments(self) -> None:
        engine = _make_engine(phase=SessionPhase.error_analysis)
        assert engine.state.error_analysis_count == 0
        engine.get_error_analysis_subtype()
        assert engine.state.error_analysis_count == 1
        engine.get_error_analysis_subtype()
        assert engine.state.error_analysis_count == 2


class TestPopWrongAnswer:
    """pop_wrong_answer removes and returns the first wrong answer."""

    def test_pop_returns_first(self) -> None:
        engine = _make_engine(phase=SessionPhase.diagnostic)
        engine.record_wrong_answer(
            problem_id=1,
            concept="a",
            problem_json={},
            student_answer="x",
            feedback="f",
            difficulty=0.5,
        )
        engine.record_wrong_answer(
            problem_id=2,
            concept="b",
            problem_json={},
            student_answer="y",
            feedback="g",
            difficulty=0.6,
        )
        first = engine.pop_wrong_answer()
        assert first is not None
        assert first["concept"] == "a"
        assert len(engine.state.wrong_answers) == 1

    def test_pop_returns_none_when_empty(self) -> None:
        engine = _make_engine()
        assert engine.pop_wrong_answer() is None


# ---------------------------------------------------------------------------
# Serialization round-trip includes new fields
# ---------------------------------------------------------------------------


class TestErrorAnalysisSerialization:
    """wrong_answers and error_analysis_count survive serialization."""

    def test_roundtrip_preserves_wrong_answers(self) -> None:
        engine = _make_engine(phase=SessionPhase.diagnostic)
        engine.record_wrong_answer(
            problem_id=1,
            concept="algebra",
            problem_json={"prompt": "test"},
            student_answer="wrong",
            feedback="nope",
            difficulty=0.5,
        )
        engine.get_error_analysis_subtype()  # increment counter

        state_json = engine.to_json()
        restored = SessionEngine.from_json(state_json)

        assert len(restored.state.wrong_answers) == 1
        assert restored.state.wrong_answers[0]["concept"] == "algebra"
        assert restored.state.error_analysis_count == 1

    def test_from_state_dict_without_new_fields(self) -> None:
        """Backward compatible: old state dicts without US-010 fields."""
        engine = _make_engine()
        state_dict = engine.to_state_dict()
        del state_dict["wrong_answers"]
        del state_dict["error_analysis_count"]

        restored = SessionEngine.from_state_dict(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            state_dict=state_dict,
        )
        assert restored.state.wrong_answers == []
        assert restored.state.error_analysis_count == 0
