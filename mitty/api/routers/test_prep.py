"""Test prep API endpoints (US-010).

- POST /test-prep/analyze-homework       — SSE homework analysis (DEC-010)
- GET  /test-prep/mastery-profile        — per-concept mastery profile
- POST /test-prep/sessions               — create test prep session (DEC-006)
- GET  /test-prep/sessions/{session_id}  — get session state (DEC-008)
- POST /test-prep/sessions/{session_id}/answer        — submit answer
- POST /test-prep/sessions/{session_id}/next-problem  — generate next problem
- POST /test-prep/sessions/{session_id}/skip-phase    — advance to next phase
- POST /test-prep/sessions/{session_id}/complete     — end session + summary

Traces: DEC-002 (parallel vision), DEC-006 (UUID PKs), DEC-008 (server-
authoritative state), DEC-010 (SSE, 30-min timeout, 1 concurrent per user).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_ai_client, get_canvas_client, get_user_client
from mitty.api.schemas import (
    AnalysisProgressEvent,
    HomeworkAnalysisTrigger,
    TestPrepAnswerResult,
    TestPrepAnswerSubmit,
    TestPrepConfidenceComparison,
    TestPrepConfidenceSubmit,
    TestPrepMasteryProfile,
    TestPrepProblem,
    TestPrepSessionCreate,
    TestPrepSessionResponse,
    TestPrepSessionSummary,
)
from mitty.practice.evaluator import PracticeItem, evaluate_answer
from mitty.prep.analyzer import analyze_homework_set
from mitty.prep.generator import build_review_own_errors, generate_problem
from mitty.prep.profiler import build_mastery_profile
from mitty.prep.session import SessionEngine, SessionPhase

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from mitty.ai.client import AIClient
    from mitty.canvas.client import CanvasClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-prep", tags=["test_prep"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]
OptionalAI = Annotated["AIClient | None", Depends(get_ai_client)]
OptionalCanvas = Annotated["CanvasClient | None", Depends(get_canvas_client)]

# DEC-010: 1 concurrent analysis per user
_active_analyses: dict[str, asyncio.Event] = {}

# DEC-010: 30-minute SSE timeout
_SSE_TIMEOUT_SECONDS = 30 * 60


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _verify_session_ownership(
    client: AsyncClient,
    session_id: UUID,
    user_id: str,
) -> dict[str, Any]:
    """Fetch a test prep session, verifying ownership.

    Raises 404 with SESSION_NOT_FOUND if the session does not exist or
    does not belong to the authenticated user.
    """
    result = await (
        client.table("test_prep_sessions")
        .select("*")
        .eq("id", str(session_id))
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": "Test prep session not found.",
            },
        )
    return result.data


async def _build_student_context(
    client: AsyncClient,
    *,
    user_id: str,
    course_id: int | None,
    assessment_id: int | None,
    concept: str,
) -> str | None:
    """Build context string from homework analysis and resource chunks.

    Gives the problem generator real data about:
    - What the student got right/wrong on the homework
    - Relevant textbook/resource content for the concept
    """
    parts: list[str] = []

    # 1. Homework analysis — what the student struggled with
    if assessment_id:
        try:
            hw_result = await (
                client.table("homework_analyses")
                .select("analysis_json")
                .eq("user_id", user_id)
                .eq("assignment_id", assessment_id)
                .limit(3)
                .execute()
            )
            if hw_result.data:
                hw_lines: list[str] = []
                for row in hw_result.data:
                    aj = row.get("analysis_json", {})
                    for prob in aj.get("per_problem", []):
                        prob_concept = prob.get("concept", "")
                        correctness = prob.get("correctness", 0)
                        error = prob.get("error_type")
                        line = (
                            f"  Problem {prob.get('problem_number', '?')}: "
                            f"concept={prob_concept}, "
                            f"correctness={correctness}"
                        )
                        if error:
                            line += f", error_type={error}"
                        hw_lines.append(line)
                    summary = aj.get("summary", {})
                    if summary.get("areas_for_improvement"):
                        hw_lines.append(
                            "  Areas for improvement: "
                            + "; ".join(summary["areas_for_improvement"])
                        )
                if hw_lines:
                    parts.append(
                        "HOMEWORK ANALYSIS (student's recent work):\n"
                        + "\n".join(hw_lines)
                    )
        except Exception:
            logger.debug("Failed to fetch homework analysis", exc_info=True)

    # 2. Resource chunks — relevant textbook/course content
    #    Join through resources table to filter by course_id and get title.
    if course_id:
        try:
            chunk_result = await (
                client.table("resource_chunks")
                .select("content_text, resources!inner(title, course_id)")
                .eq("resources.course_id", course_id)
                .ilike("content_text", f"%{concept}%")
                .limit(3)
                .execute()
            )
            if chunk_result.data:
                chunk_lines = []
                for chunk in chunk_result.data:
                    res = chunk.get("resources", {})
                    title = res.get("title", "") if res else ""
                    text = chunk.get("content_text", "")
                    # Truncate long chunks
                    if len(text) > 500:
                        text = text[:500] + "..."
                    prefix = f"  [{title}] " if title else "  "
                    chunk_lines.append(prefix + text)
                if chunk_lines:
                    parts.append(
                        "TEXTBOOK/RESOURCE CONTENT:\n" + "\n".join(chunk_lines)
                    )
        except Exception:
            logger.debug("Failed to fetch resource chunks", exc_info=True)

    return "\n\n".join(parts) if parts else None


# Map test-prep problem types to evaluator practice types.
# Types not listed here default to "short_answer" (LLM evaluation).
_EVAL_TYPE_MAP: dict[str, str] = {
    "multiple_choice": "multiple_choice",
    "worked_example": "worked_example",
}


async def _evaluate_answer(
    *,
    problem_json: dict[str, Any],
    student_answer: str,
    ai_client: AIClient | None = None,
) -> dict[str, Any]:
    """Evaluate a student answer using the hybrid evaluator.

    Multiple-choice uses exact match; all other types use LLM
    evaluation for semantic comparison (partial credit, alternate
    formats). Falls back to simple exact-match when AI is unavailable.
    """
    problem_type = problem_json.get("type", "free_response")
    eval_type = _EVAL_TYPE_MAP.get(problem_type, "short_answer")

    item = PracticeItem(
        practice_type=eval_type,
        question_text=problem_json.get("prompt", ""),
        correct_answer=str(problem_json.get("correct_answer", "")),
        options_json=problem_json.get("choices"),
        explanation=problem_json.get("explanation"),
        concept=problem_json.get("concept", ""),
    )

    try:
        result = await evaluate_answer(ai_client, item, student_answer)
        return {
            "is_correct": result.is_correct,
            "score": result.score,
            "explanation": result.feedback,
        }
    except (ValueError, Exception):
        # AI unavailable — fall back to exact match
        logger.debug(
            "LLM evaluation unavailable, using exact match",
            exc_info=True,
        )
        correct = str(problem_json.get("correct_answer", ""))
        normalised_student = student_answer.strip().lower()
        normalised_correct = correct.strip().lower()
        is_correct = normalised_student == normalised_correct
        return {
            "is_correct": is_correct,
            "score": 1.0 if is_correct else 0.0,
            "explanation": "Correct!" if is_correct else "Not quite.",
        }


# ---------------------------------------------------------------------------
# POST /test-prep/analyze-homework (SSE — DEC-010)
# ---------------------------------------------------------------------------


async def _analysis_event_stream(
    *,
    trigger: HomeworkAnalysisTrigger,
    user_id: str,
    ai_client: AIClient,
    supabase_client: AsyncClient,
    canvas_client: CanvasClient | None = None,
) -> AsyncGenerator[str]:
    """Yield SSE events as homework analysis progresses."""
    # Emit started event
    started = AnalysisProgressEvent(
        status="started",
        message=f"Starting analysis of assignment {trigger.assignment_id}",
    )
    yield f"data: {started.model_dump_json()}\n\n"

    try:
        results = await asyncio.wait_for(
            analyze_homework_set(
                assignment_ids=[trigger.assignment_id],
                course_id=trigger.course_id,
                user_id=user_id,
                ai_client=ai_client,
                supabase_client=supabase_client,
                canvas_client=canvas_client,
            ),
            timeout=_SSE_TIMEOUT_SECONDS,
        )

        # Emit per-page events
        for r in results:
            page_event = AnalysisProgressEvent(
                status="page_complete",
                page_number=r.get("page_number"),
                total_pages=len(results),
                message=f"Page {r.get('page_number', '?')} analysis complete",
            )
            yield f"data: {page_event.model_dump_json()}\n\n"

        # Emit complete event
        complete = AnalysisProgressEvent(
            status="complete",
            total_pages=len(results),
            message=f"Analysis complete: {len(results)} pages analyzed",
        )
        yield f"data: {complete.model_dump_json()}\n\n"

    except TimeoutError:
        error = AnalysisProgressEvent(
            status="error",
            message="Analysis timed out after 30 minutes",
        )
        yield f"data: {error.model_dump_json()}\n\n"

    except Exception:
        logger.warning(
            "Homework analysis failed for user=%s assignment=%d",
            user_id,
            trigger.assignment_id,
            exc_info=True,
        )
        error = AnalysisProgressEvent(
            status="error",
            message="Analysis failed. Please try again later.",
        )
        yield f"data: {error.model_dump_json()}\n\n"

    finally:
        # Release the per-user concurrency slot
        event = _active_analyses.pop(user_id, None)
        if event:
            event.set()


@router.post("/analyze-homework")
async def analyze_homework(
    trigger: HomeworkAnalysisTrigger,
    current_user: CurrentUser,
    client: UserClient,
    ai_client: OptionalAI,
    canvas_client: OptionalCanvas,
) -> StreamingResponse:
    """Trigger homework analysis and stream progress via SSE.

    DEC-010: 30-minute timeout, 1 concurrent analysis per user.
    Returns 503 if AI client is unavailable, 429 if an analysis is
    already in progress for this user.
    """
    user_id = current_user["user_id"]

    if ai_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "AI_UNAVAILABLE",
                "message": "AI service is currently unavailable.",
            },
        )

    # DEC-010: 1 concurrent analysis per user (atomic check-and-set)
    if user_id in _active_analyses:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ANALYSIS_IN_PROGRESS",
                "message": "An analysis is already in progress. "
                "Please wait for it to complete.",
            },
        )
    # No await between check and set, so this is safe under CPython's GIL.
    _active_analyses[user_id] = asyncio.Event()

    return StreamingResponse(
        _analysis_event_stream(
            trigger=trigger,
            user_id=user_id,
            ai_client=ai_client,
            supabase_client=client,
            canvas_client=canvas_client,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /test-prep/mastery-profile
# ---------------------------------------------------------------------------


@router.get(
    "/mastery-profile",
    response_model=list[TestPrepMasteryProfile],
)
async def get_mastery_profile(
    current_user: CurrentUser,
    client: UserClient,
    course_id: int = Query(...),
    assignment_id: int = Query(...),
) -> list[TestPrepMasteryProfile]:
    """Fetch per-concept mastery profile from homework analyses.

    Aggregates homework analysis results for the specified course
    and assignment, returning mastery profiles sorted by weakest first.
    """
    user_id = current_user["user_id"]

    return await build_mastery_profile(
        client=client,
        user_id=UUID(user_id),
        course_id=course_id,
        assignment_id=assignment_id,
    )


# ---------------------------------------------------------------------------
# POST /test-prep/sessions  (DEC-006: UUID PK)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=TestPrepSessionResponse,
    status_code=201,
)
async def create_session(
    data: TestPrepSessionCreate,
    current_user: CurrentUser,
    client: UserClient,
) -> TestPrepSessionResponse:
    """Create a new test prep session.

    Initialises a SessionEngine in the diagnostic phase, persists
    state to ``test_prep_sessions``, and returns the new row.
    """
    user_id = current_user["user_id"]
    session_id = uuid4()
    now = datetime.now(UTC)

    engine = SessionEngine(
        session_id=session_id,
        user_id=UUID(user_id),
        course_id=data.course_id,
        concepts=data.concepts,
        session_type=data.session_type,
    )

    row = {
        "id": str(session_id),
        "user_id": user_id,
        "course_id": data.course_id,
        "assessment_id": data.assessment_id,
        "state_json": engine.to_state_dict(),
        "started_at": now.isoformat(),
        "completed_at": None,
        "total_problems": 0,
        "total_correct": 0,
        "duration_seconds": None,
        "phase_reached": engine.current_phase.value,
        "session_type": data.session_type,
    }

    result = await client.table("test_prep_sessions").insert(row).execute()
    if not result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INSERT_FAILED",
                "message": "Failed to create test prep session.",
            },
        )

    return TestPrepSessionResponse.model_validate(result.data[0])


# ---------------------------------------------------------------------------
# GET /test-prep/sessions/{session_id}  (DEC-008: server-authoritative)
# ---------------------------------------------------------------------------


@router.get(
    "/sessions/{session_id}",
    response_model=TestPrepSessionResponse,
)
async def get_session(
    session_id: UUID,
    current_user: CurrentUser,
    client: UserClient,
) -> TestPrepSessionResponse:
    """Fetch a test prep session by ID.

    Verifies ownership via user_id filter.  Returns 404 if the session
    does not exist or belongs to another user.
    """
    user_id = current_user["user_id"]
    session_data = await _verify_session_ownership(client, session_id, user_id)
    return TestPrepSessionResponse.model_validate(session_data)


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/answer
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/answer",
    response_model=TestPrepAnswerResult,
)
async def submit_answer(
    session_id: UUID,
    data: TestPrepAnswerSubmit,
    current_user: CurrentUser,
    client: UserClient,
    ai_client: OptionalAI,
) -> TestPrepAnswerResult:
    """Submit an answer for a problem in a test prep session.

    Finds the unanswered problem by problem_id, evaluates the answer,
    updates the session engine state, and persists both.  Returns 409
    PROBLEM_NOT_FOUND if the problem was already answered or does not
    exist.
    """
    user_id = current_user["user_id"]
    session_data = await _verify_session_ownership(client, session_id, user_id)

    # Find the unanswered problem
    problem_result = await (
        client.table("test_prep_results")
        .select("*")
        .eq("session_id", str(session_id))
        .eq("id", data.problem_id)
        .is_("student_answer", "null")
        .maybe_single()
        .execute()
    )
    if not problem_result or not problem_result.data:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROBLEM_NOT_FOUND",
                "message": "Problem not found or already answered.",
            },
        )

    problem_row = problem_result.data
    problem_json = problem_row.get("problem_json", {})

    # Reflections (review_own_errors) are ungraded — auto-accept
    is_reflection = problem_json.get("is_reflection", False)
    if is_reflection:
        evaluation = {
            "is_correct": True,
            "score": 1.0,
            "explanation": "Reflection recorded. Nice work!",
        }
    else:
        # Evaluate the answer (LLM for free-response, exact for MC)
        evaluation = await _evaluate_answer(
            problem_json=problem_json,
            student_answer=data.student_answer,
            ai_client=ai_client,
        )

    # Update the result row
    update_data: dict[str, Any] = {
        "student_answer": data.student_answer,
        "is_correct": evaluation["is_correct"],
        "score": evaluation["score"],
        "feedback": evaluation["explanation"],
    }
    if data.time_spent_seconds is not None:
        update_data["time_spent_seconds"] = data.time_spent_seconds

    update_result = await (
        client.table("test_prep_results")
        .update(update_data)
        .eq("id", data.problem_id)
        .eq("session_id", str(session_id))
        .execute()
    )
    if not update_result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "UPDATE_FAILED",
                "message": "Failed to update problem result.",
            },
        )

    # Update session engine state
    state_dict = session_data.get("state_json", {})
    engine = SessionEngine.from_state_dict(
        session_id=session_id,
        user_id=UUID(user_id),
        state_dict=state_dict,
    )
    engine.record_answer(
        correct=evaluation["is_correct"],
        concept=problem_row.get("concept"),
    )

    # US-010: Record wrong answers from Phases 1-2 for review_own_errors
    if not evaluation["is_correct"] and not is_reflection:
        engine.record_wrong_answer(
            problem_id=problem_row.get("id", 0),
            concept=problem_row.get("concept", ""),
            problem_json=problem_json,
            student_answer=data.student_answer,
            feedback=evaluation["explanation"],
            difficulty=problem_row.get("difficulty", 0.5),
        )

    # Persist updated session state
    await (
        client.table("test_prep_sessions")
        .update(
            {
                "state_json": engine.to_state_dict(),
                "total_problems": engine.state.total_problems,
                "total_correct": engine.state.total_correct,
            }
        )
        .eq("id", str(session_id))
        .execute()
    )

    return TestPrepAnswerResult(
        is_correct=evaluation["is_correct"],
        score=evaluation["score"],
        explanation=evaluation["explanation"],
        correct_answer=str(problem_json.get("correct_answer", "")),
        worked_solution=problem_json.get("explanation", None),
        next_problem=None,  # Next problem generated on demand by the client
    )


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/next-problem
# ---------------------------------------------------------------------------

# Map session phase to the problem type the generator should produce.
_PHASE_PROBLEM_TYPE: dict[SessionPhase, str] = {
    SessionPhase.diagnostic: "free_response",
    SessionPhase.focused_practice: "multiple_choice",
    SessionPhase.error_analysis: "error_analysis",
    SessionPhase.mixed_test: "mixed",
    SessionPhase.calibration: "calibration",
}


@router.post(
    "/sessions/{session_id}/next-problem",
    response_model=TestPrepProblem,
)
async def next_problem(
    session_id: UUID,
    current_user: CurrentUser,
    client: UserClient,
    ai_client: OptionalAI,
) -> TestPrepProblem:
    """Generate the next problem for a session.

    Reads the session state (phase, difficulty, concepts), calls the AI
    problem generator, inserts the problem into ``test_prep_results``,
    and returns it so the frontend can display it.
    """
    user_id = current_user["user_id"]
    session_data = await _verify_session_ownership(client, session_id, user_id)

    state_json = session_data.get("state_json", {})
    phase_str = state_json.get("phase", "diagnostic")
    phase = SessionPhase(phase_str)
    difficulty = state_json.get("difficulty", 0.5)
    concepts: list[str] = state_json.get("concepts", [])

    if not concepts:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "NO_CONCEPTS",
                "message": "Session has no concepts to generate problems for.",
            },
        )

    # US-010: Restore session engine to determine error_analysis subtype
    engine = SessionEngine.from_state_dict(
        session_id=session_id,
        user_id=UUID(user_id),
        state_dict=state_json,
    )

    # Auto-advance: diagnostic ends after 1 question per concept
    if phase == SessionPhase.diagnostic:
        mastery = engine.state.concept_mastery
        all_tested = all(mastery.get(c, {}).get("attempted", 0) >= 1 for c in concepts)
        if all_tested:
            try:
                phase = engine.advance_phase()
                # Persist the phase change
                await (
                    client.table("test_prep_sessions")
                    .update(
                        {
                            "state_json": engine.to_state_dict(),
                            "phase_reached": phase.value,
                        }
                    )
                    .eq("id", str(session_id))
                    .execute()
                )
                logger.info(
                    "Session %s: auto-advanced from diagnostic (%d concepts tested)",
                    session_id,
                    len(concepts),
                )
            except ValueError:
                pass  # already at final phase

    # Pick concept round-robin based on phase-level problem count
    phase_key = phase.value
    phase_problems = engine.state.phase_problems.get(phase_key, 0)
    concept = concepts[phase_problems % len(concepts)]
    problem_type = _PHASE_PROBLEM_TYPE.get(phase, "free_response")

    # US-010: Phase 3 alternates between find_the_mistake and review_own_errors
    is_reflection = False
    if phase == SessionPhase.error_analysis:
        subtype = engine.get_error_analysis_subtype()

        if subtype == "review_own_errors":
            wrong = engine.pop_wrong_answer()
            if wrong is not None:
                # Build reflection problem from the student's own wrong answer
                problem_dict = build_review_own_errors(wrong_answer=wrong)
                problem_type = "review_own_errors"
                concept = wrong.get("concept", concept)
                is_reflection = True

                # Persist updated engine state (popped wrong answer + counter)
                await (
                    client.table("test_prep_sessions")
                    .update({"state_json": engine.to_state_dict()})
                    .eq("id", str(session_id))
                    .execute()
                )

                # Insert into test_prep_results
                now = datetime.now(UTC)
                row = {
                    "user_id": user_id,
                    "session_id": str(session_id),
                    "concept": concept,
                    "difficulty": problem_dict.get("difficulty", difficulty),
                    "created_at": now.isoformat(),
                    "problem_json": {
                        "type": problem_type,
                        "concept": concept,
                        "difficulty": problem_dict.get("difficulty", difficulty),
                        "prompt": problem_dict["prompt"],
                        "choices": None,
                        "correct_answer": problem_dict.get("correct_answer", ""),
                        "explanation": problem_dict.get("explanation", ""),
                        "hint": problem_dict.get("hint", ""),
                        "is_reflection": True,
                    },
                }
                result = await client.table("test_prep_results").insert(row).execute()
                if not result.data:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "code": "INSERT_FAILED",
                            "message": "Failed to persist reflection problem.",
                        },
                    )
                inserted = result.data[0]
                return TestPrepProblem(
                    id=inserted["id"],
                    problem_type=problem_type,
                    concept=concept,
                    difficulty=problem_dict.get("difficulty", difficulty),
                    prompt=problem_dict["prompt"],
                    choices=None,
                    correct_answer=None,
                    is_reflection=True,
                    phase=phase.value,
                )

            # No wrong answers left — fall through to find_the_mistake
            subtype = "find_the_mistake"

        # find_the_mistake: use the LLM generator with the new subtype
        if subtype == "find_the_mistake":
            problem_type = "find_the_mistake"
            # Persist updated engine state (counter increment)
            await (
                client.table("test_prep_sessions")
                .update({"state_json": engine.to_state_dict()})
                .eq("id", str(session_id))
                .execute()
            )

    if ai_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "AI_UNAVAILABLE",
                "message": "AI client is not configured.",
            },
        )

    # Build student context from homework analysis + resource chunks
    student_context = await _build_student_context(
        client,
        user_id=user_id,
        course_id=state_json.get("course_id"),
        assessment_id=session_data.get("assessment_id"),
        concept=concept,
    )

    # Fetch previously asked prompts to avoid duplicate questions
    try:
        prev_result = await (
            client.table("test_prep_results")
            .select("problem_json")
            .eq("session_id", str(session_id))
            .execute()
        )
        if prev_result.data:
            prev_prompts = [
                r["problem_json"].get("prompt", "")
                for r in prev_result.data
                if r.get("problem_json")
            ]
            if prev_prompts:
                avoid_section = "PREVIOUSLY ASKED (do NOT repeat these):\n" + "\n".join(
                    f"- {p[:150]}" for p in prev_prompts
                )
                if student_context:
                    student_context += "\n\n" + avoid_section
                else:
                    student_context = avoid_section
    except Exception:
        logger.debug("Failed to fetch previous prompts", exc_info=True)

    problem_dict = await generate_problem(
        concept=concept,
        difficulty=difficulty,
        problem_type=problem_type,
        ai_client=ai_client,
        student_context=student_context,
        user_id=user_id,
        supabase_client=client,
    )

    # Insert into test_prep_results so submit_answer can find it
    now = datetime.now(UTC)
    row = {
        "user_id": user_id,
        "session_id": str(session_id),
        "concept": concept,
        "difficulty": difficulty,
        "created_at": now.isoformat(),
        "problem_json": {
            "type": problem_dict.get("type", problem_type),
            "concept": concept,
            "difficulty": difficulty,
            "prompt": problem_dict["prompt"],
            "choices": problem_dict.get("choices"),
            "correct_answer": problem_dict.get("correct_answer", ""),
            "explanation": problem_dict.get("explanation", ""),
            "hint": problem_dict.get("hint", ""),
        },
    }
    result = await client.table("test_prep_results").insert(row).execute()
    if not result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INSERT_FAILED",
                "message": "Failed to persist generated problem.",
            },
        )

    inserted = result.data[0]
    return TestPrepProblem(
        id=inserted["id"],
        problem_type=problem_type,
        concept=concept,
        difficulty=difficulty,
        prompt=problem_dict["prompt"],
        choices=problem_dict.get("choices"),
        correct_answer=None,  # Don't leak correct answer to frontend
        is_reflection=is_reflection,
        phase=phase.value,
    )


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/confidence  (US-009 / DEC-008, R5)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/confidence",
    response_model=TestPrepSessionResponse,
)
async def submit_confidence(
    session_id: UUID,
    data: TestPrepConfidenceSubmit,
    current_user: CurrentUser,
    client: UserClient,
) -> TestPrepSessionResponse:
    """Submit per-concept confidence ratings at a phase transition.

    Stores ratings in state_json.per_concept_confidence keyed by
    concept, with phase and rating per checkpoint.  Returns the
    updated session.
    """
    user_id = current_user["user_id"]
    session_data = await _verify_session_ownership(client, session_id, user_id)

    state_dict = session_data.get("state_json", {})
    engine = SessionEngine.from_state_dict(
        session_id=session_id,
        user_id=UUID(user_id),
        state_dict=state_dict,
    )

    for concept, rating in data.ratings.items():
        engine.record_confidence(concept=concept, rating=rating)

    # Persist updated state
    result = await (
        client.table("test_prep_sessions")
        .update({"state_json": engine.to_state_dict()})
        .eq("id", str(session_id))
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "UPDATE_FAILED",
                "message": "Failed to update session state.",
            },
        )

    return TestPrepSessionResponse.model_validate(result.data[0])


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/skip-phase
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/skip-phase",
    response_model=TestPrepSessionResponse,
)
async def skip_phase(
    session_id: UUID,
    current_user: CurrentUser,
    client: UserClient,
) -> TestPrepSessionResponse:
    """Advance the session to the next phase.

    Returns the updated session.  Returns 400 FINAL_PHASE if
    already at the last phase (calibration).
    """
    user_id = current_user["user_id"]
    session_data = await _verify_session_ownership(client, session_id, user_id)

    state_dict = session_data.get("state_json", {})
    engine = SessionEngine.from_state_dict(
        session_id=session_id,
        user_id=UUID(user_id),
        state_dict=state_dict,
    )

    try:
        new_phase = engine.advance_phase()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "FINAL_PHASE",
                "message": "Already at the final phase (calibration). "
                "Complete the session instead.",
            },
        ) from None

    # Persist updated state
    result = await (
        client.table("test_prep_sessions")
        .update(
            {
                "state_json": engine.to_state_dict(),
                "phase_reached": new_phase.value,
            }
        )
        .eq("id", str(session_id))
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "UPDATE_FAILED",
                "message": "Failed to update session state.",
            },
        )

    return TestPrepSessionResponse.model_validate(result.data[0])


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/complete
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/complete",
    response_model=TestPrepSessionSummary,
)
async def complete_session(
    session_id: UUID,
    current_user: CurrentUser,
    client: UserClient,
) -> TestPrepSessionSummary:
    """Complete a test prep session and return a summary.

    Marks the session with a completed_at timestamp, computes
    duration, aggregates per-phase scores, and returns a summary.
    Returns 400 ALREADY_COMPLETED if the session was already completed.
    """
    user_id = current_user["user_id"]
    session_data = await _verify_session_ownership(client, session_id, user_id)

    if session_data.get("completed_at") is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ALREADY_COMPLETED",
                "message": "This session has already been completed.",
            },
        )

    now = datetime.now(UTC)
    started_at_str = session_data.get("started_at", "")
    try:
        started_at = datetime.fromisoformat(started_at_str)
        duration = int((now - started_at).total_seconds())
    except (ValueError, TypeError):
        duration = None

    state_dict = session_data.get("state_json", {})
    engine = SessionEngine.from_state_dict(
        session_id=session_id,
        user_id=UUID(user_id),
        state_dict=state_dict,
    )

    # Update session as completed
    complete_result = await (
        client.table("test_prep_sessions")
        .update(
            {
                "completed_at": now.isoformat(),
                "total_problems": engine.state.total_problems,
                "total_correct": engine.state.total_correct,
                "duration_seconds": duration,
            }
        )
        .eq("id", str(session_id))
        .execute()
    )
    if not complete_result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "UPDATE_FAILED",
                "message": "Failed to complete session.",
            },
        )

    # Build per-phase scores from engine state
    from mitty.api.schemas import PhaseScore

    phase_scores: list[PhaseScore] = []
    for phase in engine.phase_order:
        p_key = phase.value
        total = engine.state.phase_problems.get(p_key, 0)
        correct = engine.state.phase_correct.get(p_key, 0)
        if total > 0:
            phase_scores.append(
                PhaseScore(
                    phase=p_key,
                    total=total,
                    correct=correct,
                    accuracy=round(correct / total, 3),
                )
            )

    # Build mastery profile from engine concept_mastery
    mastery_profile: list[TestPrepMasteryProfile] = []
    for concept, mastery_data in engine.state.concept_mastery.items():
        mastery_profile.append(
            TestPrepMasteryProfile(
                concept=concept,
                mastery_level=mastery_data.get("mastery", 0.0),
                problems_attempted=mastery_data.get("attempted", 0),
                problems_correct=mastery_data.get("correct", 0),
            )
        )

    # Build confidence comparison from running checkpoints (US-009)
    confidence_rows = engine.get_confidence_vs_performance()
    confidence_comparison = [
        TestPrepConfidenceComparison(**row) for row in confidence_rows
    ]

    return TestPrepSessionSummary(
        session_id=session_id,
        phase_scores=phase_scores,
        total_correct=engine.state.total_correct,
        total_problems=engine.state.total_problems,
        duration_seconds=duration,
        mastery_profile=mastery_profile,
        confidence_comparison=confidence_comparison,
    )
