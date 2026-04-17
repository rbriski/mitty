"""LLM-powered math problem generator for test prep.

Generates problems at a target difficulty for a given concept using Claude.
Eight problem types are supported: multiple choice, free response, worked
example, error analysis, find the mistake, review own errors, mixed, and
calibration.  Prompts reference Sullivan & Sullivan Pre-Calculus 11th
Edition for notation and style (DEC-011).

Graceful degradation: if the AI client is unavailable, a simple fallback
problem is returned so the student is never blocked.

Traces: DEC-001 (structured AI output), DEC-011 (Sullivan style),
        US-010 (error analysis enhancements, R6 desirable difficulty).

Public API:
    generate_problem(concept, difficulty, problem_type, ai_client, ...) -> dict
    build_review_own_errors(wrong_answer) -> dict
"""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from mitty.ai.prompts import get_prompt, wrap_user_input

if TYPE_CHECKING:
    from mitty.ai.client import AIClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Problem type enum
# ---------------------------------------------------------------------------


class ProblemType(enum.StrEnum):
    """Supported problem types for test prep generation."""

    multiple_choice = "multiple_choice"
    free_response = "free_response"
    worked_example = "worked_example"
    error_analysis = "error_analysis"
    find_the_mistake = "find_the_mistake"
    review_own_errors = "review_own_errors"
    mixed = "mixed"
    calibration = "calibration"


PROBLEM_TYPES: list[str] = [t.value for t in ProblemType]


# ---------------------------------------------------------------------------
# Pydantic model for structured LLM output (DEC-001)
# ---------------------------------------------------------------------------


class GeneratedProblem(BaseModel):
    """Structured problem returned by the LLM via tool-use."""

    prompt: str = Field(
        description="The problem statement presented to the student.",
        max_length=10000,
    )
    choices: list[str] | None = Field(
        default=None,
        description=(
            "For multiple_choice: list of exactly 4 answer options. "
            "Null for other problem types."
        ),
    )
    correct_answer: str = Field(
        description="The correct answer or expected response.",
        max_length=10000,
    )
    explanation: str = Field(
        description=(
            "Explanation of the solution method. For worked_example, "
            "include detailed step-by-step reasoning."
        ),
        max_length=10000,
    )
    hint: str = Field(
        description="A hint that guides the student without giving the answer.",
        max_length=5000,
    )


# ---------------------------------------------------------------------------
# Difficulty label helper
# ---------------------------------------------------------------------------

_DIFFICULTY_LABELS: list[tuple[float, str]] = [
    (0.3, "beginner"),
    (0.6, "intermediate"),
    (1.0, "advanced"),
]


def _difficulty_label(difficulty: float) -> str:
    """Map a 0.0-1.0 difficulty float to a human-readable label."""
    for threshold, label in _DIFFICULTY_LABELS:
        if difficulty <= threshold:
            return label
    return "advanced"


# ---------------------------------------------------------------------------
# Fallback problem (graceful degradation)
# ---------------------------------------------------------------------------


def _fallback_problem(
    concept: str,
    difficulty: float,
    problem_type: str,
) -> dict:
    """Return a simple fallback problem when AI is unavailable.

    The fallback is intentionally generic -- it keeps the student moving
    rather than blocking on an AI outage.
    """
    base: dict = {
        "type": problem_type,
        "concept": concept,
        "difficulty": difficulty,
        "prompt": (
            f"Review the concept of {concept}. "
            "Write a brief summary of the key ideas and work through "
            "a practice problem from your textbook "
            "(Sullivan Pre-Calculus 11e)."
        ),
        "choices": None,
        "correct_answer": ("Refer to your textbook for the complete solution."),
        "explanation": (
            "This is a fallback problem generated because the AI service "
            "was temporarily unavailable. Please review your textbook or "
            "class notes for detailed examples."
        ),
        "hint": f"Start by reviewing the definition of {concept}.",
        "is_fallback": True,
    }
    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_problem(
    *,
    concept: str,
    difficulty: float,
    problem_type: str,
    ai_client: AIClient,
    student_context: str | None = None,
    user_id: str | None = None,
    supabase_client: object | None = None,
) -> dict:
    """Generate a single math problem at *difficulty* for *concept*.

    Args:
        concept: The math concept/topic (e.g. "polynomial long division").
        difficulty: Target difficulty as a float 0.0-1.0.
        problem_type: One of the eight ``ProblemType`` values.
        ai_client: ``AIClient`` instance for Claude API calls.
        student_context: Optional student-provided context (wrapped via
            ``wrap_user_input`` for injection defense).
        user_id: Optional user ID for audit logging.
        supabase_client: Optional Supabase client for audit logging.

    Returns:
        A dict with keys: type, concept, difficulty, prompt, choices,
        correct_answer, explanation, hint. If AI fails, includes
        ``is_fallback: True``.

    Raises:
        ValueError: If *problem_type* is not one of the valid types.
    """
    # Validate problem type
    if problem_type not in PROBLEM_TYPES:
        msg = f"Invalid problem type: {problem_type!r}. Must be one of: {PROBLEM_TYPES}"
        raise ValueError(msg)

    # Clamp difficulty to [0.0, 1.0]
    difficulty = max(0.0, min(1.0, difficulty))

    # Build the user prompt from the registered template
    prompt_config = get_prompt("problem_generator")

    # Format student context section
    context_section = ""
    if student_context:
        context_section = f"Student context: {wrap_user_input(student_context)}"

    user_prompt = (
        prompt_config.user_template.replace("{concept}", concept)
        .replace("{problem_type}", problem_type)
        .replace("{difficulty}", str(difficulty))
        .replace("{student_context}", context_section)
    )

    # Attempt AI generation with graceful degradation
    try:
        generated = await ai_client.call_structured(
            system=prompt_config.system_prompt,
            user_prompt=user_prompt,
            response_model=GeneratedProblem,
            role="problem_generator",
            user_id=user_id,
            call_type="problem_generation",
            supabase_client=supabase_client,
        )

        result: dict = {
            "type": problem_type,
            "concept": concept,
            "difficulty": difficulty,
            "prompt": generated.prompt,
            "choices": generated.choices,
            "correct_answer": generated.correct_answer,
            "explanation": generated.explanation,
            "hint": generated.hint,
        }

        logger.info(
            "Generated %s problem for concept=%r at difficulty=%.1f",
            problem_type,
            concept,
            difficulty,
        )
        return result

    except Exception:
        logger.warning(
            "AI unavailable for problem generation "
            "(concept=%r, type=%s, difficulty=%.1f), returning fallback",
            concept,
            problem_type,
            difficulty,
            exc_info=True,
        )
        return _fallback_problem(concept, difficulty, problem_type)


# ---------------------------------------------------------------------------
# Review-own-errors builder (US-010, R6 — desirable difficulty)
# ---------------------------------------------------------------------------


def build_review_own_errors(
    *,
    wrong_answer: dict,
) -> dict:
    """Build a review-own-errors reflection problem from a prior wrong answer.

    This is an *ungraded* reflection prompt: the student is shown their
    original wrong answer and asked to self-explain what went wrong.
    No LLM call is needed.

    Args:
        wrong_answer: A dict with keys from a ``test_prep_results`` row:
            concept, problem_json (with prompt, correct_answer, explanation),
            student_answer, feedback.

    Returns:
        A problem dict with ``type="review_own_errors"`` and ``is_reflection=True``.
    """
    pj = wrong_answer.get("problem_json", {})
    original_prompt = pj.get("prompt", "")
    original_correct = pj.get("correct_answer", "")
    original_explanation = pj.get("explanation", "")
    student_answer = wrong_answer.get("student_answer", "")
    concept = wrong_answer.get("concept", "unknown")
    feedback = wrong_answer.get("feedback", "")

    reflection_prompt = (
        "Review your earlier answer and reflect on what went wrong.\n\n"
        f"Original problem:\n{original_prompt}\n\n"
        f"Your answer: {student_answer}\n"
        f"Correct answer: {original_correct}"
    )
    if feedback:
        reflection_prompt += f"\nFeedback: {feedback}"

    reflection_prompt += (
        "\n\nIn the text box below, explain in your own words "
        "what mistake you made and how you would solve it correctly. "
        "This is an ungraded reflection — take your time."
    )

    return {
        "type": "review_own_errors",
        "concept": concept,
        "difficulty": wrong_answer.get("difficulty", 0.5),
        "prompt": reflection_prompt,
        "choices": None,
        "correct_answer": original_correct,
        "explanation": original_explanation,
        "hint": "Think about where your reasoning diverged from the correct approach.",
        "is_reflection": True,
    }
