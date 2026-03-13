"""CRUD router for study_blocks.

Ownership is verified via plan_id join — every block's plan must belong
to the authenticated user.  RLS provides defense-in-depth.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    ListResponse,
    StudyBlockCreate,
    StudyBlockResponse,
    StudyBlockUpdate,
)
from supabase import AsyncClient

router = APIRouter(prefix="/study-blocks", tags=["study_blocks"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated[AsyncClient, Depends(get_user_client)]


async def _verify_plan_ownership(
    client: object,
    plan_id: int,
    user_id: str,
) -> None:
    """Raise 404 if the plan_id does not belong to the given user."""
    result = (
        await client.table("study_plans")  # type: ignore[union-attr]
        .select("id")
        .eq("id", plan_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "PLAN_NOT_FOUND", "message": "Study plan not found"},
        )


async def _verify_block_ownership(
    client: object,
    block_id: int,
    user_id: str,
) -> dict:
    """Return the block row if it exists and belongs to the user (via plan join).

    Raises 404 otherwise.
    """
    result = (
        await client.table("study_blocks")  # type: ignore[union-attr]
        .select("*, study_plans!inner(user_id)")
        .eq("id", block_id)
        .eq("study_plans.user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Study block not found"},
        )
    return result.data


@router.post("/", response_model=StudyBlockResponse, status_code=201)
async def create_block(
    data: StudyBlockCreate,
    current_user: CurrentUser,
    client: UserClient,
) -> StudyBlockResponse:
    """Create a new study block. Plan ownership is verified first."""
    await _verify_plan_ownership(client, data.plan_id, current_user["user_id"])
    row = data.model_dump(exclude_none=True, mode="json")
    result = await client.table("study_blocks").insert(row).execute()
    return StudyBlockResponse.model_validate(result.data[0])


@router.get("/", response_model=ListResponse[StudyBlockResponse])
async def list_blocks(
    current_user: CurrentUser,
    client: UserClient,
    plan_id: int = Query(..., description="Required: filter by plan ID"),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
) -> ListResponse[StudyBlockResponse]:
    """List blocks for a plan (plan ownership verified)."""
    await _verify_plan_ownership(client, plan_id, current_user["user_id"])
    result = (
        await client.table("study_blocks")
        .select("*", count="exact")
        .eq("plan_id", plan_id)
        .order("sort_order")
        .range(offset, offset + limit - 1)
        .execute()
    )
    return ListResponse(
        data=[StudyBlockResponse.model_validate(r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{block_id}", response_model=StudyBlockResponse)
async def get_block(
    block_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> StudyBlockResponse:
    """Get a single block (ownership verified via plan join)."""
    row = await _verify_block_ownership(client, block_id, current_user["user_id"])
    # Remove the nested join data before validating
    row.pop("study_plans", None)
    return StudyBlockResponse.model_validate(row)


@router.put("/{block_id}", response_model=StudyBlockResponse)
async def update_block(
    block_id: int,
    data: StudyBlockUpdate,
    current_user: CurrentUser,
    client: UserClient,
) -> StudyBlockResponse:
    """Update a block (ownership verified via plan join)."""
    await _verify_block_ownership(client, block_id, current_user["user_id"])
    updates = data.model_dump(exclude_unset=True, mode="json")
    if not updates:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_FIELDS", "message": "No fields to update"},
        )
    result = (
        await client.table("study_blocks").update(updates).eq("id", block_id).execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Study block not found"},
        )
    return StudyBlockResponse.model_validate(result.data[0])


@router.delete("/{block_id}", status_code=204)
async def delete_block(
    block_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> None:
    """Delete a block (ownership verified via plan join)."""
    await _verify_block_ownership(client, block_id, current_user["user_id"])
    await client.table("study_blocks").delete().eq("id", block_id).execute()
