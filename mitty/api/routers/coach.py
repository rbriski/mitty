"""Coach chat endpoints for conversational study coaching.

- POST /study-blocks/{block_id}/coach/messages — send a message, get coach response
- GET  /study-blocks/{block_id}/coach/messages — get chat history for a block
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.ai.coach import coach_chat
from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_ai_client, get_user_client
from mitty.api.schemas import (
    ChatMessageCreate,
    CoachMessageResponse,
    ListResponse,
)

if TYPE_CHECKING:
    from mitty.ai.client import AIClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["coach"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]
OptionalAI = Annotated["AIClient | None", Depends(get_ai_client)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_block_for_user(
    client: AsyncClient,
    block_id: int,
    user_id: str,
) -> dict[str, Any]:
    """Fetch a study block, verifying ownership via plan join."""
    result = await (
        client.table("study_blocks")
        .select("*, study_plans!inner(user_id)")
        .eq("id", block_id)
        .eq("study_plans.user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BLOCK_NOT_FOUND",
                "message": "Study block not found.",
            },
        )
    data = result.data
    data.pop("study_plans", None)
    return data


# ---------------------------------------------------------------------------
# POST /study-blocks/{block_id}/coach/messages
# ---------------------------------------------------------------------------


@router.post(
    "/study-blocks/{block_id}/coach/messages",
    response_model=CoachMessageResponse,
)
async def send_coach_message(
    block_id: int,
    data: ChatMessageCreate,
    client: UserClient,
    current_user: CurrentUser,
    ai_client: OptionalAI,
) -> CoachMessageResponse:
    """Send a student message and receive a coach response.

    Verifies block ownership, delegates to coach_chat(), and returns
    the coach's reply with source citations. Returns 503 when the AI
    client is unavailable.
    """
    user_id = current_user["user_id"]

    # Verify block ownership
    await _fetch_block_for_user(client, block_id, user_id)

    if ai_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "COACH_UNAVAILABLE",
                "message": "Coach is currently unavailable.",
            },
        )

    response = await coach_chat(
        client=client,
        ai_client=ai_client,
        user_id=user_id,
        study_block_id=block_id,
        message=data.message,
    )

    # Fetch the stored message to get the DB-generated created_at.
    msg_result = await (
        client.table("coach_messages")
        .select("created_at")
        .eq("id", response.message_id)
        .maybe_single()
        .execute()
    )
    created_at = (
        msg_result.data["created_at"]
        if msg_result and msg_result.data
        else datetime.now(UTC).isoformat()
    )

    return CoachMessageResponse(
        id=response.message_id,
        study_block_id=block_id,
        role="coach",
        content=response.content,
        sources_cited=response.sources_cited or None,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# GET /study-blocks/{block_id}/coach/messages
# ---------------------------------------------------------------------------


@router.get(
    "/study-blocks/{block_id}/coach/messages",
    response_model=ListResponse[CoachMessageResponse],
)
async def get_coach_messages(
    block_id: int,
    client: UserClient,
    current_user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[CoachMessageResponse]:
    """Return paginated chat history for a study block.

    Verifies block ownership and fetches messages from coach_messages.
    """
    user_id = current_user["user_id"]

    # Verify block ownership
    await _fetch_block_for_user(client, block_id, user_id)

    # Fetch total count
    count_result = await (
        client.table("coach_messages")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("study_block_id", block_id)
        .execute()
    )
    total = count_result.count if count_result.count is not None else 0

    # Fetch paginated messages
    result = await (
        client.table("coach_messages")
        .select("*")
        .eq("user_id", user_id)
        .eq("study_block_id", block_id)
        .order("created_at", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows: list[dict[str, Any]] = result.data or []

    messages = [
        CoachMessageResponse(
            id=row["id"],
            study_block_id=row["study_block_id"],
            role=row["role"],
            content=row["content"],
            sources_cited=row.get("sources_cited"),
            created_at=row.get("created_at", datetime.now(UTC).isoformat()),
        )
        for row in rows
    ]

    return ListResponse[CoachMessageResponse](
        data=messages,
        total=total,
        offset=offset,
        limit=limit,
    )
