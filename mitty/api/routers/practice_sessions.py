"""Practice session orchestration endpoints.

Stateless endpoints that combine generator, evaluator, and mastery updater:
- POST /study-blocks/{block_id}/practice/generate — generate practice items
- POST /practice-results/evaluate — evaluate a student answer
- POST /mastery-states/update-from-results — batch-update mastery after session

Graceful degradation: when the LLM is unavailable, generate falls back to
cached items and evaluate falls back to exact-match only.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_ai_client, get_user_client
from mitty.api.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    MasteryStateResult,
    MasteryUpdateRequest,
    MasteryUpdateResponse,
    PracticeGenerateResponse,
    PracticeItemResponse,
)
from mitty.mastery.updater import update_mastery
from mitty.practice.evaluator import PracticeItem as EvalPracticeItem
from mitty.practice.evaluator import evaluate_answer
from mitty.practice.generator import generate_practice_items

if TYPE_CHECKING:
    from supabase import AsyncClient

    from mitty.ai.client import AIClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["practice_sessions"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]
OptionalAI = Annotated["AIClient | None", Depends(get_ai_client)]


# ---------------------------------------------------------------------------
# POST /study-blocks/{block_id}/practice/generate
# ---------------------------------------------------------------------------


@router.post(
    "/study-blocks/{block_id}/practice/generate",
    response_model=PracticeGenerateResponse,
)
async def generate_practice(
    block_id: int,
    current_user: CurrentUser,
    client: UserClient,
    ai_client: OptionalAI,
) -> PracticeGenerateResponse:
    """Generate practice items for a study block.

    Fetches the block's concept (from assessment), retrieves resource chunks,
    calls the generator, and returns practice items. Falls back to cached
    items when the LLM is unavailable.
    """
    user_id = current_user["user_id"]

    # 1. Fetch block with plan-join for ownership verification.
    block = await _fetch_block_for_user(client, block_id, user_id)

    # 2. Derive concept and course_id from block.
    concept, course_id = await _derive_concept(client, block)
    if concept is None or course_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_CONCEPT",
                "message": (
                    "Cannot determine concept for this block. "
                    "Block must have an assessment with a unit_or_topic."
                ),
            },
        )

    # 3. Get current mastery level.
    mastery_level = await _get_mastery_level(client, user_id, course_id, concept)

    # 4. Fetch resource chunks for the course.
    resource_chunks = await _fetch_resource_chunks(client, course_id)

    # 5. Generate practice items (with fallback).
    from uuid import UUID

    uid = UUID(user_id)

    try:
        items = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=client,
            user_id=uid,
            course_id=course_id,
            concept=concept,
            mastery_level=mastery_level,
            resource_chunks=resource_chunks,
        )
        cached = False
    except Exception:
        logger.warning(
            "Practice generation failed for block=%d, falling back to cache",
            block_id,
            exc_info=True,
        )
        # Fallback: return cached items
        items_data = await _fetch_cached_items(client, user_id, course_id, concept)
        if not items_data:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "GENERATION_UNAVAILABLE",
                    "message": (
                        "Practice item generation is temporarily unavailable "
                        "and no cached items exist."
                    ),
                },
            ) from None
        return PracticeGenerateResponse(
            concept=concept,
            course_id=course_id,
            items=[PracticeItemResponse.model_validate(r) for r in items_data],
            cached=True,
        )

    # Convert dataclass items to response models.
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    item_responses = []
    for item in items:
        item_responses.append(
            PracticeItemResponse(
                id=item.id,
                user_id=uid,
                course_id=item.course_id,
                concept=item.concept,
                practice_type=item.practice_type,
                question_text=item.question_text,
                correct_answer=item.correct_answer,
                options_json=item.options_json,
                explanation=item.explanation,
                source_chunk_ids=item.source_chunk_ids,
                difficulty_level=item.difficulty_level,
                generation_model=item.generation_model,
                times_used=item.times_used,
                last_used_at=item.last_used_at,
                created_at=item.created_at or now,
            )
        )

    return PracticeGenerateResponse(
        concept=concept,
        course_id=course_id,
        items=item_responses,
        cached=cached,
    )


# ---------------------------------------------------------------------------
# POST /practice-results/evaluate
# ---------------------------------------------------------------------------


@router.post(
    "/practice-results/evaluate",
    response_model=EvaluateResponse,
)
async def evaluate_practice_answer(
    data: EvaluateRequest,
    current_user: CurrentUser,
    client: UserClient,
    ai_client: OptionalAI,
) -> EvaluateResponse:
    """Evaluate a student's answer for a practice item.

    Fetches the practice item, calls the evaluator, stores the practice
    result, and returns the evaluation. Falls back to exact-match only
    when the LLM is unavailable.
    """
    user_id = current_user["user_id"]

    # 1. Fetch the practice item.
    item_data = await _fetch_practice_item(client, data.practice_item_id, user_id)
    if item_data is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ITEM_NOT_FOUND",
                "message": "Practice item not found.",
            },
        )

    # 2. Build evaluator PracticeItem.
    eval_item = EvalPracticeItem(
        practice_type=item_data["practice_type"],
        question_text=item_data["question_text"],
        correct_answer=item_data.get("correct_answer"),
        options_json=item_data.get("options_json"),
        explanation=item_data.get("explanation"),
        concept=item_data.get("concept", ""),
    )

    # 3. Evaluate — graceful degradation on LLM failure.
    #    ValueError: ai_client is None but LLM evaluation needed.
    #    AIClientError / RateLimitError: LLM call itself failed.
    try:
        result = await evaluate_answer(ai_client, eval_item, data.student_answer)
    except Exception as exc:
        logger.warning(
            "Evaluation failed (%s), falling back to exact match",
            type(exc).__name__,
        )
        result = _exact_match_fallback(eval_item, data.student_answer)

    # 4. Store the practice result.
    practice_result = await _store_practice_result(
        client=client,
        user_id=user_id,
        item_data=item_data,
        student_answer=data.student_answer,
        evaluation=result,
        confidence_before=data.confidence_before,
        study_block_id=data.study_block_id,
        time_spent_seconds=data.time_spent_seconds,
    )

    return EvaluateResponse(
        practice_result_id=practice_result["id"],
        is_correct=result.is_correct,
        score=result.score,
        feedback=result.feedback,
        misconceptions_detected=result.misconceptions_detected,
    )


# ---------------------------------------------------------------------------
# POST /mastery-states/update-from-results
# ---------------------------------------------------------------------------


@router.post(
    "/mastery-states/update-from-results",
    response_model=MasteryUpdateResponse,
)
async def update_mastery_from_results(
    data: MasteryUpdateRequest,
    current_user: CurrentUser,
    client: UserClient,
) -> MasteryUpdateResponse:
    """Batch-update mastery states from practice results for a study block.

    Reads all practice results for the given study_block_id, groups them
    by concept, and calls the mastery updater for each concept.
    """
    user_id = current_user["user_id"]
    from uuid import UUID

    uid = UUID(user_id)

    # Verify block ownership before reading results.
    await _fetch_block_for_user(client, data.study_block_id, user_id)

    # 1. Fetch practice results for the block.
    results_resp = await (
        client.table("practice_results")
        .select("*")
        .eq("study_block_id", data.study_block_id)
        .eq("user_id", user_id)
        .execute()
    )
    results: list[dict[str, Any]] = results_resp.data or []

    if not results:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NO_RESULTS",
                "message": "No practice results found for this study block.",
            },
        )

    # 2. Group results by (course_id, concept).
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        concept = r.get("concept")
        course_id = r.get("course_id")
        if concept and course_id:
            grouped[(course_id, concept)].append(r)

    # 3. Update mastery for each concept.
    mastery_states: list[MasteryStateResult] = []
    for (course_id, concept), concept_results in grouped.items():
        state = await update_mastery(client, uid, course_id, concept, concept_results)
        mastery_states.append(
            MasteryStateResult(
                concept=state.concept,
                course_id=state.course_id,
                mastery_level=state.mastery_level,
                success_rate=state.success_rate,
                confidence_self_report=state.confidence_self_report,
                retrieval_count=state.retrieval_count,
                last_retrieval_at=state.last_retrieval_at,
                next_review_at=state.next_review_at,
            )
        )

    return MasteryUpdateResponse(
        study_block_id=data.study_block_id,
        mastery_states=mastery_states,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_block_for_user(
    client: AsyncClient,
    block_id: int,
    user_id: str,
) -> dict[str, Any]:
    """Fetch a study block, verifying ownership via plan join."""
    result = await (
        client.table("study_blocks")
        .select("*, study_plans!inner(user_id)")
        .eq("id", block_id)
        .eq("study_plans.user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BLOCK_NOT_FOUND",
                "message": "Study block not found.",
            },
        )
    data = result.data
    data.pop("study_plans", None)
    return data


async def _derive_concept(
    client: AsyncClient,
    block: dict[str, Any],
) -> tuple[str | None, int | None]:
    """Derive concept name and course_id from a study block.

    Tries assessment.unit_or_topic first, falls back to block title
    enriched with the course name so the LLM knows the subject area.
    """
    assessment_id = block.get("assessment_id")
    course_id = block.get("course_id")

    if assessment_id is not None:
        result = await (
            client.table("assessments")
            .select("unit_or_topic, course_id")
            .eq("id", assessment_id)
            .maybe_single()
            .execute()
        )
        if result and result.data:
            concept = result.data.get("unit_or_topic")
            if not course_id:
                course_id = result.data.get("course_id")
            if concept:
                return concept, course_id

    # Fallback: enrich block title with course name for LLM context.
    if course_id:
        title = block.get("title")
        if title:
            course_name = await _get_course_name(client, course_id)
            if course_name:
                return f"{course_name}: {title}", course_id
            return title, course_id

    return None, None


async def _get_course_name(client: AsyncClient, course_id: int) -> str | None:
    """Fetch the course name for enriching concept context."""
    result = await (
        client.table("courses")
        .select("name")
        .eq("id", course_id)
        .maybe_single()
        .execute()
    )
    if result and result.data:
        return result.data.get("name")
    return None


async def _get_mastery_level(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str,
) -> float:
    """Fetch current mastery level for this user/course/concept. Defaults to 0.0."""
    result = await (
        client.table("mastery_states")
        .select("mastery_level")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .eq("concept", concept)
        .maybe_single()
        .execute()
    )
    if result and result.data:
        return float(result.data.get("mastery_level", 0.0))
    return 0.0


async def _fetch_resource_chunks(
    client: AsyncClient,
    course_id: int,
) -> list[dict[str, Any]]:
    """Fetch resource chunks for a course (via resources join)."""
    result = await (
        client.table("resource_chunks")
        .select("id, content_text, resource_id, resources!inner(course_id)")
        .eq("resources.course_id", course_id)
        .limit(20)
        .execute()
    )
    return result.data or []


async def _fetch_cached_items(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str,
) -> list[dict[str, Any]]:
    """Fetch previously generated practice items from the cache."""
    result = await (
        client.table("practice_items")
        .select("*")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .eq("concept", concept)
        .execute()
    )
    return result.data or []


async def _fetch_practice_item(
    client: AsyncClient,
    item_id: int,
    user_id: str,
) -> dict[str, Any] | None:
    """Fetch a practice item by ID, scoped to the user."""
    result = await (
        client.table("practice_items")
        .select("*")
        .eq("id", item_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data if result else None


async def _store_practice_result(
    *,
    client: AsyncClient,
    user_id: str,
    item_data: dict[str, Any],
    student_answer: str,
    evaluation: Any,
    confidence_before: float | None,
    study_block_id: int | None,
    time_spent_seconds: int | None,
) -> dict[str, Any]:
    """Store the evaluation result in the practice_results table."""
    row = {
        "user_id": user_id,
        "course_id": item_data["course_id"],
        "concept": item_data.get("concept"),
        "practice_type": item_data["practice_type"],
        "question_text": item_data["question_text"],
        "student_answer": student_answer,
        "correct_answer": item_data.get("correct_answer"),
        "is_correct": evaluation.is_correct,
        "score": evaluation.score,
        "feedback": evaluation.feedback,
        "misconceptions_detected": evaluation.misconceptions_detected,
        "confidence_before": confidence_before,
        "study_block_id": study_block_id,
        "time_spent_seconds": time_spent_seconds,
    }
    result = await client.table("practice_results").insert(row).execute()
    if not result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INSERT_FAILED",
                "message": "Failed to store practice result.",
            },
        )
    return result.data[0]


def _exact_match_fallback(
    item: EvalPracticeItem,
    student_answer: str,
) -> Any:
    """Simple exact-match evaluation as a fallback when LLM is unavailable."""
    from mitty.practice.evaluator import EvaluationResult

    correct = (item.correct_answer or "").strip().lower()
    answer = student_answer.strip().lower()

    if correct and answer == correct:
        return EvaluationResult(
            is_correct=True,
            score=1.0,
            feedback="Correct!",
            misconceptions_detected=[],
        )

    return EvaluationResult(
        is_correct=False,
        score=0.0,
        feedback=(
            f"Incorrect. The correct answer is {item.correct_answer}."
            if item.correct_answer
            else "Incorrect. Unable to determine the correct answer."
        ),
        misconceptions_detected=[],
    )
