"""Tests for mitty.guides.sources — tiered source bundle builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.ai.retriever import RetrievalResult, RetrievedChunk
from mitty.guides.sources import (
    DEFAULT_TIER,
    MIN_SOURCE_CHUNKS,
    TIER_MAP,
    SourceBundle,
    TieredChunk,
    build_source_bundle,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: int,
    *,
    resource_id: int = 100,
    content: str = "some content",
    title: str = "Resource",
    trust: float = 0.7,
    rank: float = 1.0,
) -> RetrievedChunk:
    """Build a RetrievedChunk for testing."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        content_text=content,
        resource_id=resource_id,
        resource_title=title,
        trust_score=trust,
        rank=rank,
    )


def _make_resource_lookup_client(
    type_map: dict[int, str],
) -> AsyncMock:
    """Create a mock Supabase client that returns resource types.

    The client supports the chain: table("resources").select(...).in_(...).execute()
    """
    rows = [{"id": rid, "resource_type": rtype} for rid, rtype in type_map.items()]
    execute_result = MagicMock()
    execute_result.data = rows

    chain = AsyncMock()
    chain.execute = AsyncMock(return_value=execute_result)
    chain.in_ = MagicMock(return_value=chain)
    chain.select = MagicMock(return_value=chain)

    client = AsyncMock()
    client.table = MagicMock(return_value=chain)
    return client


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestBuildSourceBundleHappyPath:
    @pytest.mark.asyncio
    async def test_returns_tiered_chunks(self) -> None:
        """Happy path: multiple concepts yield a SourceBundle with tiered chunks."""
        chunks = [
            _make_chunk(1, resource_id=10, trust=1.0, rank=1.0),
            _make_chunk(2, resource_id=11, trust=0.7, rank=2.0),
            _make_chunk(3, resource_id=12, trust=0.5, rank=3.0),
            _make_chunk(4, resource_id=13, trust=0.3, rank=4.0),
        ]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)

        type_map = {
            10: "canvas_page",
            11: "file",
            12: "discussion",
            13: "web_link",
        }
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(
                client, course_id=1, concepts=["photosynthesis"]
            )

        assert isinstance(bundle, SourceBundle)
        assert len(bundle.chunks) == 4
        assert all(isinstance(c, TieredChunk) for c in bundle.chunks)
        assert bundle.needs_resources is False

    @pytest.mark.asyncio
    async def test_tier_counts_populated(self) -> None:
        chunks = [
            _make_chunk(1, resource_id=10, trust=1.0),
            _make_chunk(2, resource_id=11, trust=0.7),
            _make_chunk(3, resource_id=12, trust=0.5),
            _make_chunk(4, resource_id=13, trust=0.3),
        ]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)

        type_map = {
            10: "canvas_page",
            11: "file",
            12: "discussion",
            13: "web_link",
        }
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(
                client, course_id=1, concepts=["photosynthesis"]
            )

        assert bundle.tier_counts == {
            "teacher": 2,
            "supplementary": 1,
            "external": 1,
        }


# ---------------------------------------------------------------------------
# needs_resources flag
# ---------------------------------------------------------------------------


class TestNeedsResources:
    @pytest.mark.asyncio
    async def test_true_when_below_threshold(self) -> None:
        """needs_resources=True when total chunks < MIN_SOURCE_CHUNKS."""
        chunks = [
            _make_chunk(1, resource_id=10, trust=1.0),
            _make_chunk(2, resource_id=11, trust=0.7),
        ]
        assert len(chunks) < MIN_SOURCE_CHUNKS

        retrieval = RetrievalResult(chunks=chunks, sufficient=True)
        type_map = {10: "canvas_page", 11: "file"}
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        assert bundle.needs_resources is True
        assert len(bundle.chunks) == 2

    @pytest.mark.asyncio
    async def test_false_when_sufficient(self) -> None:
        """needs_resources=False when total chunks >= MIN_SOURCE_CHUNKS."""
        chunks = [
            _make_chunk(i, resource_id=10 + i, trust=0.7)
            for i in range(1, MIN_SOURCE_CHUNKS + 1)
        ]
        assert len(chunks) >= MIN_SOURCE_CHUNKS

        retrieval = RetrievalResult(chunks=chunks, sufficient=True)
        type_map = {10 + i: "file" for i in range(1, MIN_SOURCE_CHUNKS + 1)}
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        assert bundle.needs_resources is False
        assert len(bundle.chunks) == MIN_SOURCE_CHUNKS

    @pytest.mark.asyncio
    async def test_true_when_exactly_at_threshold(self) -> None:
        """needs_resources=False when chunks == MIN_SOURCE_CHUNKS (boundary)."""
        chunks = [
            _make_chunk(i, resource_id=10 + i, trust=0.7)
            for i in range(1, MIN_SOURCE_CHUNKS + 1)
        ]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)
        type_map = {10 + i: "file" for i in range(1, MIN_SOURCE_CHUNKS + 1)}
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        assert bundle.needs_resources is False


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestChunkSorting:
    @pytest.mark.asyncio
    async def test_sorted_by_tier_then_trust(self) -> None:
        """Chunks sort by tier (teacher > supplementary > external), then
        by trust_score descending within the same tier."""
        chunks = [
            _make_chunk(1, resource_id=10, trust=0.3, rank=1.0),  # external
            _make_chunk(2, resource_id=11, trust=0.5, rank=2.0),  # supplementary
            _make_chunk(3, resource_id=12, trust=1.0, rank=3.0),  # teacher
            _make_chunk(4, resource_id=13, trust=0.7, rank=4.0),  # teacher
        ]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)

        type_map = {
            10: "web_link",  # external
            11: "discussion",  # supplementary
            12: "canvas_page",  # teacher
            13: "file",  # teacher
        }
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        tiers = [c.tier for c in bundle.chunks]
        assert tiers == ["teacher", "teacher", "supplementary", "external"]

        # Within teacher tier, canvas_page (trust=1.0) should come before
        # file (trust=0.7).
        teacher_chunks = [c for c in bundle.chunks if c.tier == "teacher"]
        assert teacher_chunks[0].trust_score >= teacher_chunks[1].trust_score

    @pytest.mark.asyncio
    async def test_multiple_chunks_same_tier_sorted_by_trust_desc(self) -> None:
        """Within a single tier, higher trust_score comes first."""
        chunks = [
            _make_chunk(1, resource_id=10, trust=0.5),
            _make_chunk(2, resource_id=11, trust=0.9),
            _make_chunk(3, resource_id=12, trust=0.7),
        ]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)

        # All supplementary
        type_map = {10: "discussion", 11: "discussion", 12: "discussion"}
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        scores = [c.trust_score for c in bundle.chunks]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Empty retrieval
# ---------------------------------------------------------------------------


class TestEmptyRetrieval:
    @pytest.mark.asyncio
    async def test_empty_retrieval_returns_empty_bundle(self) -> None:
        """When retriever finds nothing, return an empty bundle."""
        retrieval = RetrievalResult(chunks=[], sufficient=False)
        client = _make_resource_lookup_client({})

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(
                client, course_id=1, concepts=["unknown topic"]
            )

        assert bundle.chunks == []
        assert bundle.needs_resources is True
        assert bundle.tier_counts == {}

    @pytest.mark.asyncio
    async def test_empty_concepts_returns_empty_bundle(self) -> None:
        """When no concepts are provided, return an empty bundle."""
        client = _make_resource_lookup_client({})

        bundle = await build_source_bundle(client, course_id=1, concepts=[])

        assert bundle.chunks == []
        assert bundle.needs_resources is True


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_deduplicates_chunks_across_concepts(self) -> None:
        """Same chunk returned for two concepts is included only once."""
        shared_chunk = _make_chunk(
            1, resource_id=10, content="shared content", trust=1.0
        )
        unique_chunk = _make_chunk(
            2, resource_id=11, content="unique content", trust=0.7
        )

        result_a = RetrievalResult(chunks=[shared_chunk, unique_chunk], sufficient=True)
        result_b = RetrievalResult(chunks=[shared_chunk], sufficient=True)

        type_map = {10: "canvas_page", 11: "file"}
        client = _make_resource_lookup_client(type_map)

        mock_retrieve = AsyncMock(side_effect=[result_a, result_b])

        with patch("mitty.guides.sources.retrieve", mock_retrieve):
            bundle = await build_source_bundle(
                client, course_id=1, concepts=["concept A", "concept B"]
            )

        assert len(bundle.chunks) == 2
        ids = {c.chunk_id for c in bundle.chunks}
        assert ids == {1, 2}

    @pytest.mark.asyncio
    async def test_retrieve_called_per_concept(self) -> None:
        """retrieve() is called once for each concept."""
        retrieval = RetrievalResult(
            chunks=[_make_chunk(1, resource_id=10)], sufficient=True
        )
        type_map = {10: "canvas_page"}
        client = _make_resource_lookup_client(type_map)

        mock_retrieve = AsyncMock(return_value=retrieval)

        with patch("mitty.guides.sources.retrieve", mock_retrieve):
            await build_source_bundle(client, course_id=1, concepts=["a", "b", "c"])

        assert mock_retrieve.call_count == 3


# ---------------------------------------------------------------------------
# Tier assignment by resource type
# ---------------------------------------------------------------------------


class TestTierAssignment:
    @pytest.mark.asyncio
    async def test_tier_assignment_by_resource_type(self) -> None:
        """Each resource type maps to the correct tier."""
        test_cases: list[tuple[str, str]] = [
            ("canvas_page", "teacher"),
            ("file", "teacher"),
            ("discussion", "supplementary"),
            ("textbook", "supplementary"),
            ("textbook_chapter", "supplementary"),
            ("notes", "supplementary"),
            ("canvas_assignment", "supplementary"),
            ("canvas_quiz", "supplementary"),
            ("link", "external"),
            ("video", "external"),
            ("web_link", "external"),
        ]

        for resource_type, expected_tier in test_cases:
            chunks = [_make_chunk(1, resource_id=10, trust=0.7)]
            retrieval = RetrievalResult(chunks=chunks, sufficient=True)
            type_map = {10: resource_type}
            client = _make_resource_lookup_client(type_map)

            with patch(
                "mitty.guides.sources.retrieve",
                new_callable=AsyncMock,
                return_value=retrieval,
            ):
                bundle = await build_source_bundle(
                    client, course_id=1, concepts=["topic"]
                )

            assert bundle.chunks[0].tier == expected_tier, (
                f"resource_type={resource_type!r}: "
                f"expected tier={expected_tier!r}, "
                f"got {bundle.chunks[0].tier!r}"
            )

    @pytest.mark.asyncio
    async def test_unknown_resource_type_gets_default_tier(self) -> None:
        """Unknown resource types receive the default tier."""
        chunks = [_make_chunk(1, resource_id=10, trust=0.5)]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)
        type_map = {10: "unknown_type_xyz"}
        client = _make_resource_lookup_client(type_map)

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        assert bundle.chunks[0].tier == DEFAULT_TIER

    @pytest.mark.asyncio
    async def test_missing_resource_type_lookup_gets_default_tier(self) -> None:
        """When resource type lookup fails (empty result), default tier is used."""
        chunks = [_make_chunk(1, resource_id=10, trust=0.5)]
        retrieval = RetrievalResult(chunks=chunks, sufficient=True)
        # Empty type map — simulates lookup returning nothing
        client = _make_resource_lookup_client({})

        with patch(
            "mitty.guides.sources.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ):
            bundle = await build_source_bundle(client, course_id=1, concepts=["topic"])

        assert bundle.chunks[0].tier == DEFAULT_TIER


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_min_source_chunks_is_three(self) -> None:
        assert MIN_SOURCE_CHUNKS == 3

    def test_tier_map_covers_expected_types(self) -> None:
        assert "canvas_page" in TIER_MAP
        assert "file" in TIER_MAP
        assert "discussion" in TIER_MAP
        assert "web_link" in TIER_MAP
        assert "link" in TIER_MAP

    def test_tiered_chunk_is_frozen(self) -> None:
        chunk = TieredChunk(
            chunk_id=1,
            content_text="text",
            resource_id=10,
            resource_title="Title",
            trust_score=0.7,
            tier="teacher",
            rank=1.0,
        )
        with pytest.raises(AttributeError):
            chunk.tier = "external"  # type: ignore[misc]

    def test_source_bundle_is_frozen(self) -> None:
        bundle = SourceBundle()
        with pytest.raises(AttributeError):
            bundle.needs_resources = False  # type: ignore[misc]
