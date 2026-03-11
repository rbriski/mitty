"""CRUD routes for mastery_states (user-scoped)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    ListResponse,
    MasteryStateCreate,
    MasteryStateResponse,
    MasteryStateUpdate,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

router = APIRouter(prefix="/mastery-states", tags=["mastery_states"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
SupaClient = Annotated["AsyncClient", Depends(get_user_client)]


@router.post("/", response_model=MasteryStateResponse, status_code=201)
async def create_mastery_state(
    data: MasteryStateCreate,
    current_user: CurrentUser,
    client: SupaClient,
) -> MasteryStateResponse:
    """Create or upsert a mastery state (user_id injected from auth)."""
    row = data.model_dump(exclude_none=True, mode="json")
    row["user_id"] = current_user["user_id"]
    result = (
        await client.table("mastery_states")
        .upsert(row, on_conflict="user_id,course_id,concept")
        .execute()
    )
    return MasteryStateResponse(**result.data[0])


@router.get("/{state_id}", response_model=MasteryStateResponse)
async def get_mastery_state(
    state_id: int,
    current_user: CurrentUser,
    client: SupaClient,
) -> MasteryStateResponse:
    """Get a single mastery state by ID (filtered by user)."""
    result = (
        await client.table("mastery_states")
        .select("*")
        .eq("id", state_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Mastery state not found")
    return MasteryStateResponse(**result.data[0])


@router.get("/", response_model=ListResponse[MasteryStateResponse])
async def list_mastery_states(
    current_user: CurrentUser,
    client: SupaClient,
    course_id: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> ListResponse[MasteryStateResponse]:
    """List mastery states for the current user (optionally filtered by course)."""
    query = (
        client.table("mastery_states")
        .select("*", count="exact")
        .eq("user_id", current_user["user_id"])
    )
    if course_id is not None:
        query = query.eq("course_id", course_id)
    result = await query.range(offset, offset + limit - 1).execute()
    return ListResponse(
        data=[MasteryStateResponse(**r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.put("/{state_id}", response_model=MasteryStateResponse)
async def update_mastery_state(
    state_id: int,
    data: MasteryStateUpdate,
    current_user: CurrentUser,
    client: SupaClient,
) -> MasteryStateResponse:
    """Update a mastery state by ID (filtered by user)."""
    updates = data.model_dump(exclude_unset=True, mode="json")
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = (
        await client.table("mastery_states")
        .update(updates)
        .eq("id", state_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Mastery state not found")
    return MasteryStateResponse(**result.data[0])


@router.delete("/{state_id}", status_code=204)
async def delete_mastery_state(
    state_id: int,
    current_user: CurrentUser,
    client: SupaClient,
) -> None:
    """Delete a mastery state by ID (filtered by user)."""
    result = (
        await client.table("mastery_states")
        .delete()
        .eq("id", state_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Mastery state not found")
