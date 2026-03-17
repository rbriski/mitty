"""Hybrid answer evaluator — exact-match for MC/fill-in-blank, LLM for free-text.

Provides ``evaluate_answer()`` which takes a practice item and student answer,
returns an ``EvaluationResult`` with score, feedback, and detected misconceptions.

Cost optimization: exact-match paths (MC, fill-in-blank with matching text) never
invoke the LLM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mitty.ai.client import AIClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PracticeItem(BaseModel):
    """Minimal representation of a practice item for evaluation.

    Mirrors the relevant columns from ``practice_items`` table.
    """

    practice_type: str
    question_text: str
    correct_answer: str | None = None
    options_json: list | dict | None = None
    explanation: str | None = None
    concept: str = ""


class EvaluationResult(BaseModel):
    """Result of evaluating a student answer.

    Attributes:
        is_correct: Whether the answer is considered correct.
        score: Numeric score between 0.0 and 1.0 (supports partial credit).
        feedback: Human-readable feedback explaining the evaluation.
        misconceptions_detected: List of identified misconceptions, if any.
    """

    is_correct: bool
    score: float = Field(ge=0.0, le=1.0)
    feedback: str
    misconceptions_detected: list[str] = Field(default_factory=list)


class _LLMEvaluation(BaseModel):
    """Structured response model for LLM-based evaluation.

    Used as the response_model for ``AIClient.call_structured()``.
    """

    is_correct: bool
    score: float = Field(ge=0.0, le=1.0)
    feedback: str
    misconceptions_detected: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Exact-match helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase and strip whitespace for comparison."""
    return text.strip().lower()


def _exact_match(student: str, correct: str) -> bool:
    """Case-insensitive, whitespace-trimmed equality check."""
    return _normalize(student) == _normalize(correct)


# ---------------------------------------------------------------------------
# LLM evaluation prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = """\
You are an expert educational assessor evaluating a student's answer.
Score on a 0.0-1.0 scale. Identify any misconceptions.
Be encouraging but accurate. Provide specific, actionable feedback."""

_FILL_IN_BLANK_PROMPT = """\
Practice type: Fill-in-the-blank
Question: {question}
Correct answer: {correct}
Student answer: {student}
Concept: {concept}

The student's answer did not exactly match the expected answer.
Determine if the student's answer is a reasonable variation (e.g., singular/plural,
synonym, alternate spelling) of the correct answer.
Score 1.0 if acceptable, 0.0 if wrong."""

_SHORT_ANSWER_PROMPT = """\
Practice type: Short answer
Question: {question}
Expected answer: {correct}
Student answer: {student}
Concept: {concept}

Evaluate the student's short answer against the expected answer.
Award partial credit (0.0-1.0) based on accuracy and completeness.
Identify any misconceptions in the student's reasoning."""

_EXPLANATION_PROMPT = """\
Practice type: Explanation
Question: {question}
Reference answer: {correct}
Student answer: {student}
Concept: {concept}

Evaluate the student's explanation for:
1. Completeness — does it cover the key points?
2. Accuracy — are the statements factually correct?
3. Depth — does it demonstrate understanding beyond surface level?
Award a score from 0.0 to 1.0. Identify any misconceptions."""

_WORKED_EXAMPLE_PROMPT = """\
Practice type: Worked example
Problem: {question}
Correct solution: {correct}
Reference method: {explanation}
Student work: {student}
Concept: {concept}

Evaluate the student's worked example for:
1. Method correctness — is the approach valid?
2. Answer correctness — is the final answer right?
3. Work shown — are intermediate steps clear and correct?
Award a score from 0.0 to 1.0. Identify any misconceptions."""

_PROMPT_MAP: dict[str, str] = {
    "fill_in_blank": _FILL_IN_BLANK_PROMPT,
    "short_answer": _SHORT_ANSWER_PROMPT,
    "explanation": _EXPLANATION_PROMPT,
    "worked_example": _WORKED_EXAMPLE_PROMPT,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def evaluate_answer(
    ai_client: AIClient | None,
    practice_item: PracticeItem,
    student_answer: str,
) -> EvaluationResult:
    """Evaluate a student's answer against a practice item.

    Uses exact matching for multiple-choice and fill-in-blank types
    (when the answer matches). Falls back to LLM evaluation for
    free-text types and non-matching fill-in-blank answers.

    Args:
        ai_client: AIClient instance for LLM calls. May be None for
            practice types that only need exact matching.
        practice_item: The practice item being answered.
        student_answer: The student's submitted answer.

    Returns:
        EvaluationResult with score, feedback, and any misconceptions.
    """
    ptype = practice_item.practice_type
    correct = practice_item.correct_answer or ""

    # --- Multiple choice: always exact match ---
    if ptype == "multiple_choice":
        return _evaluate_mc(correct, student_answer, practice_item.options_json)

    # --- Fill-in-blank: exact match first, LLM fallback ---
    if ptype == "fill_in_blank":
        if _exact_match(student_answer, correct):
            return EvaluationResult(
                is_correct=True,
                score=1.0,
                feedback="Correct!",
                misconceptions_detected=[],
            )
        # Fallback to LLM for reasonable variations
        return await _evaluate_with_llm(ai_client, practice_item, student_answer)

    # --- Flashcard: self-assessment (no LLM needed) ---
    if ptype == "flashcard":
        return _evaluate_flashcard_self_assessment(student_answer)

    # --- All other types: LLM evaluation ---
    return await _evaluate_with_llm(ai_client, practice_item, student_answer)


# ---------------------------------------------------------------------------
# Internal evaluators
# ---------------------------------------------------------------------------


def _resolve_mc_answer(
    correct: str,
    options: list | dict | None,
) -> str:
    """Resolve a letter-based MC answer (A/B/C/D) to the actual option text.

    The LLM sometimes stores "C" instead of the full option text. When
    options_json is a list, map A→0, B→1, C→2, D→3 to get the real text.
    If correct is already the full text or options aren't available, return as-is.
    """
    if not options or not isinstance(options, list):
        return correct

    normalized = correct.strip().upper()
    # Handle "A", "B", "C", "D" or "A.", "B.", etc.
    letter = normalized.rstrip(".)").strip()
    if len(letter) == 1 and letter in "ABCDEFGH":
        idx = ord(letter) - ord("A")
        if 0 <= idx < len(options):
            return str(options[idx])

    return correct


def _evaluate_mc(
    correct: str,
    student_answer: str,
    options: list | dict | None = None,
) -> EvaluationResult:
    """Evaluate a multiple-choice answer via exact match.

    Handles the case where correct_answer is a letter (A/B/C/D) but the
    student sends the full option text (from the UI), or vice versa.
    """
    # Direct match first (both letters, or both full text).
    if _exact_match(student_answer, correct):
        return EvaluationResult(
            is_correct=True,
            score=1.0,
            feedback="Correct!",
            misconceptions_detected=[],
        )

    # Try resolving letter→text or text→letter to handle mismatches.
    if options and isinstance(options, list):
        resolved_correct = _resolve_mc_answer(correct, options)
        resolved_student = _resolve_mc_answer(student_answer, options)
        if _exact_match(resolved_student, resolved_correct):
            return EvaluationResult(
                is_correct=True,
                score=1.0,
                feedback="Correct!",
                misconceptions_detected=[],
            )
        # Use the resolved text for feedback.
        correct = resolved_correct

    return EvaluationResult(
        is_correct=False,
        score=0.0,
        feedback=f"Incorrect. The correct answer is {correct}.",
        misconceptions_detected=[],
    )


# Flashcard self-assessment values sent by the UI.
_FLASHCARD_SCORES: dict[str, tuple[bool, float, str]] = {
    "correct": (True, 1.0, "You knew this one!"),
    "partial": (False, 0.5, "Partial recall. Review this concept again soon."),
    "incorrect": (False, 0.0, "Keep studying. You'll get it next time."),
}


def _evaluate_flashcard_self_assessment(student_answer: str) -> EvaluationResult:
    """Convert a flashcard self-assessment to a result.

    Flashcards use self-reported knowledge rather than LLM evaluation.
    The student clicks 'Knew it', 'Partially', or 'Didn't know', which
    the UI sends as 'correct', 'partial', or 'incorrect' respectively.
    """
    key = student_answer.strip().lower()
    is_correct, score, feedback = _FLASHCARD_SCORES.get(
        key,
        (False, 0.0, "Unrecognized self-assessment."),
    )
    return EvaluationResult(
        is_correct=is_correct,
        score=score,
        feedback=feedback,
        misconceptions_detected=[],
    )


async def _evaluate_with_llm(
    ai_client: AIClient | None,
    practice_item: PracticeItem,
    student_answer: str,
) -> EvaluationResult:
    """Evaluate using the LLM for free-text practice types.

    Raises:
        ValueError: If ai_client is None when LLM evaluation is needed.
    """
    if ai_client is None:
        msg = "AIClient is required for LLM-based evaluation."
        raise ValueError(msg)

    ptype = practice_item.practice_type
    template = _PROMPT_MAP.get(ptype, _SHORT_ANSWER_PROMPT)

    # Use sequential .replace() instead of .format() to avoid
    # KeyError/ValueError when user-provided text (student answers,
    # LLM-generated questions) contains curly braces — e.g., math
    # notation like "f{x}" or set notation "{1, 2, 3}".
    #
    # Local templates use plain {student} (no XML wrapper), so we call
    # wrap_user_input() to sanitise and wrap the student text (DEC-007).
    from mitty.ai.prompts import wrap_user_input

    user_prompt = (
        template.replace("{question}", practice_item.question_text)
        .replace("{correct}", practice_item.correct_answer or "(no reference answer)")
        .replace("{student}", wrap_user_input(student_answer))
        .replace("{concept}", practice_item.concept)
        .replace("{explanation}", practice_item.explanation or "(none provided)")
    )

    logger.info(
        "LLM evaluation: type=%s concept=%s",
        ptype,
        practice_item.concept,
    )

    llm_result = await ai_client.call_structured(
        system=_SYSTEM_PROMPT_BASE,
        user_prompt=user_prompt,
        response_model=_LLMEvaluation,
    )

    return EvaluationResult(
        is_correct=llm_result.is_correct,
        score=llm_result.score,
        feedback=llm_result.feedback,
        misconceptions_detected=llm_result.misconceptions_detected,
    )


# ---------------------------------------------------------------------------
# Vision-based evaluation (camera/photo input)
# ---------------------------------------------------------------------------

_VISION_EVAL_PROMPT = """\
You are evaluating a student's handwritten answer to a math problem.

**Question:** {question}
**Correct answer:** {correct}
**Concept:** {concept}
**Explanation/solution:** {explanation}

The student submitted a photo of their work. Read the handwritten work carefully.

Evaluate:
1. Is the final answer correct?
2. Is the method/approach correct?
3. Are intermediate steps shown and correct?
4. Are there any errors in arithmetic, sign, or procedure?

Award a score from 0.0 to 1.0:
- 1.0 = correct answer with valid work shown
- 0.7-0.9 = correct approach but minor errors (arithmetic, sign)
- 0.4-0.6 = partially correct approach or method
- 0.1-0.3 = some relevant work but fundamentally wrong
- 0.0 = blank, irrelevant, or completely wrong

Be encouraging but accurate. Reference specific parts of their work in feedback."""


async def evaluate_answer_with_image(
    ai_client: AIClient,
    practice_item: PracticeItem,
    image_bytes: bytes,
    student_text: str = "",
) -> EvaluationResult:
    """Evaluate a student's answer from a photo of handwritten work.

    Uses Claude Vision to read handwritten math and evaluate correctness.

    Args:
        ai_client: AIClient instance (required — vision always uses LLM).
        practice_item: The practice item being answered.
        image_bytes: Raw JPEG/PNG bytes of the student's work.
        student_text: Optional text the student typed alongside the photo.

    Returns:
        EvaluationResult with score, feedback, and any misconceptions.
    """
    from mitty.ai.prompts import wrap_user_input

    user_prompt = (
        _VISION_EVAL_PROMPT.replace("{question}", practice_item.question_text)
        .replace("{correct}", practice_item.correct_answer or "(no reference answer)")
        .replace("{concept}", practice_item.concept)
        .replace("{explanation}", practice_item.explanation or "(none provided)")
    )

    if student_text.strip():
        user_prompt += f"\n\nThe student also typed: {wrap_user_input(student_text)}"

    logger.info(
        "Vision evaluation: concept=%s",
        practice_item.concept,
    )

    llm_result = await ai_client.call_vision(
        images=[image_bytes],
        system=_SYSTEM_PROMPT_BASE,
        user_prompt=user_prompt,
        response_model=_LLMEvaluation,
        call_type="vision_eval",
    )

    return EvaluationResult(
        is_correct=llm_result.is_correct,
        score=llm_result.score,
        feedback=llm_result.feedback,
        misconceptions_detected=llm_result.misconceptions_detected,
    )
