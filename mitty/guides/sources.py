"""Source bundle builder with tiered retrieval.

Assembles a :class:`SourceBundle` for a given course and list of concepts
by calling the existing FTS retriever and organising results into trust
tiers: **teacher** (highest), **supplementary**, **external** (lowest).

Public API:
    build_source_bundle(client, course_id, concepts, *, top_k) -> SourceBundle
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from mitty.ai.retriever import retrieve

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_SOURCE_CHUNKS: int = 3
"""Minimum chunks required before the bundle is considered sufficient."""

TIER_ORDER: dict[str, int] = {
    "teacher": 0,
    "supplementary": 1,
    "external": 2,
}
"""Sort priority for tiers (lower = higher priority)."""

TIER_MAP: dict[str, str] = {
    # Teacher-authored / authoritative — highest trust
    "canvas_page": "teacher",
    "file": "teacher",
    # Supplementary — moderate trust
    "discussion": "supplementary",
    "textbook": "supplementary",
    "textbook_chapter": "supplementary",
    "notes": "supplementary",
    "canvas_assignment": "supplementary",
    "canvas_quiz": "supplementary",
    "student_notes": "supplementary",
    # External — lowest trust
    "link": "external",
    "video": "external",
    "web_link": "external",
}
"""Maps resource_type to tier name."""

DEFAULT_TIER: str = "supplementary"
"""Tier assigned to resource types not present in :data:`TIER_MAP`."""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TieredChunk:
    """A resource chunk annotated with its trust tier."""

    chunk_id: int
    content_text: str
    resource_id: int
    resource_title: str
    trust_score: float
    tier: Literal["teacher", "supplementary", "external"]
    rank: float


@dataclass(frozen=True, slots=True)
class SourceBundle:
    """Tiered collection of source chunks for guide compilation."""

    chunks: list[TieredChunk] = field(default_factory=list)
    needs_resources: bool = True
    tier_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Resource type lookup
# ---------------------------------------------------------------------------


async def _lookup_resource_types(
    client: AsyncClient,
    resource_ids: list[int],
) -> dict[int, str]:
    """Query the resources table for resource_type by resource_id.

    Returns a mapping of ``{resource_id: resource_type}``.
    """
    if not resource_ids:
        return {}

    try:
        result = await (
            client.table("resources")
            .select("id, resource_type")
            .in_("id", resource_ids)
            .execute()
        )
        return {row["id"]: row.get("resource_type", "") for row in (result.data or [])}
    except Exception:
        logger.warning(
            "Failed to look up resource types for %d resource(s)",
            len(resource_ids),
            exc_info=True,
        )
        return {}


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------


async def build_source_bundle(
    client: AsyncClient,
    course_id: int,
    concepts: list[str],
    *,
    top_k: int = 10,
) -> SourceBundle:
    """Build a tiered source bundle for the given course and concepts.

    For each concept, calls the existing FTS :func:`retrieve` function,
    deduplicates chunks across concepts, looks up resource types to assign
    tiers, and sorts by tier priority then trust score descending.

    Args:
        client: Async Supabase client.
        course_id: Course to retrieve sources from.
        concepts: List of concept strings to search for.
        top_k: Maximum chunks per concept query.

    Returns:
        A :class:`SourceBundle` with tiered chunks and a
        ``needs_resources`` flag when fewer than :data:`MIN_SOURCE_CHUNKS`
        chunks are found.
    """
    if not concepts:
        return SourceBundle(
            chunks=[],
            needs_resources=True,
            tier_counts={},
        )

    # Retrieve chunks for each concept and deduplicate by chunk_id.
    seen_ids: set[int] = set()
    unique_chunks: list[tuple[int, str, int, str, float, float]] = []

    for concept in concepts:
        result = await retrieve(client, course_id, concept, top_k=top_k, min_results=0)
        for chunk in result.chunks:
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                unique_chunks.append(
                    (
                        chunk.chunk_id,
                        chunk.content_text,
                        chunk.resource_id,
                        chunk.resource_title,
                        chunk.trust_score,
                        chunk.rank,
                    )
                )

    if not unique_chunks:
        return SourceBundle(
            chunks=[],
            needs_resources=True,
            tier_counts={},
        )

    # Look up resource types so we can assign tiers.
    resource_ids = list({c[2] for c in unique_chunks})
    type_map = await _lookup_resource_types(client, resource_ids)

    # Build TieredChunks with tier assignment.
    tiered: list[TieredChunk] = []
    for chunk_id, content, res_id, res_title, trust, rank in unique_chunks:
        resource_type = type_map.get(res_id, "")
        tier = TIER_MAP.get(resource_type, DEFAULT_TIER)
        tiered.append(
            TieredChunk(
                chunk_id=chunk_id,
                content_text=content,
                resource_id=res_id,
                resource_title=res_title,
                trust_score=trust,
                tier=tier,
                rank=rank,
            )
        )

    # Sort: tier order (teacher first), then trust_score descending.
    tiered.sort(key=lambda c: (TIER_ORDER.get(c.tier, 99), -c.trust_score))

    # Compute tier counts.
    tier_counts: dict[str, int] = {}
    for chunk in tiered:
        tier_counts[chunk.tier] = tier_counts.get(chunk.tier, 0) + 1

    needs_resources = len(tiered) < MIN_SOURCE_CHUNKS

    return SourceBundle(
        chunks=tiered,
        needs_resources=needs_resources,
        tier_counts=tier_counts,
    )
