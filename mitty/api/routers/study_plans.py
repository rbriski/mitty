"""CRUD router for study_plans.

User isolation enforced by RLS + belt-and-suspenders user_id filters.
"""

from __future__ import annotations

import logging
from datetime import (
    UTC,
    date,  # noqa: TCH003 — must be available at runtime for FastAPI/Pydantic
    datetime,
)
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    ListResponse,
    StudyBlockResponse,
    StudyPlanCreate,
    StudyPlanResponse,
    StudyPlanUpdate,
    StudyPlanWithBlocksResponse,
)
from mitty.planner.generator import PlanGenerationError, generate_plan
from supabase import AsyncClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/study-plans", tags=["study_plans"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated[AsyncClient, Depends(get_user_client)]


@router.post("/generate", response_model=StudyPlanWithBlocksResponse, status_code=201)
async def generate_study_plan(
    current_user: CurrentUser,
    client: UserClient,
) -> StudyPlanWithBlocksResponse:
    """Trigger study plan generation for today.

    - Returns 400 NO_SIGNAL_TODAY if no recent student signal.
    - Returns 409 PLAN_EXISTS if an active/completed plan already exists.
    - Silently replaces draft plans.
    """
    user_id = current_user["user_id"]
    plan_date = datetime.now(UTC).date()

    try:
        result = await generate_plan(client, user_id, plan_date)
    except PlanGenerationError as exc:
        if exc.code == "NO_SIGNAL":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "NO_SIGNAL_TODAY",
                    "message": "No recent student signal found. "
                    "Complete a check-in first.",
                },
            ) from None
        if exc.code == "PLAN_EXISTS":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PLAN_EXISTS",
                    "message": "An active or completed plan already exists for today.",
                },
            ) from None
        # Unexpected generation error
        logger.error("Plan generation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "GENERATION_FAILED",
                "message": "Plan generation failed unexpectedly.",
            },
        ) from None

    # Read back the full plan + blocks from the database.
    plan_resp = await (
        client.table("study_plans")
        .select("*")
        .eq("id", result.plan_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not plan_resp.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "GENERATION_FAILED",
                "message": "Plan was generated but could not be read back.",
            },
        )

    blocks_resp = await (
        client.table("study_blocks")
        .select("*")
        .eq("plan_id", result.plan_id)
        .order("sort_order")
        .execute()
    )

    plan_data = plan_resp.data
    plan_data["blocks"] = [
        StudyBlockResponse.model_validate(b).model_dump()
        for b in (blocks_resp.data or [])
    ]
    return StudyPlanWithBlocksResponse.model_validate(plan_data)


@router.get("/today", response_model=StudyPlanWithBlocksResponse)
async def get_today_plan(
    current_user: CurrentUser,
    client: UserClient,
) -> StudyPlanWithBlocksResponse:
    """Get today's study plan with nested blocks, or 404 if none exists."""
    user_id = current_user["user_id"]
    today = datetime.now(UTC).date().isoformat()

    plan_resp = await (
        client.table("study_plans")
        .select("*")
        .eq("user_id", user_id)
        .eq("plan_date", today)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not plan_resp.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": "No study plan found for today.",
            },
        )

    plan_data = plan_resp.data[0]
    plan_id = plan_data["id"]

    blocks_resp = await (
        client.table("study_blocks")
        .select("*")
        .eq("plan_id", plan_id)
        .order("sort_order")
        .execute()
    )

    plan_data["blocks"] = [
        StudyBlockResponse.model_validate(b).model_dump()
        for b in (blocks_resp.data or [])
    ]
    return StudyPlanWithBlocksResponse.model_validate(plan_data)


@router.post("/", response_model=StudyPlanResponse, status_code=201)
async def create_plan(
    data: StudyPlanCreate,
    current_user: CurrentUser,
    client: UserClient,
) -> StudyPlanResponse:
    """Create a new study plan. user_id is injected from auth."""
    row = data.model_dump(exclude_none=True, mode="json")
    row["user_id"] = current_user["user_id"]
    result = await client.table("study_plans").insert(row).execute()
    return StudyPlanResponse.model_validate(result.data[0])


@router.get("/", response_model=ListResponse[StudyPlanResponse])
async def list_plans(
    current_user: CurrentUser,
    client: UserClient,
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
    date_from: date | None = Query(default=None),  # noqa: B008
    date_to: date | None = Query(default=None),  # noqa: B008
) -> ListResponse[StudyPlanResponse]:
    """List plans for the authenticated user (paginated, optional date filter)."""
    query = (
        client.table("study_plans")
        .select("*", count="exact")
        .eq("user_id", current_user["user_id"])
        .order("plan_date", desc=True)
    )
    if date_from is not None:
        query = query.gte("plan_date", date_from.isoformat())
    if date_to is not None:
        query = query.lte("plan_date", date_to.isoformat())
    result = await query.range(offset, offset + limit - 1).execute()
    return ListResponse(
        data=[StudyPlanResponse.model_validate(r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{plan_id}", response_model=StudyPlanResponse)
async def get_plan(
    plan_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> StudyPlanResponse:
    """Get a single plan by ID (scoped to the authenticated user)."""
    result = (
        await client.table("study_plans")
        .select("*")
        .eq("id", plan_id)
        .eq("user_id", current_user["user_id"])
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Study plan not found"},
        )
    return StudyPlanResponse.model_validate(result.data)


@router.put("/{plan_id}", response_model=StudyPlanResponse)
async def update_plan(
    plan_id: int,
    data: StudyPlanUpdate,
    current_user: CurrentUser,
    client: UserClient,
) -> StudyPlanResponse:
    """Update a plan (scoped to the authenticated user)."""
    updates = data.model_dump(exclude_unset=True, mode="json")
    if not updates:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_FIELDS", "message": "No fields to update"},
        )
    result = (
        await client.table("study_plans")
        .update(updates)
        .eq("id", plan_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Study plan not found"},
        )
    return StudyPlanResponse.model_validate(result.data[0])


@router.delete("/{plan_id}", status_code=204)
async def delete_plan(
    plan_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> None:
    """Delete a plan (scoped to the authenticated user)."""
    result = (
        await client.table("study_plans")
        .delete()
        .eq("id", plan_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Study plan not found"},
        )
