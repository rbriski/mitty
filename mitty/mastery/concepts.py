"""LLM-powered concept extraction with pattern-matching fallback.

Reads assignments, modules, resource chunks, and assessments for a course,
then extracts concept/topic tags via an LLM structured-output call.
When the LLM is unavailable (no ai_client, rate-limited, error), falls back
to deterministic pattern matching: chapter numbers, module titles, and
assessment unit_or_topic fields.

Populates mastery_states with initial concept entries (mastery_level=0.5).

Public API:
    extract_concepts(client, ai_client, course_id, user_id) -> list[ConceptExtraction]
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID  # noqa: TCH003 — needed at runtime by Pydantic

import tiktoken
from pydantic import BaseModel

if TYPE_CHECKING:
    from supabase import AsyncClient

    from mitty.ai.client import AIClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models for structured LLM output
# ---------------------------------------------------------------------------


class ConceptExtraction(BaseModel):
    """A single extracted concept/topic tag."""

    name: str
    description: str
    source_type: str  # "assignment", "resource", "assessment", "chunk"


class ConceptExtractionList(BaseModel):
    """Wrapper for LLM structured output — a list of concepts."""

    concepts: list[ConceptExtraction]


# ---------------------------------------------------------------------------
# Token capping
# ---------------------------------------------------------------------------

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Return the cl100k_base encoder, creating it once."""
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _cap_tokens(text: str, *, max_tokens: int = 100) -> str:
    """Truncate *text* to at most *max_tokens* tokens.

    Uses cl100k_base encoding. Returns the original string unchanged
    if it's already within the limit.
    """
    if not text:
        return ""

    enc = _get_encoder()
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text

    return enc.decode(tokens[:max_tokens])


# ---------------------------------------------------------------------------
# Pattern fallback extractors
# ---------------------------------------------------------------------------

# Match "Chapter N", "Ch. N", "chapter N" (case-insensitive)
_CHAPTER_RE = re.compile(r"\b(?:chapter|ch\.?)\s*(\d+)\b", re.IGNORECASE)


def _extract_chapter_numbers(
    assignments: list[dict[str, Any]],
) -> list[ConceptExtraction]:
    """Extract chapter numbers from assignment names.

    Deduplicates by chapter number.
    """
    seen: set[int] = set()
    results: list[ConceptExtraction] = []

    for a in assignments:
        name = a.get("name", "")
        match = _CHAPTER_RE.search(name)
        if match:
            chapter_num = int(match.group(1))
            if chapter_num not in seen:
                seen.add(chapter_num)
                results.append(
                    ConceptExtraction(
                        name=f"Chapter {chapter_num}",
                        description=f"Concepts from chapter {chapter_num}",
                        source_type="assignment",
                    )
                )

    return results


def _extract_module_titles(
    resources: list[dict[str, Any]],
) -> list[ConceptExtraction]:
    """Extract unique module titles from resources.

    Uses the ``module_name`` field, skipping None values.
    Deduplicates by module_name (case-sensitive).
    """
    seen: set[str] = set()
    results: list[ConceptExtraction] = []

    for r in resources:
        module_name = r.get("module_name")
        if module_name and module_name not in seen:
            seen.add(module_name)
            results.append(
                ConceptExtraction(
                    name=module_name,
                    description=f"Topics covered in {module_name}",
                    source_type="resource",
                )
            )

    return results


def _extract_assessment_topics(
    assessments: list[dict[str, Any]],
) -> list[ConceptExtraction]:
    """Extract unique unit_or_topic values from assessments.

    Skips None values. Deduplicates by topic (case-sensitive).
    """
    seen: set[str] = set()
    results: list[ConceptExtraction] = []

    for a in assessments:
        topic = a.get("unit_or_topic")
        if topic and topic not in seen:
            seen.add(topic)
            results.append(
                ConceptExtraction(
                    name=topic,
                    description=f"Assessment topic: {topic}",
                    source_type="assessment",
                )
            )

    return results


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------


def _build_extraction_prompt(
    *,
    assignments: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    resource_chunks: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
) -> str:
    """Build the user prompt for LLM concept extraction.

    Chunk summaries are capped to 100 tokens each for cost control.
    """
    sections: list[str] = []

    if assignments:
        lines = [f"- {a.get('name', '(unnamed)')}" for a in assignments]
        sections.append("## Assignment Names\n" + "\n".join(lines))

    if resources:
        lines = []
        for r in resources:
            title = r.get("title", "(unnamed)")
            module = r.get("module_name", "")
            suffix = f" (module: {module})" if module else ""
            lines.append(f"- {title}{suffix}")
        sections.append("## Resource Titles\n" + "\n".join(lines))

    if resource_chunks:
        lines = []
        for chunk in resource_chunks:
            content = chunk.get("content_text", "")
            capped = _cap_tokens(content, max_tokens=100)
            if capped:
                lines.append(f"- {capped}")
        if lines:
            sections.append("## Resource Chunk Summaries\n" + "\n".join(lines))

    if assessments:
        lines = []
        for a in assessments:
            name = a.get("name", "(unnamed)")
            topic = a.get("unit_or_topic", "")
            atype = a.get("assessment_type", "")
            parts = [name]
            if atype:
                parts.append(f"type={atype}")
            if topic:
                parts.append(f"topic={topic}")
            lines.append(f"- {', '.join(parts)}")
        sections.append("## Assessments\n" + "\n".join(lines))

    return "\n\n".join(sections)


_SYSTEM_PROMPT = """\
You are an educational concept extractor. Given course data (assignment names, \
resource titles, resource chunk summaries, and assessment information), extract \
a list of distinct academic concepts or topics that a student would need to master.

Guidelines:
- Each concept should be a specific, study-able topic (e.g., "Quadratic Equations", \
"Cell Division", "Thermodynamics")
- Avoid overly broad concepts (e.g., "Math") or overly narrow ones
- Include the source_type indicating where the concept was primarily found: \
"assignment", "resource", "assessment", or "chunk"
- Provide a brief 1-sentence description for each concept
- Aim for 5-20 concepts depending on the breadth of course material
- Deduplicate: if the same concept appears across multiple sources, list it once
"""


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


async def _fetch_assignments(
    client: AsyncClient,
    course_id: int,
) -> list[dict[str, Any]]:
    """Fetch assignments for a course."""
    response = await (
        client.table("assignments")
        .select("id, name")
        .eq("course_id", course_id)
        .execute()
    )
    return response.data or []


async def _fetch_resources(
    client: AsyncClient,
    course_id: int,
) -> list[dict[str, Any]]:
    """Fetch resources for a course."""
    response = await (
        client.table("resources")
        .select("id, title, module_name")
        .eq("course_id", course_id)
        .execute()
    )
    return response.data or []


async def _fetch_resource_chunks(
    client: AsyncClient,
    course_id: int,
) -> list[dict[str, Any]]:
    """Fetch resource chunks for a course via joined resources."""
    response = await (
        client.table("resource_chunks")
        .select("content_text, token_count, resources!inner(course_id)")
        .eq("resources.course_id", course_id)
        .execute()
    )
    return response.data or []


async def _fetch_assessments(
    client: AsyncClient,
    course_id: int,
) -> list[dict[str, Any]]:
    """Fetch assessments for a course."""
    response = await (
        client.table("assessments")
        .select("name, unit_or_topic, assessment_type")
        .eq("course_id", course_id)
        .execute()
    )
    return response.data or []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_concepts(
    concepts: list[ConceptExtraction],
) -> list[ConceptExtraction]:
    """Deduplicate concepts by name (case-insensitive).

    Keeps the first occurrence of each lowered name.
    """
    seen: set[str] = set()
    unique: list[ConceptExtraction] = []

    for c in concepts:
        key = c.name.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


# ---------------------------------------------------------------------------
# Mastery state upsert
# ---------------------------------------------------------------------------


async def _upsert_mastery_states(
    client: AsyncClient,
    user_id: UUID,
    course_id: int,
    concepts: list[ConceptExtraction],
) -> None:
    """Upsert initial mastery_states rows for extracted concepts.

    Uses on_conflict="user_id,course_id,concept" to avoid duplicates.
    Sets initial mastery_level=0.5 and retrieval_count=0.
    """
    if not concepts:
        return

    now = datetime.now(UTC).isoformat()
    rows = [
        {
            "user_id": str(user_id),
            "course_id": course_id,
            "concept": c.name,
            "mastery_level": 0.5,
            "retrieval_count": 0,
            "updated_at": now,
        }
        for c in concepts
    ]

    await (
        client.table("mastery_states")
        .upsert(rows, on_conflict="user_id,course_id,concept")
        .execute()
    )

    logger.info(
        "Upserted %d mastery_state entries for user=%s course=%d",
        len(rows),
        user_id,
        course_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_concepts(
    *,
    client: AsyncClient,
    ai_client: AIClient | None,
    course_id: int,
    user_id: UUID,
) -> list[ConceptExtraction]:
    """Extract concept/topic tags from course data.

    Reads assignments, resources, resource chunks, and assessments from
    Supabase. If *ai_client* is provided, sends a batched LLM prompt for
    structured concept extraction. Falls back to pattern matching when
    the LLM is unavailable or errors out.

    After extraction, upserts initial mastery_states rows with
    mastery_level=0.5.

    Args:
        client: Async Supabase client.
        ai_client: Optional AIClient for LLM extraction.
        course_id: The course to extract concepts for.
        user_id: The student's user ID.

    Returns:
        Deduplicated list of ConceptExtraction objects.
    """
    # 1. Fetch course data in parallel-ish (sequential for simplicity).
    assignments = await _fetch_assignments(client, course_id)
    resources = await _fetch_resources(client, course_id)
    resource_chunks = await _fetch_resource_chunks(client, course_id)
    assessments = await _fetch_assessments(client, course_id)

    logger.info(
        "Fetched course data for concept extraction: "
        "assignments=%d resources=%d chunks=%d assessments=%d",
        len(assignments),
        len(resources),
        len(resource_chunks),
        len(assessments),
    )

    concepts: list[ConceptExtraction] | None = None

    # 2. Try LLM extraction.
    if ai_client is not None:
        try:
            prompt = _build_extraction_prompt(
                assignments=assignments,
                resources=resources,
                resource_chunks=resource_chunks,
                assessments=assessments,
            )

            if prompt.strip():
                result = await ai_client.call_structured(
                    system=_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    response_model=ConceptExtractionList,
                )
                concepts = result.concepts
                logger.info("LLM extracted %d concepts", len(concepts))

        except Exception:
            logger.warning(
                "LLM concept extraction failed, falling back to patterns",
                exc_info=True,
            )
            concepts = None

    # 3. Fallback to pattern matching.
    if concepts is None:
        logger.info("Using pattern-based concept extraction fallback")
        concepts = []
        concepts.extend(_extract_chapter_numbers(assignments))
        concepts.extend(_extract_module_titles(resources))
        concepts.extend(_extract_assessment_topics(assessments))

    # 4. Deduplicate.
    concepts = _deduplicate_concepts(concepts)

    # 5. Upsert mastery states.
    await _upsert_mastery_states(client, user_id, course_id, concepts)

    logger.info(
        "Extracted %d unique concepts for course=%d",
        len(concepts),
        course_id,
    )

    return concepts
