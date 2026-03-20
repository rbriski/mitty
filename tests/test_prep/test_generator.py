"""Tests for mitty.prep.generator — LLM problem generation for test prep.

Covers: multiple choice, free response, worked example, difficulty scaling,
graceful degradation when AI is unavailable.

Traces: DEC-001, DEC-011.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mitty.ai.errors import AIClientError
from mitty.prep.generator import (
    PROBLEM_TYPES,
    GeneratedProblem,
    ProblemType,
    generate_problem,
)

# ---------------------------------------------------------------------------
# Mock AI client helpers
# ---------------------------------------------------------------------------


def _build_mock_ai_client(response: GeneratedProblem) -> AsyncMock:
    """Build a mock AIClient that returns a predetermined structured response."""
    ai = AsyncMock()
    ai.call_structured = AsyncMock(return_value=response)
    ai._model = "claude-sonnet-4-20250514"
    return ai


def _build_failing_ai_client(exc: Exception) -> AsyncMock:
    """Build a mock AIClient whose call_structured raises *exc*."""
    ai = AsyncMock()
    ai.call_structured = AsyncMock(side_effect=exc)
    ai._model = "claude-sonnet-4-20250514"
    return ai


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProblemTypeEnum:
    """ProblemType enum has all 8 required types (6 original + 2 US-010)."""

    def test_all_eight_types_present(self) -> None:
        assert len(ProblemType) == 8
        expected = {
            "multiple_choice",
            "free_response",
            "worked_example",
            "error_analysis",
            "find_the_mistake",
            "review_own_errors",
            "mixed",
            "calibration",
        }
        assert {t.value for t in ProblemType} == expected

    def test_problem_types_list_matches_enum(self) -> None:
        assert set(PROBLEM_TYPES) == {t.value for t in ProblemType}


class TestMultipleChoice:
    """generate_problem produces MC problem with 4 choices."""

    async def test_multiple_choice(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Divide 2x^3 + 3x^2 - x + 5 by x - 2 using long division.",
            choices=[
                "2x^2 + 7x + 13, R31",
                "2x^2 + 7x + 13, R27",
                "2x^2 - x + 1, R3",
                "x^2 + 5x + 9, R23",
            ],
            correct_answer="2x^2 + 7x + 13, R31",
            explanation="Using synthetic division, bring down 2, multiply...",
            hint="Start by dividing the leading terms.",
        )
        ai_client = _build_mock_ai_client(mock_response)

        result = await generate_problem(
            concept="polynomial long division",
            difficulty=0.6,
            problem_type="multiple_choice",
            ai_client=ai_client,
        )

        assert result["type"] == "multiple_choice"
        assert result["concept"] == "polynomial long division"
        assert result["difficulty"] == 0.6
        assert result["prompt"] is not None
        assert len(result["prompt"]) > 0
        assert result["choices"] is not None
        assert len(result["choices"]) == 4
        assert result["correct_answer"] is not None
        assert result["explanation"] is not None
        assert result["hint"] is not None

        # Verify AI was called with correct role
        ai_client.call_structured.assert_called_once()
        call_kwargs = ai_client.call_structured.call_args.kwargs
        assert call_kwargs["role"] == "problem_generator"


class TestFreeResponse:
    """generate_problem produces free response with expected answer."""

    async def test_free_response(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Find all zeros of f(x) = x^3 - 6x^2 + 11x - 6.",
            choices=None,
            correct_answer="x = 1, x = 2, x = 3",
            explanation="Factor by testing rational roots...",
            hint="Try using the Rational Root Theorem.",
        )
        ai_client = _build_mock_ai_client(mock_response)

        result = await generate_problem(
            concept="finding zeros of polynomials",
            difficulty=0.5,
            problem_type="free_response",
            ai_client=ai_client,
        )

        assert result["type"] == "free_response"
        assert result["concept"] == "finding zeros of polynomials"
        assert result["difficulty"] == 0.5
        assert result["prompt"] is not None
        assert len(result["prompt"]) > 0
        assert result["correct_answer"] is not None
        assert result["choices"] is None
        assert result["explanation"] is not None


class TestWorkedExample:
    """generate_problem produces step-by-step solution."""

    async def test_worked_example(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Solve: lim(x->2) (x^2 - 4)/(x - 2)",
            choices=None,
            correct_answer="4",
            explanation=(
                "Step 1: Factor numerator as (x+2)(x-2). "
                "Step 2: Cancel (x-2). "
                "Step 3: Evaluate x+2 at x=2 to get 4."
            ),
            hint="Factor the numerator first.",
        )
        ai_client = _build_mock_ai_client(mock_response)

        result = await generate_problem(
            concept="limits",
            difficulty=0.3,
            problem_type="worked_example",
            ai_client=ai_client,
        )

        assert result["type"] == "worked_example"
        assert result["concept"] == "limits"
        assert result["prompt"] is not None
        assert result["correct_answer"] is not None
        assert result["explanation"] is not None
        # Worked example should have multi-step explanation
        assert len(result["explanation"]) > 20


class TestDifficultyScaling:
    """Harder difficulty produces harder content in the prompt."""

    async def test_difficulty_scaling(self) -> None:
        from mitty.prep.generator import GeneratedProblem

        easy_response = GeneratedProblem(
            prompt="What is sin(0)?",
            choices=None,
            correct_answer="0",
            explanation="sin(0) = 0 by definition.",
            hint="Recall the unit circle at angle 0.",
        )
        hard_response = GeneratedProblem(
            prompt="Prove that lim(x->0) sin(x)/x = 1 using the squeeze theorem.",
            choices=None,
            correct_answer="Apply cos(x) <= sin(x)/x <= 1 and squeeze...",
            explanation="By geometry, cos(x) <= sin(x)/x <= 1 for x near 0...",
            hint="Start with the unit circle inequality cos(x) <= sin(x)/x <= 1.",
        )

        easy_ai = _build_mock_ai_client(easy_response)
        hard_ai = _build_mock_ai_client(hard_response)

        easy_result = await generate_problem(
            concept="trigonometric functions",
            difficulty=0.1,
            problem_type="free_response",
            ai_client=easy_ai,
        )
        hard_result = await generate_problem(
            concept="trigonometric functions",
            difficulty=0.9,
            problem_type="free_response",
            ai_client=hard_ai,
        )

        # Verify both calls include correct difficulty in the prompt
        easy_call = easy_ai.call_structured.call_args.kwargs
        hard_call = hard_ai.call_structured.call_args.kwargs

        assert "0.1" in easy_call["user_prompt"]
        assert "0.9" in hard_call["user_prompt"]

        # Difficulty labels in the prompt differ
        assert "beginner" in easy_call["user_prompt"].lower()
        assert "advanced" in hard_call["user_prompt"].lower()

        # Both return valid results
        assert easy_result["difficulty"] == 0.1
        assert hard_result["difficulty"] == 0.9


class TestAiUnavailable:
    """Returns fallback problem when AI fails (graceful degradation)."""

    async def test_ai_unavailable(self) -> None:
        ai_client = _build_failing_ai_client(
            AIClientError("Service unavailable", status_code=503)
        )

        result = await generate_problem(
            concept="polynomial long division",
            difficulty=0.5,
            problem_type="multiple_choice",
            ai_client=ai_client,
        )

        # Should return a valid fallback problem, not raise
        assert result["type"] == "multiple_choice"
        assert result["concept"] == "polynomial long division"
        assert result["difficulty"] == 0.5
        assert result["prompt"] is not None
        assert len(result["prompt"]) > 0
        assert result["correct_answer"] is not None
        assert result["is_fallback"] is True

    async def test_ai_unavailable_free_response(self) -> None:
        ai_client = _build_failing_ai_client(
            AIClientError("Rate limited", status_code=429)
        )

        result = await generate_problem(
            concept="limits",
            difficulty=0.7,
            problem_type="free_response",
            ai_client=ai_client,
        )

        assert result["type"] == "free_response"
        assert result["concept"] == "limits"
        assert result["is_fallback"] is True
        assert result["choices"] is None

    async def test_ai_unavailable_generic_exception(self) -> None:
        """Even unexpected exceptions produce a fallback."""
        ai_client = _build_failing_ai_client(RuntimeError("unexpected"))

        result = await generate_problem(
            concept="derivatives",
            difficulty=0.4,
            problem_type="worked_example",
            ai_client=ai_client,
        )

        assert result["type"] == "worked_example"
        assert result["is_fallback"] is True


class TestPromptContent:
    """The prompt sent to AI references Sullivan Pre-Calculus and uses templates."""

    async def test_prompt_references_sullivan(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Test",
            choices=None,
            correct_answer="Test",
            explanation="Test",
            hint="Test",
        )
        ai_client = _build_mock_ai_client(mock_response)

        await generate_problem(
            concept="polynomial long division",
            difficulty=0.5,
            problem_type="free_response",
            ai_client=ai_client,
        )

        call_kwargs = ai_client.call_structured.call_args.kwargs
        system = call_kwargs["system"]
        # DEC-011: prompt references Sullivan Pre-Calculus
        assert "Sullivan" in system

    async def test_user_prompt_uses_wrap_user_input(self) -> None:
        """Student context (concept) is wrapped via wrap_user_input pattern."""
        mock_response = GeneratedProblem(
            prompt="Test",
            choices=None,
            correct_answer="Test",
            explanation="Test",
            hint="Test",
        )
        ai_client = _build_mock_ai_client(mock_response)

        await generate_problem(
            concept="polynomial long division",
            difficulty=0.5,
            problem_type="free_response",
            ai_client=ai_client,
            student_context="I struggle with long division steps",
        )

        call_kwargs = ai_client.call_structured.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        # Student context should be wrapped in <user_input> tags
        assert "<user_input>" in user_prompt
        assert "</user_input>" in user_prompt
        assert "I struggle with long division steps" in user_prompt


class TestDifficultyValidation:
    """Difficulty must be a float between 0.0 and 1.0."""

    async def test_difficulty_clamped_low(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Test",
            choices=None,
            correct_answer="Test",
            explanation="Test",
            hint="Test",
        )
        ai_client = _build_mock_ai_client(mock_response)

        result = await generate_problem(
            concept="test",
            difficulty=-0.5,
            problem_type="free_response",
            ai_client=ai_client,
        )
        assert result["difficulty"] == 0.0

    async def test_difficulty_clamped_high(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Test",
            choices=None,
            correct_answer="Test",
            explanation="Test",
            hint="Test",
        )
        ai_client = _build_mock_ai_client(mock_response)

        result = await generate_problem(
            concept="test",
            difficulty=1.5,
            problem_type="free_response",
            ai_client=ai_client,
        )
        assert result["difficulty"] == 1.0

    async def test_invalid_problem_type_raises(self) -> None:
        mock_response = GeneratedProblem(
            prompt="Test",
            choices=None,
            correct_answer="Test",
            explanation="Test",
            hint="Test",
        )
        ai_client = _build_mock_ai_client(mock_response)

        with pytest.raises(ValueError, match="Invalid problem type"):
            await generate_problem(
                concept="test",
                difficulty=0.5,
                problem_type="invalid_type",
                ai_client=ai_client,
            )
