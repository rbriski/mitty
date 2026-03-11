"""CRUD routes for practice_results (user-scoped)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_supabase_client
from mitty.api.schemas import (
    ListResponse,
    PracticeResultCreate,
    PracticeResultResponse,
    PracticeResultUpdate,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

router = APIRouter(prefix="/practice-results", tags=["practice_results"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
SupaClient = Annotated["AsyncClient", Depends(get_supabase_client)]


@router.post("/", response_model=PracticeResultResponse, status_code=201)
async def create_practice_result(
    data: PracticeResultCreate,
    current_user: CurrentUser,
    client: SupaClient,
) -> PracticeResultResponse:
    """Create a new practice result (user_id injected from auth)."""
    row = data.model_dump(exclude_none=True)
    row["user_id"] = current_user["user_id"]
    result = await client.table("practice_results").insert(row).execute()
    return PracticeResultResponse(**result.data[0])


@router.get("/{result_id}", response_model=PracticeResultResponse)
async def get_practice_result(
    result_id: int,
    current_user: CurrentUser,
    client: SupaClient,
) -> PracticeResultResponse:
    """Get a single practice result by ID (filtered by user)."""
    result = (
        await client.table("practice_results")
        .select("*")
        .eq("id", result_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Practice result not found")
    return PracticeResultResponse(**result.data[0])


@router.get("/", response_model=ListResponse[PracticeResultResponse])
async def list_practice_results(
    current_user: CurrentUser,
    client: SupaClient,
    course_id: int | None = Query(default=None),
    study_block_id: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> ListResponse[PracticeResultResponse]:
    """List practice results for the current user, ordered by created_at DESC."""
    query = (
        client.table("practice_results")
        .select("*", count="exact")
        .eq("user_id", current_user["user_id"])
    )
    if course_id is not None:
        query = query.eq("course_id", course_id)
    if study_block_id is not None:
        query = query.eq("study_block_id", study_block_id)
    result = (
        await query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return ListResponse(
        data=[PracticeResultResponse(**r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.put("/{result_id}", response_model=PracticeResultResponse)
async def update_practice_result(
    result_id: int,
    data: PracticeResultUpdate,
    current_user: CurrentUser,
    client: SupaClient,
) -> PracticeResultResponse:
    """Update a practice result by ID (filtered by user)."""
    updates = data.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = (
        await client.table("practice_results")
        .update(updates)
        .eq("id", result_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Practice result not found")
    return PracticeResultResponse(**result.data[0])


@router.delete("/{result_id}", status_code=204)
async def delete_practice_result(
    result_id: int,
    current_user: CurrentUser,
    client: SupaClient,
) -> None:
    """Delete a practice result by ID (filtered by user)."""
    result = (
        await client.table("practice_results")
        .delete()
        .eq("id", result_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Practice result not found")
