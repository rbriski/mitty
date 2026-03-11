"""CRUD router for study_plans.

Every query filters by the authenticated user's ID to enforce isolation.
"""

from __future__ import annotations

from datetime import (
    date,  # noqa: TCH003 — must be available at runtime for FastAPI/Pydantic
)

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from mitty.api.auth import get_current_user
from mitty.api.schemas import (
    ListResponse,
    StudyPlanCreate,
    StudyPlanResponse,
    StudyPlanUpdate,
)

router = APIRouter(prefix="/study-plans", tags=["study_plans"])


def _get_client(request: Request):  # noqa: ANN202
    """Return the Supabase async client from app state."""
    client = getattr(request.app.state, "supabase_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return client


@router.post("/", response_model=StudyPlanResponse, status_code=201)
async def create_plan(
    data: StudyPlanCreate,
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> StudyPlanResponse:
    """Create a new study plan. user_id is injected from auth."""
    client = _get_client(request)
    row = data.model_dump(exclude_none=True, mode="json")
    row["user_id"] = current_user["user_id"]
    result = await client.table("study_plans").insert(row).execute()
    return StudyPlanResponse.model_validate(result.data[0])


@router.get("/", response_model=ListResponse[StudyPlanResponse])
async def list_plans(
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
    date_from: date | None = Query(default=None),  # noqa: B008
    date_to: date | None = Query(default=None),  # noqa: B008
) -> ListResponse[StudyPlanResponse]:
    """List plans for the authenticated user (paginated, optional date filter)."""
    client = _get_client(request)
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
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> StudyPlanResponse:
    """Get a single plan by ID (scoped to the authenticated user)."""
    client = _get_client(request)
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
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> StudyPlanResponse:
    """Update a plan (scoped to the authenticated user)."""
    client = _get_client(request)
    updates = data.model_dump(exclude_none=True, mode="json")
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
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> None:
    """Delete a plan (scoped to the authenticated user)."""
    client = _get_client(request)
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
