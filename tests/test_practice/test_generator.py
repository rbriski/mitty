"""Tests for mitty.practice.generator — LLM practice item generation.

Covers: all 6 practice types, source chunk citations, difficulty scaling,
needs_resources fallback, cache hit skips LLM, items stored in table,
and type variation within a batch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from mitty.practice.generator import (
    GeneratedBatch,
    GeneratedItem,
    GenerationResult,
    generate_practice_items,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_COURSE_ID = 42
_CONCEPT = "photosynthesis"

ALL_PRACTICE_TYPES = {
    "multiple_choice",
    "fill_in_blank",
    "short_answer",
    "flashcard",
    "worked_example",
    "explanation",
}

# ---------------------------------------------------------------------------
# Mock Supabase helpers (same pattern as test_planner)
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


class _UpsertChain(_QueryChain):
    """Upsert chain that captures upserted rows and returns them with ids."""

    def __init__(self, id_start: int = 1) -> None:
        super().__init__([])
        self._id_counter = id_start
        self._upserted: list[dict[str, Any]] = []

    def upsert(self, rows: Any, **_kw: Any) -> _UpsertChain:
        if isinstance(rows, dict):
            rows = [rows]
        self._upserted = list(rows)
        return self

    async def execute(self) -> MagicMock:
        result = []
        for row in self._upserted:
            row_with_id = {**row, "id": self._id_counter}
            result.append(row_with_id)
            self._id_counter += 1
        return _mock_response(result)


def _sample_chunks() -> list[dict[str, Any]]:
    """Return sample resource chunk rows."""
    return [
        {
            "id": 101,
            "resource_id": 1,
            "chunk_index": 0,
            "content_text": (
                "Photosynthesis is the process by which green plants convert "
                "light energy into chemical energy, producing glucose and oxygen "
                "from carbon dioxide and water."
            ),
            "token_count": 30,
        },
        {
            "id": 102,
            "resource_id": 1,
            "chunk_index": 1,
            "content_text": (
                "The light-dependent reactions occur in the thylakoid membranes "
                "and produce ATP and NADPH. The Calvin cycle uses these products "
                "to fix carbon dioxide into glucose."
            ),
            "token_count": 35,
        },
    ]


def _make_generated_item(
    practice_type: str,
    *,
    source_chunk_ids: list[int] | None = None,
    difficulty_level: float = 0.5,
    options: list[str] | None = None,
) -> GeneratedItem:
    """Build a single GeneratedItem for testing."""
    base: dict[str, Any] = {
        "practice_type": practice_type,
        "question_text": f"Sample {practice_type} question about photosynthesis?",
        "correct_answer": f"Sample answer for {practice_type}.",
        "explanation": f"Explanation for {practice_type}.",
        "source_chunk_ids": source_chunk_ids or [101, 102],
        "difficulty_level": difficulty_level,
    }
    if practice_type == "multiple_choice":
        base["options_json"] = options or [
            "A. opt1",
            "B. opt2",
            "C. opt3",
            "D. opt4",
        ]
    elif practice_type == "worked_example":
        base["options_json"] = {
            "steps": ["Step 1: ...", "Step 2: ..."],
            "practice_problem": "Now try this...",
        }
    elif practice_type == "short_answer":
        base["options_json"] = {
            "rubric": ["Mentions light energy", "Mentions glucose"],
        }
    elif practice_type == "explanation":
        base["options_json"] = {
            "rubric": ["Clear definition", "Connects to real world"],
        }
    else:
        base["options_json"] = None
    return GeneratedItem(**base)


def _make_full_batch(
    *,
    needs_resources: bool = False,
    difficulty_level: float = 0.5,
) -> GeneratedBatch:
    """Build a GeneratedBatch with all 6 types."""
    items = [
        _make_generated_item(t, difficulty_level=difficulty_level)
        for t in ALL_PRACTICE_TYPES
    ]
    return GeneratedBatch(
        items=items,
        needs_resources=needs_resources,
    )


def _build_mock_client(
    *,
    cached_items: list[dict[str, Any]] | None = None,
    upsert_id_start: int = 1,
) -> AsyncMock:
    """Build a mock Supabase client with practice_items table routing."""
    client = AsyncMock()

    cache_chain = _QueryChain(cached_items or [])
    upsert_chain = _UpsertChain(id_start=upsert_id_start)

    def _table(name: str) -> Any:
        if name == "practice_items":
            # Return a mock that routes select -> cache_chain, upsert -> upsert_chain
            tbl = MagicMock()
            tbl.select = cache_chain.select
            tbl.upsert = upsert_chain.upsert
            return tbl
        return _QueryChain([])

    client.table = MagicMock(side_effect=_table)
    return client


def _build_mock_ai_client(batch: GeneratedBatch) -> AsyncMock:
    """Build a mock AIClient that returns a predetermined batch."""
    ai = AsyncMock()
    ai.call_structured = AsyncMock(return_value=batch)
    ai._model = "claude-sonnet-4-20250514"
    return ai


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateAll6Types:
    """generate_practice_items produces items covering all 6 practice types."""

    async def test_generate_all_6_types(self) -> None:
        batch = _make_full_batch()
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()
        chunks = _sample_chunks()

        gen_result = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=sb_client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.5,
            resource_chunks=chunks,
        )

        assert isinstance(gen_result, GenerationResult)
        assert gen_result.needs_resources is False
        result = gen_result.items

        # We should get items for all 6 types
        types_returned = {item.practice_type for item in result}
        assert types_returned == ALL_PRACTICE_TYPES

        # Should have at least 6 items
        assert len(result) >= 6


class TestItemsCiteSourceChunks:
    """Every generated item references source chunk IDs."""

    async def test_items_cite_source_chunks(self) -> None:
        batch = _make_full_batch()
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()
        chunks = _sample_chunks()

        gen_result = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=sb_client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.5,
            resource_chunks=chunks,
        )

        chunk_ids = {c["id"] for c in chunks}
        for item in gen_result.items:
            assert item.source_chunk_ids is not None
            assert len(item.source_chunk_ids) > 0
            # Every cited chunk should be from the provided chunks
            for cid in item.source_chunk_ids:
                assert cid in chunk_ids


class TestDifficultyScalesWithMasteryLevel:
    """Difficulty in the LLM prompt scales with mastery_level."""

    async def test_difficulty_scales_with_mastery_level(self) -> None:
        low_batch = _make_full_batch(difficulty_level=0.2)
        high_batch = _make_full_batch(difficulty_level=0.8)

        low_ai = _build_mock_ai_client(low_batch)
        high_ai = _build_mock_ai_client(high_batch)

        sb_low = _build_mock_client()
        sb_high = _build_mock_client()
        chunks = _sample_chunks()

        low_gen = await generate_practice_items(
            ai_client=low_ai,
            supabase_client=sb_low,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.2,
            resource_chunks=chunks,
        )

        high_gen = await generate_practice_items(
            ai_client=high_ai,
            supabase_client=sb_high,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.8,
            resource_chunks=chunks,
        )

        # Verify the LLM was called with different mastery levels
        # (the prompt should include the mastery_level)
        low_call = low_ai.call_structured.call_args
        high_call = high_ai.call_structured.call_args

        assert "0.2" in low_call.kwargs["user_prompt"]
        assert "0.8" in high_call.kwargs["user_prompt"]

        # The returned items should reflect their respective difficulty levels
        low_difficulties = [
            i.difficulty_level for i in low_gen.items if i.difficulty_level
        ]
        high_difficulties = [
            i.difficulty_level for i in high_gen.items if i.difficulty_level
        ]

        if low_difficulties and high_difficulties:
            assert max(low_difficulties) <= max(high_difficulties) + 0.01


class TestNeedsResourcesWhenNoChunks:
    """Returns needs_resources indicator when retriever finds insufficient sources."""

    async def test_needs_resources_via_retriever(self) -> None:
        """When retriever returns sufficient=False, generator falls through to LLM
        with empty chunks (concept-name-only generation), matching Phase 4 behavior."""
        from unittest.mock import patch

        from mitty.ai.retriever import RetrievalResult

        batch = _make_full_batch(needs_resources=True)
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()

        insufficient = RetrievalResult(
            chunks=[],
            sufficient=False,
            message="No study materials found for this topic.",
        )

        with patch(
            "mitty.ai.retriever.retrieve",
            new_callable=AsyncMock,
            return_value=insufficient,
        ):
            gen_result = await generate_practice_items(
                ai_client=ai_client,
                supabase_client=sb_client,
                user_id=_USER_ID,
                course_id=_COURSE_ID,
                concept=_CONCEPT,
                mastery_level=0.5,
                # No resource_chunks -> uses retriever
            )

        # LLM is called with empty chunks — generates from concept name alone
        ai_client.call_structured.assert_called_once()
        assert len(gen_result.items) > 0
        assert gen_result.needs_resources is True

    async def test_needs_resources_legacy_empty_chunks(self) -> None:
        """Legacy: passing empty resource_chunks=[] still works (calls LLM)."""
        batch = _make_full_batch(needs_resources=True)
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()

        gen_result = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=sb_client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.5,
            resource_chunks=[],  # Legacy path: empty list passed explicitly
        )

        # The AI client should have been called with a prompt indicating
        # insufficient resources
        call_kwargs = ai_client.call_structured.call_args.kwargs
        assert "no resource" in call_kwargs["user_prompt"].lower() or (
            "insufficient" in call_kwargs["user_prompt"].lower()
        )

        # Result should still be items (the LLM can generate from concept alone)
        assert len(gen_result.items) >= 1


class TestCacheHitSkipsLlmCall:
    """When items already exist in the cache, the LLM is not called."""

    async def test_cache_hit_skips_llm_call(self) -> None:
        # Simulate cached items in the practice_items table
        cached = [
            {
                "id": 1,
                "user_id": str(_USER_ID),
                "course_id": _COURSE_ID,
                "concept": _CONCEPT,
                "practice_type": "multiple_choice",
                "question_text": "Cached MC question?",
                "correct_answer": "Cached answer",
                "options_json": ["A", "B", "C", "D"],
                "explanation": "Cached explanation",
                "source_chunk_ids": [101],
                "difficulty_level": 0.5,
                "generation_model": "claude-sonnet-4-20250514",
                "times_used": 1,
                "last_used_at": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": 2,
                "user_id": str(_USER_ID),
                "course_id": _COURSE_ID,
                "concept": _CONCEPT,
                "practice_type": "flashcard",
                "question_text": "Cached flashcard?",
                "correct_answer": "Cached answer",
                "options_json": None,
                "explanation": "Cached explanation",
                "source_chunk_ids": [102],
                "difficulty_level": 0.5,
                "generation_model": "claude-sonnet-4-20250514",
                "times_used": 0,
                "last_used_at": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        ]
        ai_client = _build_mock_ai_client(_make_full_batch())
        sb_client = _build_mock_client(cached_items=cached)

        gen_result = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=sb_client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.5,
            resource_chunks=_sample_chunks(),
        )

        # LLM should NOT have been called
        ai_client.call_structured.assert_not_called()

        # Should return the cached items
        assert gen_result.needs_resources is False
        assert len(gen_result.items) == 2
        assert gen_result.items[0].practice_type == "multiple_choice"
        assert gen_result.items[1].practice_type == "flashcard"


class TestItemsStoredInPracticeItemsTable:
    """Generated items are stored in the practice_items table via upsert."""

    async def test_items_stored_in_practice_items_table(self) -> None:
        batch = _make_full_batch()
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()
        chunks = _sample_chunks()

        gen_result = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=sb_client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.5,
            resource_chunks=chunks,
        )

        # Verify table("practice_items") was called for upsert
        table_calls = [
            call.args[0] for call in sb_client.table.call_args_list if call.args
        ]
        assert "practice_items" in table_calls

        # Each returned item should have an id (from the upsert response)
        for item in gen_result.items:
            assert item.id is not None
            assert item.id > 0


class TestVariesQuestionTypesInBatch:
    """A batch should contain varied question types, not all the same."""

    async def test_varies_question_types_in_batch(self) -> None:
        batch = _make_full_batch()
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()
        chunks = _sample_chunks()

        gen_result = await generate_practice_items(
            ai_client=ai_client,
            supabase_client=sb_client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            concept=_CONCEPT,
            mastery_level=0.5,
            resource_chunks=chunks,
        )

        types = {item.practice_type for item in gen_result.items}
        # Should have multiple distinct types — at least 3 different types
        assert len(types) >= 3
        # Ideally all 6
        assert types == ALL_PRACTICE_TYPES


class TestRetrieverIntegration:
    """Generator calls retriever internally when resource_chunks is omitted."""

    async def test_generator_calls_retriever_when_no_chunks_passed(self) -> None:
        """When resource_chunks is None, generator calls retrieve() internally."""
        from unittest.mock import patch

        from mitty.ai.retriever import RetrievalResult, RetrievedChunk

        batch = _make_full_batch()
        ai_client = _build_mock_ai_client(batch)
        sb_client = _build_mock_client()

        retrieval = RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id=101,
                    content_text="Photosynthesis converts light to energy.",
                    resource_id=1,
                    resource_title="Biology Ch.5",
                    trust_score=0.9,
                    rank=1.0,
                ),
                RetrievedChunk(
                    chunk_id=102,
                    content_text="Calvin cycle fixes carbon dioxide.",
                    resource_id=1,
                    resource_title="Biology Ch.5",
                    trust_score=0.9,
                    rank=2.0,
                ),
                RetrievedChunk(
                    chunk_id=103,
                    content_text="Thylakoid membranes produce ATP.",
                    resource_id=1,
                    resource_title="Biology Ch.5",
                    trust_score=0.9,
                    rank=3.0,
                ),
            ],
            sufficient=True,
        )

        with patch(
            "mitty.ai.retriever.retrieve",
            new_callable=AsyncMock,
            return_value=retrieval,
        ) as mock_retrieve:
            gen_result = await generate_practice_items(
                ai_client=ai_client,
                supabase_client=sb_client,
                user_id=_USER_ID,
                course_id=_COURSE_ID,
                concept=_CONCEPT,
                mastery_level=0.5,
                # resource_chunks omitted -> uses retriever
            )

        mock_retrieve.assert_awaited_once_with(sb_client, _COURSE_ID, _CONCEPT)
        assert gen_result.needs_resources is False
        assert len(gen_result.items) >= 1
        # LLM should have been called
        ai_client.call_structured.assert_called_once()
