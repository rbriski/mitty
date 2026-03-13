"""Escalation and flag endpoints.

- GET  /escalations — list escalations for current user (paginated, filterable)
- POST /escalations/{id}/acknowledge — mark escalation as seen
- POST /coach-messages/{message_id}/flag — flag a coach response
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    EscalationResponse,
    FlagCreate,
    FlaggedResponseResponse,
    ListResponse,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["escalations"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]


# ---------------------------------------------------------------------------
# GET /escalations
# ---------------------------------------------------------------------------


@router.get("/escalations", response_model=ListResponse[EscalationResponse])
async def list_escalations(
    client: UserClient,
    current_user: CurrentUser,
    status: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=100),
) -> ListResponse[EscalationResponse]:
    """List escalations for the current user, optionally filtered by status."""
    user_id = current_user["user_id"]

    query = (
        client.table("escalation_log").select("*", count="exact").eq("user_id", user_id)
    )

    if status == "active":
        query = query.eq("acknowledged", False)
    elif status == "acknowledged":
        query = query.eq("acknowledged", True)

    query = query.order("created_at", desc=True)
    result = await query.range(offset, offset + limit - 1).execute()

    rows: list[dict[str, Any]] = result.data or []
    total = result.count if result.count is not None else 0

    escalations = [
        EscalationResponse(
            id=row["id"],
            signal_type=row["signal_type"],
            concept=row.get("concept"),
            context_data=row.get("context_data"),
            suggested_action=row.get("suggested_action"),
            acknowledged=row["acknowledged"],
            acknowledged_at=row.get("acknowledged_at"),
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return ListResponse[EscalationResponse](
        data=escalations,
        total=total,
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# POST /escalations/{id}/acknowledge
# ---------------------------------------------------------------------------


@router.post("/escalations/{id}/acknowledge", response_model=EscalationResponse)
async def acknowledge_escalation(
    id: int,
    client: UserClient,
    current_user: CurrentUser,
) -> EscalationResponse:
    """Mark an escalation as acknowledged."""
    user_id = current_user["user_id"]

    result = await (
        client.table("escalation_log")
        .update(
            {
                "acknowledged": True,
                "acknowledged_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", id)
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": "Escalation not found.",
            },
        )

    row = result.data[0]
    return EscalationResponse(
        id=row["id"],
        signal_type=row["signal_type"],
        concept=row.get("concept"),
        context_data=row.get("context_data"),
        suggested_action=row.get("suggested_action"),
        acknowledged=row["acknowledged"],
        acknowledged_at=row.get("acknowledged_at"),
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# POST /coach-messages/{message_id}/flag
# ---------------------------------------------------------------------------


@router.post(
    "/coach-messages/{message_id}/flag",
    response_model=FlaggedResponseResponse,
    status_code=201,
)
async def flag_coach_message(
    message_id: int,
    data: FlagCreate,
    client: UserClient,
    current_user: CurrentUser,
) -> FlaggedResponseResponse:
    """Flag a coach message for review.

    Verifies the coach message exists and belongs to the user
    (via study_block ownership), then creates a flagged_responses row.
    """
    user_id = current_user["user_id"]

    # Verify coach message exists and belongs to user.
    msg_result = await (
        client.table("coach_messages")
        .select("id, user_id, study_block_id")
        .eq("id", message_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    if not msg_result or not msg_result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": "Coach message not found.",
            },
        )

    # Create flagged_responses row.
    row = {
        "user_id": user_id,
        "coach_message_id": message_id,
        "reason": data.reason,
        "created_at": datetime.now(UTC).isoformat(),
    }
    insert_result = await client.table("flagged_responses").insert(row).execute()

    if not insert_result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INSERT_FAILED",
                "message": "Failed to create flag.",
            },
        )

    created = insert_result.data[0]
    return FlaggedResponseResponse(
        id=created["id"],
        coach_message_id=created["coach_message_id"],
        reason=created["reason"],
        created_at=created["created_at"],
    )
