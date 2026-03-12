"""Tests for mitty.mastery.concepts — LLM-powered concept extraction.

Covers: LLM structured extraction, pattern fallbacks (chapter numbers,
module titles, assessment unit_or_topic), upsert deduplication,
and token-capping for chunk summaries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from mitty.mastery.concepts import (
    ConceptExtraction,
    ConceptExtractionList,
    _cap_tokens,
    _extract_assessment_topics,
    _extract_chapter_numbers,
    _extract_module_titles,
    extract_concepts,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
COURSE_ID = 101


# ---------------------------------------------------------------------------
# Helpers — Supabase mock builder
# ---------------------------------------------------------------------------


def _mock_supabase_client(
    *,
    assignments: list[dict] | None = None,
    resources: list[dict] | None = None,
    resource_chunks: list[dict] | None = None,
    assessments: list[dict] | None = None,
) -> AsyncMock:
    """Build a mock Supabase AsyncClient that returns canned data.

    Supports chained calls:
      table("X").select("cols").eq("course_id", N).execute()
    and:
      table("mastery_states").upsert([...], on_conflict=...).execute()

    Also supports the resource_chunks join pattern:
      table("resource_chunks").select("..., resources!inner(course_id)")
        .eq("resources.course_id", N).execute()
    """
    client = AsyncMock()

    _data_map: dict[str, list[dict]] = {
        "assignments": assignments or [],
        "resources": resources or [],
        "resource_chunks": resource_chunks or [],
        "assessments": assessments or [],
    }

    # Track upsert calls for assertion
    upsert_calls: list[tuple] = []

    def _table(name: str) -> MagicMock:
        table_mock = MagicMock()

        if name == "mastery_states":
            # Upsert chain: table().upsert(rows, on_conflict=...).execute()
            def _upsert(rows, **kwargs):
                upsert_calls.append((rows, kwargs))
                builder = MagicMock()
                builder.execute = AsyncMock(return_value=MagicMock(data=rows))
                return builder

            table_mock.upsert = _upsert
        else:
            # Select chain: table().select(...).eq(...).execute()
            data = _data_map.get(name, [])

            def _select(*args, **kwargs):
                select_builder = MagicMock()

                def _eq(*eq_args, **eq_kwargs):
                    eq_builder = MagicMock()
                    eq_builder.execute = AsyncMock(return_value=MagicMock(data=data))
                    # Support further chained .eq() calls
                    eq_builder.eq = _eq
                    return eq_builder

                select_builder.eq = _eq
                select_builder.execute = AsyncMock(return_value=MagicMock(data=data))
                return select_builder

            table_mock.select = _select

        return table_mock

    client.table = MagicMock(side_effect=_table)
    # Expose upsert tracking
    client._upsert_calls = upsert_calls

    return client


# ---------------------------------------------------------------------------
# Test: LLM returns structured list
# ---------------------------------------------------------------------------


class TestExtractConceptsLlmReturnsStructuredList:
    """extract_concepts returns concepts from LLM structured output."""

    async def test_extract_concepts_llm_returns_structured_list(self) -> None:
        assignments = [
            {"id": 1, "name": "Chapter 5 Homework: Quadratic Equations"},
            {"id": 2, "name": "Unit 3 Quiz: Linear Functions"},
        ]
        resources = [
            {
                "id": 10,
                "title": "Module 1: Algebra Basics",
                "module_name": "Module 1",
            },
        ]
        resource_chunks = [
            {
                "content_text": "The quadratic formula is used to solve equations.",
                "token_count": 10,
            },
        ]
        assessments = [
            {
                "name": "Unit 3 Test",
                "unit_or_topic": "Linear Functions",
                "assessment_type": "test",
            },
        ]

        client = _mock_supabase_client(
            assignments=assignments,
            resources=resources,
            resource_chunks=resource_chunks,
            assessments=assessments,
        )

        # Mock AI client that returns structured concepts
        ai_client = AsyncMock()
        ai_client.call_structured = AsyncMock(
            return_value=ConceptExtractionList(
                concepts=[
                    ConceptExtraction(
                        name="Quadratic Equations",
                        description="Solving equations using the quadratic formula",
                        source_type="assignment",
                    ),
                    ConceptExtraction(
                        name="Linear Functions",
                        description="Understanding linear functions and their graphs",
                        source_type="assessment",
                    ),
                    ConceptExtraction(
                        name="Algebra Basics",
                        description="Foundational algebra concepts",
                        source_type="resource",
                    ),
                ]
            )
        )

        concepts = await extract_concepts(
            client=client,
            ai_client=ai_client,
            course_id=COURSE_ID,
            user_id=USER_ID,
        )

        assert len(concepts) == 3
        assert all(isinstance(c, ConceptExtraction) for c in concepts)
        names = {c.name for c in concepts}
        assert "Quadratic Equations" in names
        assert "Linear Functions" in names
        assert "Algebra Basics" in names

        # Verify ai_client.call_structured was called
        ai_client.call_structured.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test: Pattern fallback — chapter numbers
# ---------------------------------------------------------------------------


class TestExtractConceptsFallbackChapterNumbers:
    """Pattern fallback extracts chapter numbers from assignment names."""

    def test_extract_concepts_fallback_chapter_numbers(self) -> None:
        assignments = [
            {"id": 1, "name": "Chapter 5 Homework"},
            {"id": 2, "name": "Ch. 12 Review"},
            {"id": 3, "name": "chapter 3 quiz"},
            {"id": 4, "name": "No chapter here"},
        ]
        result = _extract_chapter_numbers(assignments)

        assert len(result) == 3
        names = {c.name for c in result}
        assert "Chapter 5" in names
        assert "Chapter 12" in names
        assert "Chapter 3" in names
        assert all(c.source_type == "assignment" for c in result)


# ---------------------------------------------------------------------------
# Test: Pattern fallback — module titles
# ---------------------------------------------------------------------------


class TestExtractConceptsFallbackModuleTitles:
    """Pattern fallback extracts module titles from resources."""

    def test_extract_concepts_fallback_module_titles(self) -> None:
        resources = [
            {"title": "Intro to Calculus", "module_name": "Module 1: Calculus"},
            {"title": "Derivatives", "module_name": "Module 2: Derivatives"},
            {"title": "Random Page", "module_name": None},
            {
                "title": "Another",
                "module_name": "Module 1: Calculus",
            },  # duplicate
        ]
        result = _extract_module_titles(resources)

        # Should deduplicate "Module 1: Calculus"
        assert len(result) == 2
        names = {c.name for c in result}
        assert "Module 1: Calculus" in names
        assert "Module 2: Derivatives" in names
        assert all(c.source_type == "resource" for c in result)


# ---------------------------------------------------------------------------
# Test: Pattern fallback — assessment unit_or_topic
# ---------------------------------------------------------------------------


class TestExtractConceptsFallbackAssessmentUnitOrTopic:
    """Pattern fallback extracts unit_or_topic from assessments."""

    def test_extract_concepts_fallback_assessment_unit_or_topic(self) -> None:
        assessments = [
            {
                "name": "Test 1",
                "unit_or_topic": "Photosynthesis",
                "assessment_type": "test",
            },
            {
                "name": "Quiz 2",
                "unit_or_topic": "Cell Division",
                "assessment_type": "quiz",
            },
            {"name": "Essay 1", "unit_or_topic": None, "assessment_type": "essay"},
            {
                "name": "Test 3",
                "unit_or_topic": "Photosynthesis",
                "assessment_type": "test",
            },  # dup
        ]
        result = _extract_assessment_topics(assessments)

        assert len(result) == 2
        names = {c.name for c in result}
        assert "Photosynthesis" in names
        assert "Cell Division" in names
        assert all(c.source_type == "assessment" for c in result)


# ---------------------------------------------------------------------------
# Test: Upsert mastery_states — no duplicates
# ---------------------------------------------------------------------------


class TestUpsertMasteryStatesNoDuplicates:
    """extract_concepts upserts to mastery_states with deduplication."""

    async def test_upsert_mastery_states_no_duplicates(self) -> None:
        """LLM returns duplicate concept names; upsert should deduplicate."""
        client = _mock_supabase_client(
            assignments=[{"id": 1, "name": "Chapter 5 Homework"}],
        )

        ai_client = AsyncMock()
        ai_client.call_structured = AsyncMock(
            return_value=ConceptExtractionList(
                concepts=[
                    ConceptExtraction(
                        name="Quadratic Equations",
                        description="Solving quadratics",
                        source_type="assignment",
                    ),
                    ConceptExtraction(
                        name="quadratic equations",  # duplicate (case-insensitive)
                        description="Another description",
                        source_type="resource",
                    ),
                    ConceptExtraction(
                        name="Linear Functions",
                        description="Linear graphs",
                        source_type="assignment",
                    ),
                ]
            )
        )

        concepts = await extract_concepts(
            client=client,
            ai_client=ai_client,
            course_id=COURSE_ID,
            user_id=USER_ID,
        )

        # Should deduplicate case-insensitively
        assert len(concepts) == 2

        # Verify upsert was called with on_conflict and ignore_duplicates
        upsert_calls = client._upsert_calls
        assert len(upsert_calls) == 1
        rows, kwargs = upsert_calls[0]
        assert kwargs.get("on_conflict") == "user_id,course_id,concept"
        assert kwargs.get("ignore_duplicates") is True
        assert len(rows) == 2

        # All rows should have initial mastery_level=0.5
        for row in rows:
            assert row["mastery_level"] == 0.5
            assert row["user_id"] == str(USER_ID)
            assert row["course_id"] == COURSE_ID


# ---------------------------------------------------------------------------
# Test: Chunk summaries capped to 100 tokens
# ---------------------------------------------------------------------------


class TestChunkSummariesCappedTo100Tokens:
    """_cap_tokens truncates text to at most 100 tokens."""

    def test_chunk_summaries_capped_to_100_tokens(self) -> None:
        # Generate a long string (well over 100 tokens)
        long_text = " ".join(f"word{i}" for i in range(200))
        capped = _cap_tokens(long_text, max_tokens=100)

        # Verify it's shorter than the original
        assert len(capped) < len(long_text)

        # Verify it has at most 100 tokens (use tiktoken to check)
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(capped))
        assert token_count <= 100

    def test_short_text_unchanged(self) -> None:
        short = "This is a short text."
        assert _cap_tokens(short, max_tokens=100) == short

    def test_empty_text_returns_empty(self) -> None:
        assert _cap_tokens("", max_tokens=100) == ""


# ---------------------------------------------------------------------------
# Test: Fallback when LLM unavailable
# ---------------------------------------------------------------------------


class TestExtractConceptsFallbackWhenLlmUnavailable:
    """extract_concepts falls back to pattern matching when ai_client is None."""

    async def test_fallback_when_no_ai_client(self) -> None:
        assignments = [
            {"id": 1, "name": "Chapter 5 Homework: Quadratic Equations"},
            {"id": 2, "name": "Chapter 8 Test"},
        ]
        resources = [
            {"title": "Intro", "module_name": "Module 3: Thermodynamics"},
        ]
        assessments = [
            {
                "name": "Unit Test",
                "unit_or_topic": "Genetics",
                "assessment_type": "test",
            },
        ]

        client = _mock_supabase_client(
            assignments=assignments,
            resources=resources,
            resource_chunks=[],
            assessments=assessments,
        )

        concepts = await extract_concepts(
            client=client,
            ai_client=None,
            course_id=COURSE_ID,
            user_id=USER_ID,
        )

        # Should have concepts from all three fallback sources
        names = {c.name for c in concepts}
        assert "Chapter 5" in names
        assert "Chapter 8" in names
        assert "Module 3: Thermodynamics" in names
        assert "Genetics" in names

    async def test_fallback_when_llm_raises(self) -> None:
        """Falls back to patterns when LLM call raises an exception."""
        from mitty.ai.errors import AIClientError

        assignments = [
            {"id": 1, "name": "Ch. 2 Review"},
        ]

        client = _mock_supabase_client(
            assignments=assignments,
            resources=[],
            resource_chunks=[],
            assessments=[],
        )

        ai_client = AsyncMock()
        ai_client.call_structured = AsyncMock(
            side_effect=AIClientError("Service unavailable", status_code=503)
        )

        concepts = await extract_concepts(
            client=client,
            ai_client=ai_client,
            course_id=COURSE_ID,
            user_id=USER_ID,
        )

        # Should still get pattern-based concepts
        names = {c.name for c in concepts}
        assert "Chapter 2" in names
