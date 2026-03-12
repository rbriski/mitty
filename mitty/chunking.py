"""Resource chunking pipeline — sentence-boundary splitting with tiktoken.

Splits text into overlapping chunks at sentence boundaries, counting tokens
with the ``cl100k_base`` tiktoken encoding.  Provides both sync and async
interfaces (the async wrapper offloads CPU-bound tiktoken work via
``asyncio.to_thread``).

Traces to: DEC-004, DEC-007
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import tiktoken

# Sentence-ending pattern: split after `.`, `!`, `?` followed by whitespace.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Lazily initialised encoder (module-level singleton).
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Return the cl100k_base encoder, creating it once."""
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


@dataclass(frozen=True, slots=True)
class Chunk:
    """A single chunk of text with metadata."""

    content_text: str
    chunk_index: int
    token_count: int


def _count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding."""
    return len(_get_encoder().encode(text))


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences at sentence-boundary punctuation."""
    parts = _SENTENCE_RE.split(text)
    return [s for s in parts if s.strip()]


def chunk_text(
    text: str,
    *,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Split *text* into chunks at sentence boundaries.

    Each chunk aims for *target_tokens* tokens (cl100k_base).  Adjacent
    chunks share approximately *overlap_tokens* of trailing/leading content
    to preserve context across boundaries.

    Args:
        text: The input text to chunk.
        target_tokens: Target token count per chunk.
        overlap_tokens: Approximate token overlap between consecutive chunks.

    Returns:
        List of :class:`Chunk` objects ordered by ``chunk_index``.
        Returns an empty list for empty / whitespace-only input.
    """
    if not text or not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    current_sentences: list[str] = []
    current_tokens = 0
    chunk_index = 0

    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)

        # If adding this sentence would exceed the target and we already
        # have content, finalise the current chunk first.
        if current_sentences and current_tokens + sentence_tokens > target_tokens:
            chunk_text_str = " ".join(current_sentences)
            chunks.append(
                Chunk(
                    content_text=chunk_text_str,
                    chunk_index=chunk_index,
                    token_count=_count_tokens(chunk_text_str),
                )
            )
            chunk_index += 1

            # Build overlap: take trailing sentences that fit within
            # overlap_tokens.
            overlap_sentences: list[str] = []
            overlap_token_count = 0
            for s in reversed(current_sentences):
                s_tokens = _count_tokens(s)
                if overlap_token_count + s_tokens > overlap_tokens:
                    break
                overlap_sentences.insert(0, s)
                overlap_token_count += s_tokens

            current_sentences = overlap_sentences
            current_tokens = overlap_token_count

        current_sentences.append(sentence)
        current_tokens += sentence_tokens

    # Flush remaining sentences as the final chunk.
    if current_sentences:
        chunk_text_str = " ".join(current_sentences)
        chunks.append(
            Chunk(
                content_text=chunk_text_str,
                chunk_index=chunk_index,
                token_count=_count_tokens(chunk_text_str),
            )
        )

    return chunks


async def achunk_text(
    text: str,
    *,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Async wrapper around :func:`chunk_text`.

    Offloads the CPU-bound tiktoken encoding to a thread via
    ``asyncio.to_thread``.
    """
    return await asyncio.to_thread(
        chunk_text,
        text,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )
