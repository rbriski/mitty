"""CRUD router for student_signals (daily check-ins).

Every query filters by the authenticated user's ID to enforce isolation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from mitty.api.auth import get_current_user
from mitty.api.schemas import (
    ListResponse,
    StudentSignalCreate,
    StudentSignalResponse,
    StudentSignalUpdate,
)

router = APIRouter(prefix="/student-signals", tags=["student_signals"])


def _get_client(request: Request):  # noqa: ANN202
    """Return the Supabase async client from app state."""
    client = getattr(request.app.state, "supabase_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return client


@router.post("/", response_model=StudentSignalResponse, status_code=201)
async def create_signal(
    data: StudentSignalCreate,
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> StudentSignalResponse:
    """Create a new student signal. user_id is injected from auth."""
    client = _get_client(request)
    row = data.model_dump(exclude_none=True, mode="json")
    row["user_id"] = current_user["user_id"]
    result = await client.table("student_signals").insert(row).execute()
    return StudentSignalResponse.model_validate(result.data[0])


@router.get("/", response_model=ListResponse[StudentSignalResponse])
async def list_signals(
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
) -> ListResponse[StudentSignalResponse]:
    """List signals for the authenticated user (paginated)."""
    client = _get_client(request)
    query = (
        client.table("student_signals")
        .select("*", count="exact")
        .eq("user_id", current_user["user_id"])
        .order("recorded_at", desc=True)
    )
    result = await query.range(offset, offset + limit - 1).execute()
    return ListResponse(
        data=[StudentSignalResponse.model_validate(r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/{signal_id}", response_model=StudentSignalResponse)
async def get_signal(
    signal_id: int,
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> StudentSignalResponse:
    """Get a single signal by ID (scoped to the authenticated user)."""
    client = _get_client(request)
    result = (
        await client.table("student_signals")
        .select("*")
        .eq("id", signal_id)
        .eq("user_id", current_user["user_id"])
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Student signal not found"},
        )
    return StudentSignalResponse.model_validate(result.data)


@router.put("/{signal_id}", response_model=StudentSignalResponse)
async def update_signal(
    signal_id: int,
    data: StudentSignalUpdate,
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> StudentSignalResponse:
    """Update a signal (scoped to the authenticated user)."""
    client = _get_client(request)
    updates = data.model_dump(exclude_none=True, mode="json")
    if not updates:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_FIELDS", "message": "No fields to update"},
        )
    result = (
        await client.table("student_signals")
        .update(updates)
        .eq("id", signal_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Student signal not found"},
        )
    return StudentSignalResponse.model_validate(result.data[0])


@router.delete("/{signal_id}", status_code=204)
async def delete_signal(
    signal_id: int,
    request: Request,
    current_user: dict[str, str] = Depends(get_current_user),  # noqa: B008
) -> None:
    """Delete a signal (scoped to the authenticated user)."""
    client = _get_client(request)
    result = (
        await client.table("student_signals")
        .delete()
        .eq("id", signal_id)
        .eq("user_id", current_user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Student signal not found"},
        )
