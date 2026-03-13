"""Postgres full-text search retriever for resource chunks.

Searches ``resource_chunks`` via the ``search_vector`` tsvector column
(with GIN index) and returns top-k chunks with source attribution and
trust scores.  When too few results are found, the retrieval is marked
as insufficient so callers can refuse gracefully.

Public API:
    retrieve(client, course_id, query, *, top_k, min_results) -> RetrievalResult
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mitty.ai.trust import get_trust_score

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievedChunk:
    """A single resource chunk returned by the retriever."""

    chunk_id: int
    content_text: str
    resource_id: int
    resource_title: str
    trust_score: float
    rank: float  # FTS rank score (position-based; lower = better match)


@dataclass(frozen=True)
class RetrievalResult:
    """The full result of a retrieval query."""

    chunks: list[RetrievedChunk] = field(default_factory=list)
    sufficient: bool = False
    message: str | None = None


# ---------------------------------------------------------------------------
# Query sanitisation
# ---------------------------------------------------------------------------

# Remove characters that are special in tsquery syntax so `.text_search()`
# receives a plain string it can safely convert via ``plainto_tsquery``.
_TSQUERY_SPECIAL = re.compile(r"[&|!<>():*\\]")


def _sanitize_query(query: str) -> str:
    """Strip tsquery operators and collapse whitespace."""
    cleaned = _TSQUERY_SPECIAL.sub(" ", query)
    return " ".join(cleaned.split())


def _escape_like(query: str) -> str:
    """Escape LIKE/ILIKE wildcard characters (``%`` and ``_``) in *query*.

    Must be applied before embedding in a ``%…%`` pattern so user input
    cannot inject wildcards that match unintended rows.
    """
    return query.replace("%", r"\%").replace("_", r"\_")


# ---------------------------------------------------------------------------
# Core retrieval
# ---------------------------------------------------------------------------


async def retrieve(
    client: AsyncClient,
    course_id: int,
    query: str,
    *,
    top_k: int = 10,
    min_results: int = 3,
) -> RetrievalResult:
    """Search resource chunks via Postgres full-text search.

    Args:
        client: Async Supabase client.
        course_id: Only return chunks from resources in this course.
        query: Natural-language search query.
        top_k: Maximum number of chunks to return.
        min_results: Minimum results required to consider the retrieval
            sufficient.  Below this threshold the result is marked
            insufficient and ``chunks`` is empty.

    Returns:
        A :class:`RetrievalResult` with ranked chunks and a sufficiency
        flag.
    """
    sanitized = _sanitize_query(query)
    if not sanitized.strip():
        return RetrievalResult(
            chunks=[],
            sufficient=False,
            message=(
                "No study materials found for this topic. "
                "Add resources to enable practice."
            ),
        )

    rows = await _fts_query(client, course_id, sanitized, top_k)

    if not rows:
        return RetrievalResult(
            chunks=[],
            sufficient=False,
            message=(
                "No study materials found for this topic. "
                "Add resources to enable practice."
            ),
        )

    chunks = _rows_to_chunks(rows)

    if len(chunks) < min_results:
        return RetrievalResult(
            chunks=[],
            sufficient=False,
            message="No study materials for this topic",
        )

    # Sort: primary by rank (ascending = better), secondary by trust (descending).
    chunks.sort(key=lambda c: (c.rank, -c.trust_score))

    return RetrievalResult(
        chunks=chunks,
        sufficient=True,
        message=None,
    )


# ---------------------------------------------------------------------------
# Supabase FTS helper
# ---------------------------------------------------------------------------


async def _fts_query(
    client: AsyncClient,
    course_id: int,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Execute the full-text search query against Supabase.

    Uses ``.text_search()`` on the ``search_vector`` column with the
    ``english`` config.  Falls back to ``.ilike()`` if the FTS call
    raises an unexpected error.
    """
    try:
        result = await (
            client.table("resource_chunks")
            .select(
                "id, content_text, resource_id, "
                "resources!inner(title, resource_type, course_id)"
            )
            .text_search("search_vector", query, config="english")
            .eq("resources.course_id", course_id)
            .limit(top_k)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.warning(
            "text_search failed, falling back to ilike for query=%r",
            query,
            exc_info=True,
        )

    # Fallback: simple ILIKE match on content_text.
    try:
        pattern = f"%{_escape_like(query)}%"
        result = await (
            client.table("resource_chunks")
            .select(
                "id, content_text, resource_id, "
                "resources!inner(title, resource_type, course_id)"
            )
            .ilike("content_text", pattern)
            .eq("resources.course_id", course_id)
            .limit(top_k)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.error(
            "ilike fallback also failed for query=%r",
            query,
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Row conversion
# ---------------------------------------------------------------------------


def _rows_to_chunks(rows: list[dict[str, Any]]) -> list[RetrievedChunk]:
    """Convert raw Supabase rows to :class:`RetrievedChunk` instances."""
    chunks: list[RetrievedChunk] = []
    for idx, row in enumerate(rows):
        resource_info = row.get("resources", {})
        resource_type = resource_info.get("resource_type", "")
        trust = get_trust_score(resource_type)
        chunks.append(
            RetrievedChunk(
                chunk_id=row["id"],
                content_text=row["content_text"],
                resource_id=row["resource_id"],
                resource_title=resource_info.get("title", ""),
                trust_score=trust,
                # Supabase text_search returns results in ranked order;
                # use 1-based position as a synthetic rank score.
                rank=float(idx + 1),
            )
        )
    return chunks
