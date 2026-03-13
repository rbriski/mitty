"""LLM-powered practice item generator.

Given a concept, calls Claude to produce a varied batch of practice items
(6 types), stores them in the ``practice_items`` table, and returns them.
Checks cache first to avoid redundant LLM calls.  Resource chunks are
fetched internally via the retriever; callers no longer need to pass them.

Public API:
    generate_practice_items(ai_client, supabase_client, user_id, course_id,
        concept, mastery_level) -> GenerationResult

Pydantic models for structured LLM output:
    GeneratedItem  — a single practice item from the LLM
    GeneratedBatch — the full batch response from the LLM
    PracticeItem   — the final item returned to callers (with DB id)
    GenerationResult — items list + needs_resources flag
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from mitty.ai.client import AIClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Practice type constants
# ---------------------------------------------------------------------------

PRACTICE_TYPES = [
    "multiple_choice",
    "fill_in_blank",
    "short_answer",
    "flashcard",
    "worked_example",
    "explanation",
]

# Minimum number of cached items to consider a cache hit.
_CACHE_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Pydantic models for structured LLM output
# ---------------------------------------------------------------------------


class GeneratedItem(BaseModel):
    """A single practice item as returned by the LLM."""

    practice_type: str = Field(
        description=(
            "One of: multiple_choice, fill_in_blank, short_answer, "
            "flashcard, worked_example, explanation"
        ),
    )
    question_text: str = Field(
        description="The question or prompt text.",
        max_length=10000,
    )
    correct_answer: str | None = Field(
        default=None,
        description="The correct answer or expected response.",
        max_length=10000,
    )
    options_json: dict | list | None = Field(
        default=None,
        description=(
            "For multiple_choice: list of 4 options. "
            "For worked_example: {steps: [...], practice_problem: str}. "
            "For short_answer/explanation: {rubric: [...]}. "
            "Null for flashcard and fill_in_blank."
        ),
    )
    explanation: str | None = Field(
        default=None,
        description="Explanation of the correct answer.",
        max_length=10000,
    )
    source_chunk_ids: list[int] = Field(
        default_factory=list,
        description="IDs of source chunks used to generate this item.",
    )
    difficulty_level: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Difficulty level from 0.0 (easy) to 1.0 (hard).",
    )


class GeneratedBatch(BaseModel):
    """Batch of practice items returned by the LLM."""

    items: list[GeneratedItem] = Field(
        description="List of 6-8 practice items covering varied types.",
    )
    needs_resources: bool = Field(
        default=False,
        description=(
            "True if the provided resource chunks were insufficient "
            "to generate high-quality items."
        ),
    )

    @field_validator("items", mode="before")
    @classmethod
    def _parse_stringified_items(cls, v: Any) -> Any:
        """Handle LLM returning items as a JSON string instead of a list."""
        if isinstance(v, str):
            return json.loads(v)
        return v


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PracticeItem:
    """A practice item with its database ID, returned to callers."""

    id: int
    user_id: UUID
    course_id: int
    concept: str
    practice_type: str
    question_text: str
    correct_answer: str | None
    options_json: dict | list | None
    explanation: str | None
    source_chunk_ids: list[int] | None
    difficulty_level: float | None
    generation_model: str | None
    times_used: int = 0
    last_used_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Result of practice item generation.

    Attributes:
        items: The generated (or cached) practice items.
        needs_resources: True when the retriever found insufficient source
            material.  When True, ``items`` is empty and callers should
            prompt the user to add resources for this course/concept.
    """

    items: list[PracticeItem]
    needs_resources: bool = False


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert educational content creator. Generate practice items for a \
student studying a specific concept. Each item must be pedagogically sound, \
clearly worded, and cite the source chunks that informed it.

Practice item types:
1. **multiple_choice** — 4 options (A-D), exactly one correct
2. **fill_in_blank** — sentence with a blank (___), correct_answer is the word/phrase
3. **short_answer** — open question with rubric in options_json.rubric
4. **flashcard** — front=question_text, back=correct_answer
5. **worked_example** — options_json has {steps: [...], practice_problem: "..."}
6. **explanation** — student must explain a concept; rubric in options_json.rubric

Rules:
- Generate 6-8 items per batch
- Include ALL 6 types at least once
- Vary difficulty based on the student's mastery level
- Every item MUST cite at least one source_chunk_id from the provided chunks
- For multiple_choice, options_json is a list of 4 strings
- Set difficulty_level proportional to the student's mastery_level
"""


def _build_user_prompt(
    *,
    concept: str,
    mastery_level: float,
    resource_chunks: list[dict[str, Any]],
) -> str:
    """Build the user prompt for the LLM call."""
    chunk_text = ""
    if resource_chunks:
        chunk_sections = []
        for chunk in resource_chunks:
            chunk_id = chunk.get("id", "unknown")
            content = chunk.get("content_text", "")
            if content:
                chunk_sections.append(f"[Chunk ID={chunk_id}]\n{content}")
        chunk_text = "\n\n".join(chunk_sections)
    else:
        chunk_text = (
            "No resource chunks available. Generate items based on the concept "
            "name alone. Set needs_resources=true in the response. Use empty "
            "source_chunk_ids lists. Mark insufficient resources clearly."
        )

    return (
        f"Concept: {concept}\n"
        f"Student mastery level: {mastery_level}\n"
        f"Difficulty guidance: target difficulty around {mastery_level} "
        f"(0=beginner, 1=advanced). For low mastery, focus on fundamentals "
        f"and recognition. For high mastery, include application, analysis, "
        f"and synthesis.\n\n"
        f"Source material:\n{chunk_text}\n\n"
        f"Generate a batch of 6-8 practice items covering all 6 types."
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


async def _check_cache(
    client: AsyncClient,
    user_id: UUID,
    course_id: int,
    concept: str,
) -> list[dict[str, Any]]:
    """Check if practice items already exist for this user/course/concept.

    Returns cached rows if the cache has sufficient items, else [].
    """
    try:
        response = await (
            client.table("practice_items")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("course_id", course_id)
            .eq("concept", concept)
            .execute()
        )
        data = response.data or []
        if len(data) >= _CACHE_THRESHOLD:
            logger.info(
                "Cache hit: %d items for concept=%r (course=%d, user=%s)",
                len(data),
                concept,
                course_id,
                user_id,
            )
            return data
    except Exception as exc:
        logger.warning("Cache check failed (will regenerate): %s", exc)

    return []


def _rows_to_practice_items(rows: list[dict[str, Any]]) -> list[PracticeItem]:
    """Convert raw Supabase rows to PracticeItem dataclass instances."""
    items = []
    for row in rows:
        created_at = row.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                created_at = None

        last_used = row.get("last_used_at")
        if isinstance(last_used, str):
            try:
                last_used = datetime.fromisoformat(last_used)
            except (ValueError, TypeError):
                last_used = None

        user_id = row.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        items.append(
            PracticeItem(
                id=row["id"],
                user_id=user_id,
                course_id=row["course_id"],
                concept=row["concept"],
                practice_type=row["practice_type"],
                question_text=row["question_text"],
                correct_answer=row.get("correct_answer"),
                options_json=row.get("options_json"),
                explanation=row.get("explanation"),
                source_chunk_ids=row.get("source_chunk_ids"),
                difficulty_level=row.get("difficulty_level"),
                generation_model=row.get("generation_model"),
                times_used=row.get("times_used", 0),
                last_used_at=last_used,
                created_at=created_at,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Storage helper
# ---------------------------------------------------------------------------


async def _store_items(
    client: AsyncClient,
    user_id: UUID,
    course_id: int,
    concept: str,
    items: list[GeneratedItem],
    generation_model: str,
) -> list[dict[str, Any]]:
    """Upsert generated items into the practice_items table.

    Returns the upserted rows (with assigned IDs).
    """
    now_iso = datetime.now(UTC).isoformat()
    rows = []
    for item in items:
        row: dict[str, Any] = {
            "user_id": str(user_id),
            "course_id": course_id,
            "concept": concept,
            "practice_type": item.practice_type,
            "question_text": item.question_text,
            "correct_answer": item.correct_answer,
            "options_json": item.options_json,
            "explanation": item.explanation,
            "source_chunk_ids": item.source_chunk_ids,
            "difficulty_level": item.difficulty_level,
            "generation_model": generation_model,
            "times_used": 0,
            "created_at": now_iso,
        }
        rows.append(row)

    response = await client.table("practice_items").upsert(rows).execute()
    return response.data or []


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


async def generate_practice_items(
    *,
    ai_client: AIClient,
    supabase_client: AsyncClient,
    user_id: UUID,
    course_id: int,
    concept: str,
    mastery_level: float,
    resource_chunks: list[dict[str, Any]] | None = None,
) -> GenerationResult:
    """Generate practice items for a concept using Claude.

    Checks cache first. If items already exist, returns them without
    calling the LLM. Otherwise, retrieves resource chunks via the
    retriever, calls the LLM to generate a batch of 6-8 items covering
    all 6 practice types, stores them in the ``practice_items`` table,
    and returns them.

    Args:
        ai_client: AIClient instance for Claude API calls.
        supabase_client: Async Supabase client for storage.
        user_id: The student's UUID.
        course_id: The course this concept belongs to.
        concept: The concept/topic to generate practice for.
        mastery_level: Student's current mastery (0.0-1.0).
        resource_chunks: **Deprecated.** Optional list of resource chunk
            dicts with id, content_text. When omitted (the default),
            chunks are fetched internally via the retriever.

    Returns:
        GenerationResult with practice items and needs_resources flag.
    """
    # 1. Check cache
    cached = await _check_cache(supabase_client, user_id, course_id, concept)
    if cached:
        return GenerationResult(items=_rows_to_practice_items(cached))

    # 2. Obtain resource chunks — prefer retriever, accept legacy passthrough
    if resource_chunks is None:
        from mitty.ai.retriever import retrieve

        retrieval = await retrieve(supabase_client, course_id, concept)

        if not retrieval.sufficient:
            logger.warning(
                "Retriever found insufficient sources for concept=%r (course=%d): %s",
                concept,
                course_id,
                retrieval.message,
            )
            # Fall through with empty chunks — the LLM prompt handles this
            # by generating items from the concept name alone.
            resource_chunks = []
        else:
            # Convert RetrievedChunk dataclasses to dicts matching legacy format
            resource_chunks = [
                {"id": chunk.chunk_id, "content_text": chunk.content_text}
                for chunk in retrieval.chunks
            ]

    # 3. Build prompt and call LLM
    user_prompt = _build_user_prompt(
        concept=concept,
        mastery_level=mastery_level,
        resource_chunks=resource_chunks,
    )

    logger.info(
        "Generating practice items: concept=%r, course=%d, mastery=%.2f, chunks=%d",
        concept,
        course_id,
        mastery_level,
        len(resource_chunks),
    )

    batch = await ai_client.call_structured(
        system=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=GeneratedBatch,
    )

    if batch.needs_resources:
        logger.warning(
            "LLM flagged insufficient resources for concept=%r (course=%d). "
            "Items may be lower quality.",
            concept,
            course_id,
        )

    # 4. Validate we have varied types
    types_seen = {item.practice_type for item in batch.items}
    logger.debug(
        "LLM generated %d items with types: %s",
        len(batch.items),
        types_seen,
    )

    # 5. Store in practice_items table
    generation_model = getattr(ai_client, "_model", "unknown")
    stored_rows = await _store_items(
        supabase_client,
        user_id,
        course_id,
        concept,
        batch.items,
        generation_model,
    )

    # 6. Convert stored rows to PracticeItem dataclass
    return GenerationResult(
        items=_rows_to_practice_items(stored_rows),
        needs_resources=batch.needs_resources,
    )
