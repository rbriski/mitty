"""Conversational coach service with pedagogical rules and source grounding.

Accepts a student message plus study block context, retrieves relevant
resource chunks, builds a pedagogically-bounded prompt (ask-before-tell,
hints-before-answers), calls the LLM, and returns a response with source
citations.  Messages are stored in ``coach_messages``.

Public API:
    coach_chat(client, ai_client, user_id, study_block_id, message) -> CoachResponse
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mitty.ai.prompts import get_prompt, wrap_user_input
from mitty.ai.retriever import retrieve

if TYPE_CHECKING:
    from mitty.ai.client import AIClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# Maximum number of previous messages to include as conversation context.
_MAX_HISTORY = 20

# Minimum retriever results to proceed with a coached response.
_MIN_RETRIEVER_RESULTS = 1


# ---------------------------------------------------------------------------
# Pydantic model for structured LLM output
# ---------------------------------------------------------------------------


class CoachLLMResponse(BaseModel):
    """Structured response from the coach LLM call."""

    response: str = Field(description="The coach's reply.")
    sources_used: list[int] = Field(
        default_factory=list,
        description="chunk_ids referenced in the response.",
    )


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoachResponse:
    """Value object returned by :func:`coach_chat`."""

    content: str
    sources_cited: list[dict[str, Any]] = field(default_factory=list)
    message_id: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_study_block(
    client: AsyncClient,
    study_block_id: int,
    user_id: str,
) -> dict[str, Any] | None:
    """Load a study block with plan-join for ownership verification."""
    result = await (
        client.table("study_blocks")
        .select("*, study_plans!inner(user_id)")
        .eq("id", study_block_id)
        .eq("study_plans.user_id", user_id)
        .maybe_single()
        .execute()
    )
    if result and result.data:
        data = result.data
        data.pop("study_plans", None)
        return data
    return None


async def _load_chat_history(
    client: AsyncClient,
    user_id: str,
    study_block_id: int,
) -> list[dict[str, Any]]:
    """Load the last N messages from coach_messages for this block."""
    result = await (
        client.table("coach_messages")
        .select("role, content")
        .eq("user_id", user_id)
        .eq("study_block_id", study_block_id)
        .order("created_at", desc=False)
        .limit(_MAX_HISTORY)
        .execute()
    )
    return result.data or []


async def _store_message(
    client: AsyncClient,
    *,
    user_id: str,
    study_block_id: int,
    role: str,
    content: str,
    sources_cited: list[dict[str, Any]] | None = None,
) -> int:
    """Insert a message into coach_messages and return its id."""
    row: dict[str, Any] = {
        "user_id": user_id,
        "study_block_id": study_block_id,
        "role": role,
        "content": content,
        "sources_cited": sources_cited,
        "created_at": datetime.now(UTC).isoformat(),
    }
    result = await client.table("coach_messages").insert(row).execute()
    data = result.data or []
    if data:
        return int(data[0]["id"])
    return 0


def _format_conversation_history(history: list[dict[str, Any]]) -> str:
    """Format chat history as a readable conversation transcript.

    Student messages are wrapped in ``<user_input>`` tags to prevent
    prompt injection via replayed history.
    """
    if not history:
        return "(no previous messages)"
    lines = []
    for msg in history:
        if msg["role"] == "student":
            lines.append(f"Student: {wrap_user_input(msg['content'])}")
        else:
            lines.append(f"Coach: {msg['content']}")
    return "\n".join(lines)


def _format_resource_chunks(
    chunks: list[Any],
) -> tuple[str, dict[int, dict[str, Any]]]:
    """Format retrieved chunks for the prompt and build a citation lookup.

    Returns:
        A tuple of (formatted_text, {chunk_id: {chunk_id, title, excerpt}}).
    """
    if not chunks:
        return "(no resource chunks available)", {}

    sections: list[str] = []
    citation_map: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        chunk_id = chunk.chunk_id
        content = chunk.content_text
        title = chunk.resource_title
        sections.append(f"[Chunk {chunk_id}] (Source: {title})\n{content}")
        citation_map[chunk_id] = {
            "chunk_id": chunk_id,
            "title": title,
            "excerpt": content[:200],
        }
    return "\n\n".join(sections), citation_map


async def _get_mastery_level(
    client: AsyncClient,
    user_id: str,
    course_id: int,
    concept: str,
) -> float:
    """Fetch current mastery level. Defaults to 0.0."""
    result = await (
        client.table("mastery_states")
        .select("mastery_level")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .eq("concept", concept)
        .maybe_single()
        .execute()
    )
    if result and result.data:
        return float(result.data.get("mastery_level", 0.0))
    return 0.0


def _derive_topic(block: dict[str, Any]) -> str:
    """Derive a topic string from the study block context."""
    title = block.get("title", "")
    description = block.get("description", "")
    if description:
        return f"{title} - {description}"
    return title or "General study"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def coach_chat(
    *,
    client: AsyncClient,
    ai_client: AIClient | None,
    user_id: str,
    study_block_id: int,
    message: str,
) -> CoachResponse:
    """Send a student message to the conversational coach.

    Loads block context, retrieves relevant chunks scoped to the block's
    course, builds a pedagogically-bounded prompt, calls the LLM, stores
    both the student and coach messages, and returns the response with
    source citations.

    Args:
        client: Async Supabase client.
        ai_client: AIClient instance (or None for graceful degradation).
        user_id: The authenticated user's UUID string.
        study_block_id: The study block this conversation is scoped to.
        message: The student's message text.

    Returns:
        A :class:`CoachResponse` with the coach's reply, cited sources,
        and the stored message ID.
    """
    # 0. Graceful degradation: no AI client
    if ai_client is None:
        await _store_message(
            client,
            user_id=user_id,
            study_block_id=study_block_id,
            role="student",
            content=message,
        )
        coach_msg_id = await _store_message(
            client,
            user_id=user_id,
            study_block_id=study_block_id,
            role="coach",
            content="Coach is currently unavailable. Please try again later.",
        )
        return CoachResponse(
            content="Coach is currently unavailable. Please try again later.",
            sources_cited=[],
            message_id=coach_msg_id,
        )

    # 1. Load the study block (verifies ownership)
    block = await _load_study_block(client, study_block_id, user_id)
    if block is None:
        return CoachResponse(
            content="Study block not found.",
            sources_cited=[],
            message_id=0,
        )

    course_id = block.get("course_id")
    topic = _derive_topic(block)

    # 2. Load chat history
    history = await _load_chat_history(client, user_id, study_block_id)

    # 3. Store the student's message
    await _store_message(
        client,
        user_id=user_id,
        study_block_id=study_block_id,
        role="student",
        content=message,
    )

    # 4. Retrieve relevant chunks scoped to this course
    retrieval_result = None
    if course_id is not None:
        retrieval_result = await retrieve(
            client,
            course_id=course_id,
            query=topic,
            min_results=_MIN_RETRIEVER_RESULTS,
        )

    if retrieval_result is None or not retrieval_result.sufficient:
        coach_msg_id = await _store_message(
            client,
            user_id=user_id,
            study_block_id=study_block_id,
            role="coach",
            content=(
                "I don't have enough study materials for this topic yet. "
                "Ask your teacher to add resources so I can help you study."
            ),
        )
        return CoachResponse(
            content=(
                "I don't have enough study materials for this topic yet. "
                "Ask your teacher to add resources so I can help you study."
            ),
            sources_cited=[],
            message_id=coach_msg_id,
        )

    # 5. Build the prompt
    prompt_config = get_prompt("coach")
    chunks_text, citation_map = _format_resource_chunks(retrieval_result.chunks)
    conversation_history = _format_conversation_history(history)

    # Get mastery level for the topic
    mastery_level = 0.0
    if course_id is not None:
        mastery_level = await _get_mastery_level(client, user_id, course_id, topic)

    # The coach template already wraps {student_message} in <user_input>
    # tags, so we substitute the raw message text (no double-wrapping).
    user_prompt = prompt_config.user_template
    user_prompt = user_prompt.replace("{topic}", topic)
    user_prompt = user_prompt.replace("{mastery_level}", str(mastery_level))
    user_prompt = user_prompt.replace("{student_message}", message)
    user_prompt = user_prompt.replace("{resource_chunks}", chunks_text)
    user_prompt = user_prompt.replace("{conversation_history}", conversation_history)

    system_prompt = prompt_config.system_prompt

    # 6. Call the LLM
    llm_response = await ai_client.call_structured(
        system=system_prompt,
        user_prompt=user_prompt,
        response_model=CoachLLMResponse,
        role="coach",
        user_id=user_id,
        call_type="coach_chat",
        supabase_client=client,
    )

    # 7. Build source citations from the LLM's referenced chunk IDs
    sources_cited: list[dict[str, Any]] = []
    for chunk_id in llm_response.sources_used:
        if chunk_id in citation_map:
            sources_cited.append(citation_map[chunk_id])

    # 8. Store the coach's response
    coach_msg_id = await _store_message(
        client,
        user_id=user_id,
        study_block_id=study_block_id,
        role="coach",
        content=llm_response.response,
        sources_cited=sources_cited,
    )

    return CoachResponse(
        content=llm_response.response,
        sources_cited=sources_cited,
        message_id=coach_msg_id,
    )
