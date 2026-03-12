"""Tests for mitty.practice.evaluator — hybrid answer evaluation.

Covers: exact-match MC, case-insensitive MC, fill-in-blank exact + LLM fallback,
LLM-scored short answer / explanation / worked example, cost optimization
(exact match never calls LLM), and misconception detection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mitty.practice.evaluator import (
    EvaluationResult,
    PracticeItem,
    _LLMEvaluation,
    evaluate_answer,
)

# ---------------------------------------------------------------------------
# Helpers — build PracticeItem fixtures
# ---------------------------------------------------------------------------


def _mc_item(correct: str = "B", options: list[str] | None = None) -> PracticeItem:
    return PracticeItem(
        practice_type="multiple_choice",
        question_text="What is 2+2?",
        correct_answer=correct,
        options_json=options or ["A) 3", "B) 4", "C) 5", "D) 6"],
        concept="arithmetic",
    )


def _fill_blank_item(correct: str = "mitochondria") -> PracticeItem:
    return PracticeItem(
        practice_type="fill_in_blank",
        question_text="The ___ is the powerhouse of the cell.",
        correct_answer=correct,
        concept="cell biology",
    )


def _short_answer_item() -> PracticeItem:
    return PracticeItem(
        practice_type="short_answer",
        question_text="Explain the water cycle briefly.",
        correct_answer=("Water evaporates, condenses into clouds, and precipitates."),
        concept="water cycle",
    )


def _explanation_item() -> PracticeItem:
    return PracticeItem(
        practice_type="explanation",
        question_text="Explain why the sky is blue.",
        correct_answer=(
            "Rayleigh scattering causes shorter blue wavelengths to scatter more."
        ),
        concept="optics",
    )


def _worked_example_item() -> PracticeItem:
    return PracticeItem(
        practice_type="worked_example",
        question_text="Solve: 3x + 5 = 20",
        correct_answer="x = 5",
        explanation=("Subtract 5 from both sides: 3x = 15. Divide by 3: x = 5."),
        concept="linear equations",
    )


def _mock_llm_evaluation(
    *,
    is_correct: bool = True,
    score: float = 1.0,
    feedback: str = "Good answer.",
    misconceptions: list[str] | None = None,
) -> _LLMEvaluation:
    return _LLMEvaluation(
        is_correct=is_correct,
        score=score,
        feedback=feedback,
        misconceptions_detected=misconceptions or [],
    )


# ---------------------------------------------------------------------------
# Multiple choice — exact match, no LLM needed
# ---------------------------------------------------------------------------


class TestMcExactMatchCorrect:
    """MC correct answer returns is_correct=True, score=1.0."""

    async def test_mc_exact_match_correct(self) -> None:
        item = _mc_item(correct="B")
        result = await evaluate_answer(
            ai_client=None, practice_item=item, student_answer="B"
        )

        assert isinstance(result, EvaluationResult)
        assert result.is_correct is True
        assert result.score == 1.0
        assert result.feedback  # non-empty feedback
        assert result.misconceptions_detected == []


class TestMcExactMatchIncorrect:
    """MC wrong answer returns is_correct=False, score=0.0."""

    async def test_mc_exact_match_incorrect(self) -> None:
        item = _mc_item(correct="B")
        result = await evaluate_answer(
            ai_client=None,
            practice_item=item,
            student_answer="C",
        )

        assert result.is_correct is False
        assert result.score == 0.0
        assert result.feedback  # should explain the correct answer


class TestMcCaseInsensitive:
    """MC match should be case-insensitive and strip whitespace."""

    async def test_mc_case_insensitive(self) -> None:
        item = _mc_item(correct="B")
        result = await evaluate_answer(
            ai_client=None,
            practice_item=item,
            student_answer="  b  ",
        )

        assert result.is_correct is True
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# Fill-in-blank — exact match first, LLM fallback
# ---------------------------------------------------------------------------


class TestFillInBlankExactMatch:
    """Fill-in-blank exact match (case-insensitive) without LLM."""

    async def test_fill_in_blank_exact_match(self) -> None:
        item = _fill_blank_item(correct="mitochondria")
        result = await evaluate_answer(
            ai_client=None,
            practice_item=item,
            student_answer="Mitochondria",
        )

        assert result.is_correct is True
        assert result.score == 1.0


class TestFillInBlankLlmFallbackForVariation:
    """Fill-in-blank falls back to LLM when exact match fails."""

    async def test_fill_in_blank_llm_fallback_for_variation(
        self,
    ) -> None:
        item = _fill_blank_item(correct="mitochondria")
        mock_client = AsyncMock()

        llm_eval = _mock_llm_evaluation(
            is_correct=True,
            score=1.0,
            feedback=("'Mitochondrion' is the singular form and is acceptable."),
        )
        mock_client.call_structured = AsyncMock(return_value=llm_eval)

        result = await evaluate_answer(
            ai_client=mock_client,
            practice_item=item,
            student_answer="mitochondrion",
        )

        assert result.is_correct is True
        assert result.score == 1.0
        mock_client.call_structured.assert_called_once()


# ---------------------------------------------------------------------------
# Short answer — LLM scores with partial credit (0.0-1.0)
# ---------------------------------------------------------------------------


class TestShortAnswerLlmPartialCredit:
    """Short answer uses LLM and supports partial credit scores."""

    async def test_short_answer_llm_partial_credit(self) -> None:
        item = _short_answer_item()
        mock_client = AsyncMock()

        llm_eval = _mock_llm_evaluation(
            is_correct=False,
            score=0.6,
            feedback=("You mentioned evaporation but missed condensation."),
            misconceptions=["Precipitation and condensation are the same"],
        )
        mock_client.call_structured = AsyncMock(return_value=llm_eval)

        result = await evaluate_answer(
            ai_client=mock_client,
            practice_item=item,
            student_answer="Water goes up and comes down as rain.",
        )

        assert result.is_correct is False
        assert result.score == pytest.approx(0.6)
        assert "condensation" in result.feedback.lower()
        mock_client.call_structured.assert_called_once()


# ---------------------------------------------------------------------------
# Explanation — LLM assesses completeness, accuracy, depth
# ---------------------------------------------------------------------------


class TestExplanationLlmScoringWithRubric:
    """Explanation type uses LLM with rubric-based scoring."""

    async def test_explanation_llm_scoring_with_rubric(self) -> None:
        item = _explanation_item()
        mock_client = AsyncMock()

        llm_eval = _mock_llm_evaluation(
            is_correct=True,
            score=0.85,
            feedback=(
                "Good explanation covering Rayleigh scattering."
                " Could elaborate on wavelength dependence."
            ),
        )
        mock_client.call_structured = AsyncMock(return_value=llm_eval)

        result = await evaluate_answer(
            ai_client=mock_client,
            practice_item=item,
            student_answer=("Blue light scatters more because of Rayleigh scattering."),
        )

        assert result.is_correct is True
        assert 0.0 <= result.score <= 1.0
        assert result.score == pytest.approx(0.85)
        mock_client.call_structured.assert_called_once()


# ---------------------------------------------------------------------------
# Worked example — LLM checks method + answer correctness
# ---------------------------------------------------------------------------


class TestWorkedExampleLlmMethodCheck:
    """Worked example uses LLM to check method and final answer."""

    async def test_worked_example_llm_method_check(self) -> None:
        item = _worked_example_item()
        mock_client = AsyncMock()

        llm_eval = _mock_llm_evaluation(
            is_correct=True,
            score=0.9,
            feedback=(
                "Correct answer. Method is valid but could "
                "show more intermediate steps."
            ),
        )
        mock_client.call_structured = AsyncMock(return_value=llm_eval)

        result = await evaluate_answer(
            ai_client=mock_client,
            practice_item=item,
            student_answer="3x = 15, x = 5",
        )

        assert result.is_correct is True
        assert result.score == pytest.approx(0.9)
        mock_client.call_structured.assert_called_once()


# ---------------------------------------------------------------------------
# Cost optimization — exact-match path never calls LLM
# ---------------------------------------------------------------------------


class TestExactMatchNeverCallsLlm:
    """MC and fill-in-blank exact matches never invoke the LLM."""

    async def test_exact_match_never_calls_llm(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_structured = AsyncMock()

        # MC exact match
        mc = _mc_item(correct="A")
        await evaluate_answer(
            ai_client=mock_client,
            practice_item=mc,
            student_answer="A",
        )

        # Fill-in-blank exact match
        fib = _fill_blank_item(correct="mitochondria")
        await evaluate_answer(
            ai_client=mock_client,
            practice_item=fib,
            student_answer="mitochondria",
        )

        mock_client.call_structured.assert_not_called()


# ---------------------------------------------------------------------------
# Misconception detection
# ---------------------------------------------------------------------------


class TestMisconceptionDetectionReturned:
    """LLM-detected misconceptions are propagated in the result."""

    async def test_misconception_detection_returned(self) -> None:
        item = _short_answer_item()
        mock_client = AsyncMock()

        misconceptions = [
            "Confuses evaporation with boiling",
            "Thinks rain comes from rivers",
        ]
        llm_eval = _mock_llm_evaluation(
            is_correct=False,
            score=0.3,
            feedback="Several misconceptions detected.",
            misconceptions=misconceptions,
        )
        mock_client.call_structured = AsyncMock(return_value=llm_eval)

        result = await evaluate_answer(
            ai_client=mock_client,
            practice_item=item,
            student_answer="Water boils up from rivers.",
        )

        assert result.misconceptions_detected == misconceptions
        assert len(result.misconceptions_detected) == 2
