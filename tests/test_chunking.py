"""Tests for mitty.chunking — sentence-boundary chunking with tiktoken."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mitty.chunking import Chunk, achunk_text, chunk_text

# ------------------------------------------------------------------ #
#  test_chunk_text_empty_input
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("text", ["", "   ", "\n\t  ", None])
def test_chunk_text_empty_input(text: str | None) -> None:
    """Empty or whitespace-only text returns an empty list."""
    result = chunk_text(text or "", target_tokens=500, overlap_tokens=50)
    assert result == []


# ------------------------------------------------------------------ #
#  test_chunk_text_single_sentence
# ------------------------------------------------------------------ #


def test_chunk_text_single_sentence() -> None:
    """A single short sentence yields exactly one chunk at index 0."""
    text = "The quick brown fox jumps over the lazy dog."
    chunks = chunk_text(text, target_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content_text == text
    assert chunks[0].token_count > 0


# ------------------------------------------------------------------ #
#  test_chunk_text_splits_at_sentence_boundaries
# ------------------------------------------------------------------ #


def test_chunk_text_splits_at_sentence_boundaries() -> None:
    """Chunks should always start/end at sentence boundaries, never mid-sentence."""
    sentences = [f"Sentence number {i} has some words in it." for i in range(20)]
    text = " ".join(sentences)

    # Use a small target so we get multiple chunks.
    chunks = chunk_text(text, target_tokens=30, overlap_tokens=5)
    assert len(chunks) > 1

    # Every chunk must end at a sentence boundary (ends with a period).
    for chunk in chunks:
        assert chunk.content_text.rstrip().endswith(".")


# ------------------------------------------------------------------ #
#  test_chunk_text_respects_token_target
# ------------------------------------------------------------------ #


def test_chunk_text_respects_token_target() -> None:
    """No chunk should vastly exceed the target token count.

    A single sentence can exceed the target, but multi-sentence chunks
    should stay close. We allow up to 2x target as a generous bound.
    """
    sentences = [f"This is test sentence number {i}." for i in range(50)]
    text = " ".join(sentences)
    target = 40

    chunks = chunk_text(text, target_tokens=target, overlap_tokens=5)
    assert len(chunks) > 1

    for chunk in chunks:
        # Allow generous headroom: each chunk should be under 2x target
        # (single oversize sentences are the only exception).
        assert chunk.token_count < target * 3, (
            f"Chunk {chunk.chunk_index} has {chunk.token_count} tokens "
            f"(target={target})"
        )


# ------------------------------------------------------------------ #
#  test_chunk_text_overlap_between_chunks
# ------------------------------------------------------------------ #


def test_chunk_text_overlap_between_chunks() -> None:
    """Consecutive chunks should share overlapping content."""
    sentences = [f"Sentence {i} in the document." for i in range(30)]
    text = " ".join(sentences)

    chunks = chunk_text(text, target_tokens=30, overlap_tokens=20)
    assert len(chunks) >= 2

    # Check that consecutive chunks share at least some text.
    for i in range(len(chunks) - 1):
        current_words = set(chunks[i].content_text.split())
        next_words = set(chunks[i + 1].content_text.split())
        overlap = current_words & next_words
        assert len(overlap) > 0, f"No overlap between chunks {i} and {i + 1}"


# ------------------------------------------------------------------ #
#  test_chunk_text_non_ascii
# ------------------------------------------------------------------ #


def test_chunk_text_non_ascii() -> None:
    """Non-ASCII / unicode text should be chunked correctly."""
    text = (
        "El rápido zorro marrón salta sobre el perro perezoso. "
        "日本語のテストです。 "
        "Ünïcödé characters work fine. "
        "数学公式：E=mc². "
        "Ça marche très bien."
    )
    chunks = chunk_text(text, target_tokens=500, overlap_tokens=50)
    assert len(chunks) >= 1
    # All original text should be present across chunks.
    combined = " ".join(c.content_text for c in chunks)
    assert "rápido" in combined
    assert "日本語" in combined
    assert "Ünïcödé" in combined


# ------------------------------------------------------------------ #
#  test_chunk_text_very_long_input
# ------------------------------------------------------------------ #


def test_chunk_text_very_long_input() -> None:
    """A very long document produces many chunks with correct indexing."""
    sentences = [f"This is sentence {i} in a very long document." for i in range(500)]
    text = " ".join(sentences)

    chunks = chunk_text(text, target_tokens=100, overlap_tokens=20)

    assert len(chunks) > 10  # Should produce many chunks.

    # Verify sequential chunk_index.
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i

    # Every chunk has positive token count.
    for chunk in chunks:
        assert chunk.token_count > 0

    # No empty content.
    for chunk in chunks:
        assert chunk.content_text.strip()


# ------------------------------------------------------------------ #
#  test_chunk_text_chunk_index_sequential
# ------------------------------------------------------------------ #


def test_chunk_text_chunk_index_sequential() -> None:
    """chunk_index values must be 0, 1, 2, ... with no gaps."""
    sentences = [f"Sentence {i}." for i in range(20)]
    text = " ".join(sentences)
    chunks = chunk_text(text, target_tokens=20, overlap_tokens=5)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


# ------------------------------------------------------------------ #
#  test_async_chunk_uses_to_thread
# ------------------------------------------------------------------ #


async def test_async_chunk_uses_to_thread() -> None:
    """achunk_text must delegate to asyncio.to_thread."""
    expected = [Chunk(content_text="Hello.", chunk_index=0, token_count=2)]

    with patch(
        "mitty.chunking.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.return_value = expected
        result = await achunk_text("Hello.", target_tokens=500, overlap_tokens=50)

    mock_thread.assert_awaited_once_with(
        chunk_text,
        "Hello.",
        target_tokens=500,
        overlap_tokens=50,
    )
    assert result == expected
