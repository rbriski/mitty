"""Tests for mitty.ai.retriever — Postgres FTS retriever."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mitty.ai.retriever import (
    RetrievalResult,
    RetrievedChunk,
    _escape_like,
    _rows_to_chunks,
    _sanitize_query,
    retrieve,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_row(
    chunk_id: int,
    content: str,
    resource_id: int,
    title: str,
    resource_type: str,
    course_id: int = 1,
) -> dict[str, Any]:
    """Build a fake Supabase row matching the retriever's select shape."""
    return {
        "id": chunk_id,
        "content_text": content,
        "resource_id": resource_id,
        "resources": {
            "title": title,
            "resource_type": resource_type,
            "course_id": course_id,
        },
    }


def _make_supabase_client(rows: list[dict[str, Any]]) -> AsyncMock:
    """Create a mock Supabase AsyncClient that returns *rows* from text_search."""
    execute_result = MagicMock()
    execute_result.data = rows

    # Build a chain: table().select().eq().limit().text_search().execute()
    # text_search() is terminal (returns QueryRequestBuilder with only .execute())
    chain = AsyncMock()
    chain.execute = AsyncMock(return_value=execute_result)
    chain.text_search = MagicMock(return_value=chain)
    chain.limit = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.select = MagicMock(return_value=chain)

    client = AsyncMock()
    client.table = MagicMock(return_value=chain)
    return client


def _sample_rows(count: int = 5, course_id: int = 1) -> list[dict[str, Any]]:
    """Generate *count* sample rows."""
    types = ["canvas_page", "textbook", "file", "discussion", "link"]
    return [
        _make_row(
            chunk_id=i + 1,
            content=f"Content about photosynthesis part {i + 1}",
            resource_id=100 + i,
            title=f"Resource {i + 1}",
            resource_type=types[i % len(types)],
            course_id=course_id,
        )
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# _sanitize_query
# ---------------------------------------------------------------------------


class TestSanitizeQuery:
    def test_strips_operators(self) -> None:
        assert _sanitize_query("foo & bar | baz") == "foo bar baz"

    def test_strips_parens_and_colons(self) -> None:
        assert _sanitize_query("(hello):world*") == "hello world"

    def test_collapses_whitespace(self) -> None:
        assert _sanitize_query("  lots   of   spaces  ") == "lots of spaces"

    def test_plain_text_unchanged(self) -> None:
        assert _sanitize_query("simple query") == "simple query"


# ---------------------------------------------------------------------------
# _rows_to_chunks
# ---------------------------------------------------------------------------


class TestRowsToChunks:
    def test_converts_rows_to_chunks(self) -> None:
        rows = _sample_rows(3)
        chunks = _rows_to_chunks(rows)

        assert len(chunks) == 3
        assert all(isinstance(c, RetrievedChunk) for c in chunks)

    def test_trust_score_from_resource_type(self) -> None:
        rows = [
            _make_row(1, "text", 10, "Title", "textbook"),
            _make_row(2, "text", 11, "Title", "link"),
        ]
        chunks = _rows_to_chunks(rows)

        assert chunks[0].trust_score == 1.0  # textbook
        assert chunks[1].trust_score == 0.3  # link

    def test_rank_is_position_based(self) -> None:
        chunks = _rows_to_chunks(_sample_rows(4))
        assert [c.rank for c in chunks] == [1.0, 2.0, 3.0, 4.0]

    def test_missing_resources_key(self) -> None:
        row: dict[str, Any] = {
            "id": 1,
            "content_text": "some text",
            "resource_id": 10,
            # no "resources" key
        }
        chunks = _rows_to_chunks([row])
        assert len(chunks) == 1
        assert chunks[0].resource_title == ""
        # Default trust score for empty string resource type
        assert chunks[0].trust_score == 0.5


# ---------------------------------------------------------------------------
# retrieve — happy path
# ---------------------------------------------------------------------------


class TestRetrieveHappyPath:
    @pytest.mark.asyncio
    async def test_returns_ranked_chunks(self) -> None:
        rows = _sample_rows(5)
        client = _make_supabase_client(rows)

        result = await retrieve(client, course_id=1, query="photosynthesis")

        assert isinstance(result, RetrievalResult)
        assert result.sufficient is True
        assert result.message is None
        assert len(result.chunks) == 5

    @pytest.mark.asyncio
    async def test_chunks_sorted_by_rank_then_trust(self) -> None:
        rows = _sample_rows(5)
        client = _make_supabase_client(rows)

        result = await retrieve(client, course_id=1, query="photosynthesis")

        # Verify ranks are non-decreasing.
        ranks = [c.rank for c in result.chunks]
        assert ranks == sorted(ranks)

    @pytest.mark.asyncio
    async def test_text_search_called_with_config(self) -> None:
        rows = _sample_rows(5)
        client = _make_supabase_client(rows)

        await retrieve(client, course_id=1, query="photosynthesis")

        chain = client.table.return_value
        chain.text_search.assert_called_once_with(
            "search_vector",
            "photosynthesis",
            options={"config": "english", "type": "plain"},
        )

    @pytest.mark.asyncio
    async def test_course_scoping_applied(self) -> None:
        rows = _sample_rows(5)
        client = _make_supabase_client(rows)

        await retrieve(client, course_id=42, query="photosynthesis")

        chain = client.table.return_value
        chain.eq.assert_called_once_with("resources.course_id", 42)

    @pytest.mark.asyncio
    async def test_limit_applied(self) -> None:
        rows = _sample_rows(3)
        client = _make_supabase_client(rows)

        await retrieve(client, course_id=1, query="test", top_k=7)

        chain = client.table.return_value
        chain.limit.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_trust_scores_present(self) -> None:
        rows = [
            _make_row(1, "text", 10, "Title", "textbook"),
            _make_row(2, "text", 11, "Title", "canvas_page"),
            _make_row(3, "text", 12, "Title", "file"),
        ]
        client = _make_supabase_client(rows)

        result = await retrieve(client, course_id=1, query="test", min_results=1)

        trust_scores = {c.chunk_id: c.trust_score for c in result.chunks}
        assert trust_scores[1] == 1.0  # textbook
        assert trust_scores[2] == 1.0  # canvas_page
        assert trust_scores[3] == 0.7  # file


# ---------------------------------------------------------------------------
# retrieve — insufficient results
# ---------------------------------------------------------------------------


class TestRetrieveInsufficient:
    @pytest.mark.asyncio
    async def test_empty_results_returns_insufficient(self) -> None:
        client = _make_supabase_client([])

        result = await retrieve(client, course_id=1, query="nonexistent topic")

        assert result.sufficient is False
        assert result.chunks == []
        assert result.message is not None
        assert "No study materials" in result.message

    @pytest.mark.asyncio
    async def test_below_threshold_returns_insufficient(self) -> None:
        # Only 2 results but min_results=3 (default).
        rows = _sample_rows(2)
        client = _make_supabase_client(rows)

        result = await retrieve(client, course_id=1, query="photosynthesis")

        assert result.sufficient is False
        assert result.chunks == []
        assert result.message is not None

    @pytest.mark.asyncio
    async def test_custom_min_results(self) -> None:
        rows = _sample_rows(2)
        client = _make_supabase_client(rows)

        # With min_results=2, 2 rows should be sufficient.
        result = await retrieve(
            client, course_id=1, query="photosynthesis", min_results=2
        )

        assert result.sufficient is True
        assert len(result.chunks) == 2


# ---------------------------------------------------------------------------
# retrieve — edge cases
# ---------------------------------------------------------------------------


class TestRetrieveEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query_string(self) -> None:
        client = _make_supabase_client([])

        result = await retrieve(client, course_id=1, query="")

        assert result.sufficient is False
        assert result.chunks == []
        assert "No study materials" in (result.message or "")

    @pytest.mark.asyncio
    async def test_whitespace_only_query(self) -> None:
        client = _make_supabase_client([])

        result = await retrieve(client, course_id=1, query="   ")

        assert result.sufficient is False
        assert result.chunks == []

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self) -> None:
        rows = _sample_rows(5)
        client = _make_supabase_client(rows)

        # Special chars should be stripped, query should still work.
        result = await retrieve(
            client, course_id=1, query="photo & synthesis | (light*)"
        )

        assert result.sufficient is True
        chain = client.table.return_value
        chain.text_search.assert_called_once_with(
            "search_vector",
            "photo synthesis light",
            options={"config": "english", "type": "plain"},
        )

    @pytest.mark.asyncio
    async def test_query_with_only_special_chars(self) -> None:
        client = _make_supabase_client([])

        result = await retrieve(client, course_id=1, query="&|!()*")

        assert result.sufficient is False
        assert result.chunks == []


# ---------------------------------------------------------------------------
# retrieve — text_search fallback
# ---------------------------------------------------------------------------


class TestRetrieveFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_ilike_on_text_search_error(self) -> None:
        """When text_search raises, the retriever should try ilike."""
        rows = _sample_rows(5)
        ok_result = MagicMock()
        ok_result.data = rows

        # FTS chain: select().eq().limit().text_search().execute() raises
        fts_chain = MagicMock()
        fts_chain.select = MagicMock(return_value=fts_chain)
        fts_chain.eq = MagicMock(return_value=fts_chain)
        fts_chain.limit = MagicMock(return_value=fts_chain)
        fts_chain.text_search = MagicMock(return_value=fts_chain)
        fts_chain.execute = AsyncMock(side_effect=Exception("FTS not available"))

        # ILIKE chain: select().eq().ilike().limit().execute() succeeds
        ilike_chain = MagicMock()
        ilike_chain.select = MagicMock(return_value=ilike_chain)
        ilike_chain.eq = MagicMock(return_value=ilike_chain)
        ilike_chain.ilike = MagicMock(return_value=ilike_chain)
        ilike_chain.limit = MagicMock(return_value=ilike_chain)
        ilike_chain.execute = AsyncMock(return_value=ok_result)

        # First table() call → FTS path, second → ILIKE path
        client = AsyncMock()
        client.table = MagicMock(side_effect=[fts_chain, ilike_chain])

        result = await retrieve(client, course_id=1, query="photosynthesis")

        assert result.sufficient is True
        assert len(result.chunks) == 5
        ilike_chain.ilike.assert_called_once()

    @pytest.mark.asyncio
    async def test_ilike_fallback_escapes_wildcards(self) -> None:
        """ILIKE fallback must escape % and _ in the query to prevent injection."""
        rows = _sample_rows(5)
        ok_result = MagicMock()
        ok_result.data = rows

        # FTS chain fails
        fts_chain = MagicMock()
        fts_chain.select = MagicMock(return_value=fts_chain)
        fts_chain.eq = MagicMock(return_value=fts_chain)
        fts_chain.limit = MagicMock(return_value=fts_chain)
        fts_chain.text_search = MagicMock(return_value=fts_chain)
        fts_chain.execute = AsyncMock(side_effect=Exception("FTS not available"))

        # ILIKE chain succeeds
        ilike_chain = MagicMock()
        ilike_chain.select = MagicMock(return_value=ilike_chain)
        ilike_chain.eq = MagicMock(return_value=ilike_chain)
        ilike_chain.ilike = MagicMock(return_value=ilike_chain)
        ilike_chain.limit = MagicMock(return_value=ilike_chain)
        ilike_chain.execute = AsyncMock(return_value=ok_result)

        client = AsyncMock()
        client.table = MagicMock(side_effect=[fts_chain, ilike_chain])

        await retrieve(client, course_id=1, query="100% of_cells")

        ilike_chain.ilike.assert_called_once()
        pattern = ilike_chain.ilike.call_args[0][1]
        # Wildcards in user input must be escaped; only outer % are real
        assert pattern == r"%100\% of\_cells%"


# ---------------------------------------------------------------------------
# _escape_like
# ---------------------------------------------------------------------------


class TestEscapeLike:
    """Unit tests for ILIKE wildcard escaping."""

    def test_escapes_percent(self) -> None:
        assert _escape_like("100%") == r"100\%"

    def test_escapes_underscore(self) -> None:
        assert _escape_like("cell_division") == r"cell\_division"

    def test_escapes_both(self) -> None:
        assert _escape_like("50% of_total") == r"50\% of\_total"

    def test_plain_text_unchanged(self) -> None:
        assert _escape_like("photosynthesis") == "photosynthesis"

    def test_empty_string(self) -> None:
        assert _escape_like("") == ""

    def test_escapes_backslash_first(self) -> None:
        """Backslash must be escaped before % and _ to avoid double-escaping."""
        assert _escape_like(r"a\b%c_d") == r"a\\b\%c\_d"
