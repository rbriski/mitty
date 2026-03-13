"""Guide compiler — orchestrates mastery, sources, protocol, LLM, and cache.

Assembles a :class:`BlockGuide` for a study block by:

1. Fetching mastery concepts for the course.
2. Building a source bundle via :func:`build_source_bundle`.
3. Looking up the protocol for the block type.
4. Identifying target concepts (weakest / most overconfident).
5. Checking the guide content cache, then practice-items cache (DEC-001).
6. Calling the LLM when cache misses occur.
7. Caching results for future re-use (DEC-002).
8. Assembling the final ``BlockGuide`` with graceful degradation (DEC-005).

Public API:
    compile_block_guide(ai_client, client, block_type, course_id, user_id,
        block_id, assessment_id) -> BlockGuide

Traces: DEC-001, DEC-002, DEC-003, DEC-005, DEC-015
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mitty.ai.prompts import get_prompt, wrap_user_input
from mitty.guides.protocols import get_protocol
from mitty.guides.sources import build_source_bundle

if TYPE_CHECKING:
    from mitty.ai.client import AIClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions (DEC-015)
# ---------------------------------------------------------------------------


class GuideCompilationError(Exception):
    """Structured error for guide compilation failures.

    Carries context about where in the pipeline the failure occurred,
    enabling targeted debugging of partial-failure scenarios.

    Attributes:
        block_id: The study block this guide was being compiled for.
        step: Pipeline step where the error occurred.
        message: Human-readable description.
        sources_fetched: Whether sources were successfully retrieved.
        llm_called: Whether the LLM call was attempted.
    """

    def __init__(
        self,
        block_id: int | None,
        step: str,
        message: str,
        *,
        sources_fetched: bool = False,
        llm_called: bool = False,
    ) -> None:
        super().__init__(message)
        self.block_id = block_id
        self.step = step
        self.sources_fetched = sources_fetched
        self.llm_called = llm_called


# ---------------------------------------------------------------------------
# Pydantic model for structured LLM output
# ---------------------------------------------------------------------------


class GeneratedGuideContent(BaseModel):
    """Structured output from the guide compiler LLM call."""

    warmup_items: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Warm-up questions with keys: question, answer, type "
            "(multiple_choice | short_answer | recall)."
        ),
    )
    exit_items: list[dict[str, str]] = Field(
        default_factory=list,
        description="Exit ticket questions with keys: question, answer, type.",
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        description="Observable success criteria for the study block.",
    )


# ---------------------------------------------------------------------------
# BlockGuide value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlockGuide:
    """Compiled executable guide matching the ``study_block_guides`` schema."""

    block_id: int | None
    concepts_json: list[dict[str, Any]] = field(default_factory=list)
    source_bundle_json: list[dict[str, Any]] = field(default_factory=list)
    steps_json: list[dict[str, Any]] = field(default_factory=list)
    warmup_items_json: list[dict[str, Any]] = field(default_factory=list)
    exit_items_json: list[dict[str, Any]] = field(default_factory=list)
    completion_criteria_json: dict[str, Any] = field(default_factory=dict)
    success_criteria_json: list[str] = field(default_factory=list)
    guide_version: str = "1.0"


# ---------------------------------------------------------------------------
# Cache helpers (DEC-002)
# ---------------------------------------------------------------------------


def _compute_source_hash(chunk_ids: list[int], concept: str = "") -> str:
    """Hash sorted chunk IDs with SHA-256 for cache keying.

    Includes the concept name in the hash to prevent collisions when
    different concepts have identical (or empty) source chunk sets.
    """
    payload = f"{concept}:" + ",".join(str(cid) for cid in sorted(chunk_ids))
    return hashlib.sha256(payload.encode()).hexdigest()


async def _check_cache(
    client: AsyncClient,
    concept: str,
    source_hash: str,
) -> dict[str, Any] | None:
    """Query ``guide_content_cache`` for a matching (concept, source_hash).

    Returns the ``content_json`` if found, ``None`` on cache miss or error.
    """
    try:
        result = await (
            client.table("guide_content_cache")
            .select("content_json")
            .eq("concept", concept)
            .eq("source_hash", source_hash)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if rows:
            logger.debug("Cache hit for concept=%r", concept)
            return rows[0].get("content_json")
    except Exception:
        logger.warning("Cache lookup failed for concept=%r", concept, exc_info=True)

    logger.debug("Cache miss for concept=%r", concept)
    return None


async def _store_cache(
    client: AsyncClient,
    concept: str,
    source_hash: str,
    content_type: str,
    content_json: dict[str, Any],
) -> None:
    """Upsert a row into ``guide_content_cache``."""
    from datetime import UTC, datetime

    row = {
        "concept": concept,
        "source_hash": source_hash,
        "content_type": content_type,
        "content_json": content_json,
        "created_at": datetime.now(UTC).isoformat(),
    }
    try:
        await (
            client.table("guide_content_cache")
            .upsert(row, on_conflict="concept,source_hash")
            .execute()
        )
    except Exception:
        logger.warning("Failed to store cache for concept=%r", concept, exc_info=True)


# ---------------------------------------------------------------------------
# Mastery helpers
# ---------------------------------------------------------------------------


async def _fetch_mastery_concepts(
    client: AsyncClient,
    user_id: str,
    course_id: int,
) -> list[dict[str, Any]]:
    """Query ``mastery_states`` for the user + course.

    Returns a list of concept dicts with ``concept``, ``mastery_level``,
    and ``confidence_self_report``.  Returns ``[]`` if no data exists
    (graceful for new students).
    """
    try:
        result = await (
            client.table("mastery_states")
            .select("concept, mastery_level, confidence_self_report")
            .eq("user_id", user_id)
            .eq("course_id", course_id)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.warning(
            "Failed to fetch mastery for user=%s course=%d",
            user_id,
            course_id,
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Practice-items cache for hybrid warm-ups (DEC-001)
# ---------------------------------------------------------------------------


async def _check_practice_items_cache(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str,
) -> list[dict[str, Any]]:
    """Check ``practice_items`` for existing items on this concept.

    Returns matching rows if found (for hybrid warm-up reuse), else ``[]``.
    """
    try:
        result = await (
            client.table("practice_items")
            .select("question_text, correct_answer, practice_type")
            .eq("user_id", user_id)
            .eq("course_id", course_id)
            .eq("concept", concept)
            .limit(5)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.warning(
            "Practice items cache check failed for concept=%r",
            concept,
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Target concept selection
# ---------------------------------------------------------------------------


def _select_target_concepts(
    mastery_data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pick target concepts: weakest by mastery_level, most overconfident.

    Returns up to 3 concepts sorted by priority (weakest first).
    When no mastery data exists, returns an empty list.
    """
    if not mastery_data:
        return []

    # Score: lower mastery = higher priority;
    # overconfident (confidence > mastery) also gets a boost.
    def _priority(row: dict[str, Any]) -> float:
        mastery = float(row.get("mastery_level", 0.0))
        confidence = float(row.get("confidence_self_report") or 0.0)
        overconfidence_bonus = max(0.0, confidence - mastery)
        # Lower mastery + higher overconfidence => lower (better) score
        return mastery - overconfidence_bonus

    ranked = sorted(mastery_data, key=_priority)
    return ranked[:3]


# ---------------------------------------------------------------------------
# Generic fallback content (DEC-005)
# ---------------------------------------------------------------------------


def _generic_warmup(concept: str) -> list[dict[str, str]]:
    """Generate generic warm-up items when LLM is unavailable."""
    return [
        {
            "question": f"What do you already know about {concept}?",
            "answer": "Open-ended recall",
            "type": "recall",
        },
        {
            "question": (f"Rate your confidence (1-5) on {concept} before we begin."),
            "answer": "Self-assessment",
            "type": "recall",
        },
    ]


def _generic_exit(concept: str) -> list[dict[str, str]]:
    """Generate generic exit items when LLM is unavailable."""
    return [
        {
            "question": (
                f"Explain {concept} in your own words as if teaching a friend."
            ),
            "answer": "Open-ended explanation",
            "type": "recall",
        },
    ]


def _generic_success_criteria(concept: str) -> list[str]:
    """Generate generic success criteria when LLM is unavailable."""
    return [
        f"I can explain the main idea of {concept} in my own words.",
        f"I can identify one thing I still need to work on about {concept}.",
    ]


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------


def _build_user_prompt(
    *,
    concept: str,
    mastery_level: float,
    block_type: str,
    source_excerpts: str,
) -> str:
    """Build the user prompt for the guide compiler LLM call."""
    config = get_prompt("guide_compiler")
    return (
        config.user_template.replace("{concept}", wrap_user_input(concept))
        .replace("{mastery_level}", f"{mastery_level:.2f}")
        .replace("{block_type}", block_type)
        .replace("{source_excerpts}", source_excerpts)
    )


# ---------------------------------------------------------------------------
# Core compiler
# ---------------------------------------------------------------------------


async def compile_block_guide(
    ai_client: AIClient | None,
    client: AsyncClient,
    block_type: str,
    course_id: int,
    user_id: str,
    block_id: int | None = None,
    assessment_id: int | None = None,
) -> BlockGuide:
    """Compile an executable study guide for a single block.

    Orchestrates: mastery query -> source bundle -> protocol ->
    LLM generation -> cache -> assembly.

    Args:
        ai_client: AIClient for LLM calls, or ``None`` to skip LLM.
        client: Async Supabase client.
        block_type: One of the 6 block types.
        course_id: The course this block belongs to.
        user_id: Student UUID string.
        block_id: Study block ID (for logging / error context).
        assessment_id: Optional assessment ID for targeted guides.

    Returns:
        A :class:`BlockGuide` frozen dataclass ready for persistence.
    """
    logger.info(
        "Compiling guide for block_type=%s, course=%d, block_id=%s",
        block_type,
        course_id,
        block_id,
    )

    # 1. Fetch mastery concepts for this course
    mastery_data = await _fetch_mastery_concepts(client, user_id, course_id)
    target_concepts = _select_target_concepts(mastery_data)

    # Build concept names for source retrieval
    concept_names = [c["concept"] for c in target_concepts]
    if not concept_names:
        concept_names = [block_type]  # fallback query term

    # 2. Build source bundle
    try:
        source_bundle = await build_source_bundle(client, course_id, concept_names)
    except Exception as exc:
        logger.warning(
            "Source bundle build failed for block_id=%s: %s",
            block_id,
            exc,
        )
        raise GuideCompilationError(
            block_id,
            "source_bundle",
            f"Source bundle build failed: {exc}",
            sources_fetched=False,
            llm_called=False,
        ) from exc

    # 3. Get protocol for block type
    protocol = get_protocol(block_type)

    # 4. Pick primary concept for content generation
    primary_concept = concept_names[0] if concept_names else block_type

    # 5. Compute source hash from chunk IDs
    chunk_ids = [c.chunk_id for c in source_bundle.chunks]
    source_hash = _compute_source_hash(chunk_ids, concept=primary_concept)

    # 6. Check guide content cache
    cached_content = await _check_cache(client, primary_concept, source_hash)

    warmup_items: list[dict[str, Any]] = []
    exit_items: list[dict[str, Any]] = []
    success_criteria: list[str] = []
    degraded = False

    if cached_content is not None:
        # Cache hit -- use cached content directly
        warmup_items = cached_content.get("warmup_items", [])
        exit_items = cached_content.get("exit_items", [])
        success_criteria = cached_content.get("success_criteria", [])
    elif ai_client is not None:
        # 7a. Check practice_items for reusable warm-ups (DEC-001)
        practice_items = await _check_practice_items_cache(
            client, user_id, course_id, primary_concept
        )
        if practice_items:
            warmup_items = [
                {
                    "question": item["question_text"],
                    "answer": item.get("correct_answer", ""),
                    "type": item.get("practice_type", "short_answer"),
                }
                for item in practice_items[:3]
            ]

        # 7b. Call LLM for any missing content
        source_excerpts = "\n\n".join(
            f"[{c.tier}] {c.resource_title}: {c.content_text}"
            for c in source_bundle.chunks[:5]
        )
        if not source_excerpts:
            source_excerpts = "No source materials available."

        mastery_level = 0.5
        if target_concepts:
            mastery_level = float(target_concepts[0].get("mastery_level", 0.5))

        user_prompt = _build_user_prompt(
            concept=primary_concept,
            mastery_level=mastery_level,
            block_type=block_type,
            source_excerpts=source_excerpts,
        )

        prompt_config = get_prompt("guide_compiler")
        try:
            generated = await ai_client.call_structured(
                system=prompt_config.system_prompt,
                user_prompt=user_prompt,
                response_model=GeneratedGuideContent,
                role="guide_compiler",
            )

            # Merge: prefer practice-item warm-ups, fill rest from LLM
            if not warmup_items:
                warmup_items = generated.warmup_items
            if not exit_items:
                exit_items = generated.exit_items
            if not success_criteria:
                success_criteria = generated.success_criteria

            # Store in cache for next time
            cache_content: dict[str, Any] = {
                "warmup_items": warmup_items,
                "exit_items": exit_items,
                "success_criteria": success_criteria,
            }
            await _store_cache(
                client,
                primary_concept,
                source_hash,
                "guide_content",
                cache_content,
            )

        except Exception as exc:
            logger.warning(
                "Guide degraded to generic for block_type=%s (reason=%s)",
                block_type,
                exc,
            )
            degraded = True
    else:
        # ai_client is None -- degrade gracefully
        logger.warning(
            "Guide degraded to generic for block_type=%s (reason=no_ai_client)",
            block_type,
        )
        degraded = True

    # 8. Fill in generic content for any missing pieces
    if degraded or not warmup_items:
        warmup_items = _generic_warmup(primary_concept)
    if degraded or not exit_items:
        exit_items = _generic_exit(primary_concept)
    if degraded or not success_criteria:
        success_criteria = _generic_success_criteria(primary_concept)

    # 9. Assemble BlockGuide
    steps_json = [
        {
            "step_number": step.step_number,
            "instruction_template": step.instruction_template,
            "step_type": step.step_type,
            "requires_artifact": step.requires_artifact,
            "artifact_type": step.artifact_type,
            "time_limit_minutes": step.time_limit_minutes,
        }
        for step in protocol.steps
    ]

    source_bundle_json = [
        {
            "chunk_id": c.chunk_id,
            "content_text": c.content_text,
            "resource_title": c.resource_title,
            "trust_score": c.trust_score,
            "tier": c.tier,
        }
        for c in source_bundle.chunks
    ]

    concepts_json = [
        {
            "concept": c.get("concept", ""),
            "mastery_level": c.get("mastery_level", 0.0),
            "confidence_self_report": c.get("confidence_self_report"),
        }
        for c in target_concepts
    ]

    completion_criteria_json = {
        "required_steps": list(protocol.completion_criteria.required_steps),
        "min_artifacts": protocol.completion_criteria.min_artifacts,
    }

    return BlockGuide(
        block_id=block_id,
        concepts_json=concepts_json,
        source_bundle_json=source_bundle_json,
        steps_json=steps_json,
        warmup_items_json=warmup_items,
        exit_items_json=exit_items,
        completion_criteria_json=completion_criteria_json,
        success_criteria_json=success_criteria,
    )
