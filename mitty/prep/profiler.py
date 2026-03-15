"""Mastery profiler — aggregates homework analyses into per-concept profiles.

Reads ``homework_analyses`` rows for a given user + assignment, computes
per-concept accuracy (correct / total), maps concepts to Sullivan
Pre-Calculus 11e sections (4.1, 4.3-4.7), ranks weaknesses by lowest
accuracy, and syncs results to ``mastery_states`` via ``update_mastery()``.

Returns a list of ``TestPrepMasteryProfile``-compatible objects sorted by
mastery level (weakest first).

Traces: DEC-003 (mastery profile from homework analyses).

Public API:
    build_mastery_profile(client, user_id, course_id, assignment_id) ->
        list[TestPrepMasteryProfile]
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID  # noqa: TCH003 — needed at runtime

from mitty.api.schemas import ErrorType, TestPrepMasteryProfile
from mitty.mastery.updater import update_mastery

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sullivan Pre-Calculus 11e section mapping (Ch 4)
# ---------------------------------------------------------------------------

CONCEPT_SECTION_MAP: dict[str, str] = {
    # Section 4.1 — Polynomial Functions and Models
    "polynomial functions": "4.1",
    "polynomial long division": "4.1",
    "synthetic division": "4.1",
    "polynomial models": "4.1",
    "end behavior": "4.1",
    "turning points": "4.1",
    # Section 4.3 — Rational Functions
    "rational functions": "4.3",
    "vertical asymptotes": "4.3",
    "horizontal asymptotes": "4.3",
    "oblique asymptotes": "4.3",
    "asymptotes": "4.3",
    # Section 4.4 — Polynomial and Rational Inequalities
    "polynomial inequalities": "4.4",
    "rational inequalities": "4.4",
    "sign analysis": "4.4",
    # Section 4.5 — The Real Zeros of a Polynomial Function
    "real zeros": "4.5",
    "zeros of polynomials": "4.5",
    "remainder theorem": "4.5",
    "factor theorem": "4.5",
    "rational zeros theorem": "4.5",
    "descartes rule of signs": "4.5",
    # Section 4.6 — Complex Zeros; Fundamental Theorem of Algebra
    "complex zeros": "4.6",
    "fundamental theorem of algebra": "4.6",
    "conjugate pairs theorem": "4.6",
    # Section 4.7 — Polynomial Equations
    "polynomial equations": "4.7",
    "factoring polynomials": "4.7",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_problems(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten per-problem dicts from homework_analyses rows.

    Each row's ``analysis_json`` has a ``per_problem`` key containing
    a list of problem dicts with: problem_number, correctness, error_type,
    concept.
    """
    problems: list[dict[str, Any]] = []
    for row in rows:
        analysis = row.get("analysis_json", {})
        per_problem = analysis.get("per_problem", [])
        for p in per_problem:
            if p.get("concept"):
                problems.append(p)
    return problems


def _aggregate_concepts(
    problems: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate per-problem data into per-concept summaries.

    Returns a dict keyed by concept name with:
      - total_correctness: sum of correctness scores
      - problems_attempted: count of problems
      - problems_correct: count of problems with correctness == 1.0
      - error_types: set of non-null error types
      - time_seconds: list of time_spent_seconds values (if present)
    """
    concepts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total_correctness": 0.0,
            "problems_attempted": 0,
            "problems_correct": 0,
            "error_types": set(),
            "time_seconds": [],
        }
    )

    for p in problems:
        concept = p["concept"]
        entry = concepts[concept]
        correctness = float(p.get("correctness", 0.0))

        entry["total_correctness"] += correctness
        entry["problems_attempted"] += 1
        if correctness >= 0.9999:
            entry["problems_correct"] += 1

        error_type = p.get("error_type")
        if error_type:
            entry["error_types"].add(error_type)

        time_spent = p.get("time_spent_seconds")
        if time_spent is not None:
            entry["time_seconds"].append(time_spent)

    return dict(concepts)


def _build_mastery_results(
    concept_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build results list suitable for update_mastery() from concept data.

    Each result dict has ``score`` (0-1) and ``is_correct`` (bool).
    We synthesize one result per problem, using the average correctness
    as the score and is_correct = True when correctness == 1.0.

    For update_mastery(), we pass a single aggregated result per concept
    where score = average correctness.
    """
    attempted = concept_data["problems_attempted"]
    if attempted == 0:
        return []

    avg_correctness = concept_data["total_correctness"] / attempted
    return [
        {
            "score": avg_correctness,
            "is_correct": avg_correctness >= 1.0,
        }
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_mastery_profile(
    *,
    client: AsyncClient,
    user_id: UUID,
    course_id: int,
    assignment_id: int | None = None,
    assignment_ids: list[int] | None = None,
    _update_mastery_fn: (Callable[..., Coroutine[Any, Any, Any]] | None) = None,
) -> list[TestPrepMasteryProfile]:
    """Build a per-concept mastery profile from homework analyses.

    Steps:
      1. Query ``homework_analyses`` for the given user + assignments.
      2. Flatten per-problem results and aggregate by concept.
      3. Compute accuracy (correct / total) per concept.
      4. Map concepts to Sullivan sections (4.1, 4.3-4.7).
      5. Sync each concept to ``mastery_states`` via ``update_mastery()``.
      6. Return profiles sorted by mastery level (weakest first).

    Args:
        client: Async Supabase client.
        user_id: The student's user ID.
        course_id: The course ID.
        assignment_id: Single assignment ID (deprecated, kept for compat).
        assignment_ids: List of assignment IDs to aggregate. If neither
            this nor assignment_id is provided, queries ALL homework
            analyses for the course.
        _update_mastery_fn: Optional override for ``update_mastery`` (for
            testing). If None, uses the real ``update_mastery`` function.

    Returns:
        List of TestPrepMasteryProfile sorted by mastery_level ascending
        (weakest concepts first).
    """
    do_update = _update_mastery_fn or update_mastery

    # 1. Fetch homework_analyses rows.
    # Build the list of assignment IDs to query
    ids_to_query: list[int] | None = None
    if assignment_ids:
        ids_to_query = assignment_ids
    elif assignment_id:
        ids_to_query = [assignment_id]

    if ids_to_query:
        response = await (
            client.table("homework_analyses")
            .select("*")
            .eq("user_id", str(user_id))
            .in_("assignment_id", ids_to_query)
            .execute()
        )
    else:
        # No specific IDs — get all analyses for assignments in this course
        assign_result = await (
            client.table("assignments")
            .select("id")
            .eq("course_id", course_id)
            .execute()
        )
        all_ids = [r["id"] for r in (assign_result.data or [])]
        if not all_ids:
            return []
        response = await (
            client.table("homework_analyses")
            .select("*")
            .eq("user_id", str(user_id))
            .in_("assignment_id", all_ids)
            .execute()
        )
    rows: list[dict[str, Any]] = response.data or []

    if not rows:
        logger.info(
            "No homework analyses found for user=%s course=%d",
            user_id,
            course_id,
        )
        return []

    # 2. Extract and aggregate problems by concept.
    problems = _extract_problems(rows)
    if not problems:
        logger.info(
            "No per-problem data in analyses for user=%s assignment=%d",
            user_id,
            assignment_id,
        )
        return []

    concept_data = _aggregate_concepts(problems)

    # 3-4. Build profiles and sync mastery.
    profiles: list[TestPrepMasteryProfile] = []

    for concept, data in concept_data.items():
        attempted = data["problems_attempted"]
        correct = data["problems_correct"]
        accuracy = data["total_correctness"] / attempted if attempted > 0 else 0.0

        # Average time (None if no time data)
        avg_time: float | None = None
        if data["time_seconds"]:
            avg_time = sum(data["time_seconds"]) / len(data["time_seconds"])

        # Map error types to the ErrorType enum values
        error_types: list[ErrorType] = []
        valid_error_types = {
            "conceptual",
            "procedural",
            "careless",
            "incomplete",
            "unknown",
            "arithmetic",
            "sign",
            "transcription",
        }
        for et in data["error_types"]:
            if et in valid_error_types:
                error_types.append(et)  # type: ignore[arg-type]

        # Section mapping (informational, logged)
        section = CONCEPT_SECTION_MAP.get(concept.lower())
        if section:
            logger.debug("Concept %r maps to Sullivan section %s", concept, section)

        profile = TestPrepMasteryProfile(
            concept=concept,
            mastery_level=accuracy,
            problems_attempted=attempted,
            problems_correct=correct,
            avg_time_seconds=avg_time,
            error_types=error_types,
        )
        profiles.append(profile)

        # 5. Sync to mastery_states.
        results = _build_mastery_results(data)
        if results:
            await do_update(
                client=client,
                user_id=user_id,
                course_id=course_id,
                concept=concept,
                results=results,
            )

    # 6. Sort by mastery_level ascending (weakest first).
    profiles.sort(key=lambda p: p.mastery_level)

    logger.info(
        "Built mastery profile for user=%s assignment=%d: "
        "%d concepts, weakest=%r (%.1f%%)",
        user_id,
        assignment_id,
        len(profiles),
        profiles[0].concept if profiles else "N/A",
        profiles[0].mastery_level * 100 if profiles else 0.0,
    )

    return profiles
