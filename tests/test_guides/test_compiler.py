"""Tests for mitty.guides.compiler — guide compiler + LLM orchestration.

Covers: happy path (all 6 block types), cache hit skips LLM, cache write
after LLM call, graceful degradation on LLM failure, no AI client,
empty mastery data, empty sources, hybrid warm-up reuse.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.guides.compiler import (
    BlockGuide,
    GeneratedGuideContent,
    GuideCompilationError,
    _compute_source_hash,
    compile_block_guide,
)
from mitty.guides.protocols import get_protocol
from mitty.guides.sources import SourceBundle, TieredChunk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"
_COURSE_ID = 42
ALL_BLOCK_TYPES = [
    "plan",
    "retrieval",
    "worked_example",
    "deep_explanation",
    "urgent_deliverable",
    "reflection",
]

# ---------------------------------------------------------------------------
# Mock Supabase helpers (_QueryChain pattern from existing tests)
# ---------------------------------------------------------------------------


def _mock_response(data: list[dict[str, Any]]) -> MagicMock:
    """Create a mock response object with .data attribute."""
    resp = MagicMock()
    resp.data = data
    return resp


class _QueryChain:
    """Fluent query builder mock that captures chained calls."""

    def __init__(self, data: list[dict[str, Any]]) -> None:
        self._data = data

    def select(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def eq(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def gte(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def in_(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def order(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def limit(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def insert(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def upsert(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    def delete(self, *_a: Any, **_kw: Any) -> _QueryChain:
        return self

    async def execute(self) -> MagicMock:
        return _mock_response(self._data)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------


def _mastery_rows() -> list[dict[str, Any]]:
    """Sample mastery_states rows."""
    return [
        {
            "concept": "photosynthesis",
            "mastery_level": 0.3,
            "confidence_self_report": 0.7,
        },
        {
            "concept": "cellular respiration",
            "mastery_level": 0.6,
            "confidence_self_report": 0.5,
        },
        {
            "concept": "mitosis",
            "mastery_level": 0.8,
            "confidence_self_report": 0.8,
        },
    ]


def _sample_tiered_chunks() -> list[TieredChunk]:
    """Build sample TieredChunk objects for a SourceBundle."""
    return [
        TieredChunk(
            chunk_id=101,
            content_text="Photosynthesis converts light energy.",
            resource_id=10,
            resource_title="Biology Chapter 5",
            trust_score=0.9,
            tier="teacher",
            rank=1.0,
        ),
        TieredChunk(
            chunk_id=102,
            content_text="Chloroplasts contain chlorophyll.",
            resource_id=11,
            resource_title="Class Notes",
            trust_score=0.7,
            tier="supplementary",
            rank=2.0,
        ),
        TieredChunk(
            chunk_id=103,
            content_text="Light-dependent reactions overview.",
            resource_id=12,
            resource_title="Study Guide",
            trust_score=0.6,
            tier="supplementary",
            rank=3.0,
        ),
    ]


def _sample_source_bundle(*, needs_resources: bool = False) -> SourceBundle:
    """Build a SourceBundle with sample chunks."""
    chunks = _sample_tiered_chunks()
    return SourceBundle(
        chunks=chunks,
        needs_resources=needs_resources,
        tier_counts={"teacher": 1, "supplementary": 2},
    )


def _empty_source_bundle() -> SourceBundle:
    return SourceBundle(chunks=[], needs_resources=True, tier_counts={})


def _sample_generated_content() -> GeneratedGuideContent:
    """Build a GeneratedGuideContent for LLM mock returns."""
    return GeneratedGuideContent(
        warmup_items=[
            {
                "question": "What is photosynthesis?",
                "answer": "The process by which plants convert light to energy.",
                "type": "short_answer",
            },
            {
                "question": "Name one product of photosynthesis.",
                "answer": "Oxygen",
                "type": "recall",
            },
        ],
        exit_items=[
            {
                "question": "Explain why photosynthesis matters for life on Earth.",
                "answer": "Produces oxygen and glucose for food chains.",
                "type": "short_answer",
            },
        ],
        success_criteria=[
            "I can describe the inputs and outputs of photosynthesis.",
            "I can explain the role of chlorophyll in light absorption.",
        ],
    )


def _practice_item_rows() -> list[dict[str, Any]]:
    """Sample practice_items rows for hybrid warm-up reuse."""
    return [
        {
            "question_text": "What is the equation for photosynthesis?",
            "correct_answer": "6CO2 + 6H2O -> C6H12O6 + 6O2",
            "practice_type": "short_answer",
        },
        {
            "question_text": "Where does photosynthesis occur?",
            "correct_answer": "Chloroplasts",
            "practice_type": "recall",
        },
    ]


# ---------------------------------------------------------------------------
# Mock Supabase client builders
# ---------------------------------------------------------------------------


def _build_mock_client(
    *,
    mastery_rows: list[dict[str, Any]] | None = None,
    cache_rows: list[dict[str, Any]] | None = None,
    practice_rows: list[dict[str, Any]] | None = None,
) -> AsyncMock:
    """Build a mock Supabase client with table routing.

    Routes:
      - mastery_states -> mastery_rows
      - guide_content_cache -> cache_rows (for select), upsert is a no-op
      - practice_items -> practice_rows
    """
    mastery_chain = _QueryChain(mastery_rows or [])
    cache_select_chain = _QueryChain(cache_rows or [])
    cache_upsert_chain = _QueryChain([])
    practice_chain = _QueryChain(practice_rows or [])

    def _table(name: str) -> Any:
        if name == "mastery_states":
            return mastery_chain
        if name == "guide_content_cache":
            tbl = MagicMock()
            tbl.select = cache_select_chain.select
            tbl.upsert = cache_upsert_chain.upsert
            return tbl
        if name == "practice_items":
            return practice_chain
        return _QueryChain([])

    client = AsyncMock()
    client.table = MagicMock(side_effect=_table)
    return client


def _build_mock_ai_client(
    content: GeneratedGuideContent | None = None,
) -> AsyncMock:
    """Build a mock AIClient that returns predetermined content."""
    ai = AsyncMock()
    if content is not None:
        ai.call_structured = AsyncMock(return_value=content)
    else:
        ai.call_structured = AsyncMock(return_value=_sample_generated_content())
    ai._model = "claude-sonnet-4-20250514"
    return ai


# ---------------------------------------------------------------------------
# Tests: happy path (parametrize all 6 block types)
# ---------------------------------------------------------------------------


class TestCompileGuideHappyPath:
    @pytest.mark.parametrize("block_type", ALL_BLOCK_TYPES)
    @pytest.mark.asyncio
    async def test_compile_guide_happy_path(self, block_type: str) -> None:
        """Happy path: compile_block_guide returns a BlockGuide for each type."""
        ai_client = _build_mock_ai_client()
        sb_client = _build_mock_client(mastery_rows=_mastery_rows())
        bundle = _sample_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type=block_type,
                course_id=_COURSE_ID,
                user_id=_USER_ID,
                block_id=1,
            )

        assert isinstance(guide, BlockGuide)
        assert guide.block_id == 1
        assert guide.guide_version == "1.0"

        # Steps should match the protocol
        protocol = get_protocol(block_type)
        assert len(guide.steps_json) == len(protocol.steps)

        # Should have warm-up and exit items
        assert len(guide.warmup_items_json) > 0
        assert len(guide.exit_items_json) > 0
        assert len(guide.success_criteria_json) > 0

        # Concepts should be populated from mastery data
        assert len(guide.concepts_json) > 0

        # Source bundle should be populated
        assert len(guide.source_bundle_json) > 0

        # Completion criteria should have required_steps
        assert "required_steps" in guide.completion_criteria_json
        assert "min_artifacts" in guide.completion_criteria_json


# ---------------------------------------------------------------------------
# Tests: cache hit skips LLM
# ---------------------------------------------------------------------------


class TestCacheHit:
    @pytest.mark.asyncio
    async def test_compile_guide_cache_hit_skips_llm(self) -> None:
        """When cache has content, ai_client.call_structured is NOT called."""
        cached_content = {
            "content_json": {
                "warmup_items": [
                    {
                        "question": "Cached warm-up",
                        "answer": "Cached answer",
                        "type": "recall",
                    }
                ],
                "exit_items": [
                    {
                        "question": "Cached exit",
                        "answer": "Cached answer",
                        "type": "recall",
                    }
                ],
                "success_criteria": ["Cached criterion"],
            }
        }
        ai_client = _build_mock_ai_client()
        sb_client = _build_mock_client(
            mastery_rows=_mastery_rows(),
            cache_rows=[cached_content],
        )
        bundle = _sample_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type="retrieval",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        # LLM should NOT have been called
        ai_client.call_structured.assert_not_called()

        # Content should come from cache
        assert guide.warmup_items_json == [
            {
                "question": "Cached warm-up",
                "answer": "Cached answer",
                "type": "recall",
            }
        ]
        assert guide.success_criteria_json == ["Cached criterion"]


# ---------------------------------------------------------------------------
# Tests: cache write after LLM call
# ---------------------------------------------------------------------------


class TestCacheWriteAfterLLM:
    @pytest.mark.asyncio
    async def test_compile_guide_caches_after_llm_call(self) -> None:
        """After a successful LLM call, _store_cache is called."""
        ai_client = _build_mock_ai_client()
        sb_client = _build_mock_client(mastery_rows=_mastery_rows())
        bundle = _sample_source_bundle()

        with (
            patch(
                "mitty.guides.compiler.build_source_bundle",
                new_callable=AsyncMock,
                return_value=bundle,
            ),
            patch(
                "mitty.guides.compiler._store_cache",
                new_callable=AsyncMock,
            ) as mock_store,
        ):
            await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type="retrieval",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        mock_store.assert_called_once()
        call_args = mock_store.call_args
        # Should store content_type="guide_content"
        assert call_args[0][3] == "guide_content"
        # content_json should have warmup_items, exit_items, success_criteria
        content_json = call_args[0][4]
        assert "warmup_items" in content_json
        assert "exit_items" in content_json
        assert "success_criteria" in content_json


# ---------------------------------------------------------------------------
# Tests: graceful degradation on LLM failure
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_compile_guide_graceful_degradation_on_llm_failure(
        self,
    ) -> None:
        """When LLM raises an exception, guide still returns with generic."""
        ai_client = _build_mock_ai_client()
        ai_client.call_structured = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )

        sb_client = _build_mock_client(mastery_rows=_mastery_rows())
        bundle = _sample_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type="retrieval",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        assert isinstance(guide, BlockGuide)
        # Should have generic warm-ups
        assert len(guide.warmup_items_json) > 0
        assert (
            "What do you already know about" in guide.warmup_items_json[0]["question"]
        )
        # Should have generic exit items
        assert len(guide.exit_items_json) > 0
        # Should have generic success criteria
        assert len(guide.success_criteria_json) > 0


# ---------------------------------------------------------------------------
# Tests: no AI client
# ---------------------------------------------------------------------------


class TestNoAIClient:
    @pytest.mark.asyncio
    async def test_compile_guide_with_no_ai_client(self) -> None:
        """When ai_client=None, returns generic guide without LLM."""
        sb_client = _build_mock_client(mastery_rows=_mastery_rows())
        bundle = _sample_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=None,
                client=sb_client,
                block_type="plan",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        assert isinstance(guide, BlockGuide)
        # Generic warm-ups
        assert len(guide.warmup_items_json) > 0
        assert (
            "What do you already know about" in guide.warmup_items_json[0]["question"]
        )
        # Steps from protocol
        protocol = get_protocol("plan")
        assert len(guide.steps_json) == len(protocol.steps)


# ---------------------------------------------------------------------------
# Tests: empty mastery data
# ---------------------------------------------------------------------------


class TestEmptyMastery:
    @pytest.mark.asyncio
    async def test_compile_guide_with_empty_mastery(self) -> None:
        """When no mastery data exists, guide still compiles (new student)."""
        ai_client = _build_mock_ai_client()
        sb_client = _build_mock_client(mastery_rows=[])
        bundle = _sample_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type="retrieval",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        assert isinstance(guide, BlockGuide)
        # Concepts list should be empty (no mastery data)
        assert guide.concepts_json == []
        # Should still have warm-ups from LLM
        assert len(guide.warmup_items_json) > 0


# ---------------------------------------------------------------------------
# Tests: empty sources (needs_resources flag)
# ---------------------------------------------------------------------------


class TestEmptySources:
    @pytest.mark.asyncio
    async def test_compile_guide_with_empty_sources(self) -> None:
        """When sources are empty, needs_resources is set; guide still works."""
        ai_client = _build_mock_ai_client()
        sb_client = _build_mock_client(mastery_rows=_mastery_rows())
        bundle = _empty_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type="deep_explanation",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        assert isinstance(guide, BlockGuide)
        # Source bundle should be empty
        assert guide.source_bundle_json == []
        # Guide still has steps, warm-ups, etc.
        assert len(guide.steps_json) > 0
        assert len(guide.warmup_items_json) > 0


# ---------------------------------------------------------------------------
# Tests: hybrid warm-up reuses practice items (DEC-001)
# ---------------------------------------------------------------------------


class TestHybridWarmup:
    @pytest.mark.asyncio
    async def test_hybrid_warmup_reuses_practice_items(self) -> None:
        """When practice_items exist, they are reused for warm-ups."""
        ai_client = _build_mock_ai_client()
        sb_client = _build_mock_client(
            mastery_rows=_mastery_rows(),
            practice_rows=_practice_item_rows(),
        )
        bundle = _sample_source_bundle()

        with patch(
            "mitty.guides.compiler.build_source_bundle",
            new_callable=AsyncMock,
            return_value=bundle,
        ):
            guide = await compile_block_guide(
                ai_client=ai_client,
                client=sb_client,
                block_type="plan",
                course_id=_COURSE_ID,
                user_id=_USER_ID,
            )

        assert isinstance(guide, BlockGuide)
        # Warm-ups should come from practice_items, not LLM
        assert any(
            "equation for photosynthesis" in item.get("question", "")
            for item in guide.warmup_items_json
        )


# ---------------------------------------------------------------------------
# Tests: GuideCompilationError
# ---------------------------------------------------------------------------


class TestGuideCompilationError:
    def test_error_attributes(self) -> None:
        """GuideCompilationError carries structured context."""
        err = GuideCompilationError(
            block_id=42,
            step="source_bundle",
            message="Failed to fetch sources",
            sources_fetched=False,
            llm_called=False,
        )
        assert err.block_id == 42
        assert err.step == "source_bundle"
        assert str(err) == "Failed to fetch sources"
        assert err.sources_fetched is False
        assert err.llm_called is False

    def test_error_defaults(self) -> None:
        """Default flags are False."""
        err = GuideCompilationError(None, "test", "msg")
        assert err.block_id is None
        assert err.sources_fetched is False
        assert err.llm_called is False


# ---------------------------------------------------------------------------
# Tests: _compute_source_hash
# ---------------------------------------------------------------------------


class TestComputeSourceHash:
    def test_deterministic_for_same_ids(self) -> None:
        h1 = _compute_source_hash([3, 1, 2])
        h2 = _compute_source_hash([2, 3, 1])
        assert h1 == h2

    def test_different_for_different_ids(self) -> None:
        h1 = _compute_source_hash([1, 2, 3])
        h2 = _compute_source_hash([4, 5, 6])
        assert h1 != h2

    def test_empty_ids(self) -> None:
        h = _compute_source_hash([])
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest length


# ---------------------------------------------------------------------------
# Tests: BlockGuide is frozen
# ---------------------------------------------------------------------------


class TestBlockGuide:
    def test_frozen(self) -> None:
        guide = BlockGuide(block_id=1)
        with pytest.raises(AttributeError):
            guide.block_id = 2  # type: ignore[misc]

    def test_default_values(self) -> None:
        guide = BlockGuide(block_id=None)
        assert guide.block_id is None
        assert guide.concepts_json == []
        assert guide.guide_version == "1.0"
