"""CRUD router for student_signals (daily check-ins).

User isolation is enforced by RLS (via the user JWT set on the client)
and belt-and-suspenders user_id filters in queries.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import AsyncClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    ListResponse,
    StudentSignalCreate,
    StudentSignalResponse,
    StudentSignalUpdate,
)

router = APIRouter(prefix="/student-signals", tags=["student_signals"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated[AsyncClient, Depends(get_user_client)]


@router.post("/", response_model=StudentSignalResponse, status_code=201)
async def create_signal(
    data: StudentSignalCreate,
    current_user: CurrentUser,
    client: UserClient,
) -> StudentSignalResponse:
    """Create a new student signal. user_id is injected from auth."""
    row = data.model_dump(exclude_none=True, mode="json")
    row["user_id"] = current_user["user_id"]
    result = await client.table("student_signals").insert(row).execute()
    return StudentSignalResponse.model_validate(result.data[0])


@router.get("/", response_model=ListResponse[StudentSignalResponse])
async def list_signals(
    current_user: CurrentUser,
    client: UserClient,
    offset: int = Query(default=0, ge=0),  # noqa: B008
    limit: int = Query(default=20, ge=1, le=100),  # noqa: B008
) -> ListResponse[StudentSignalResponse]:
    """List signals for the authenticated user (paginated)."""
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
    current_user: CurrentUser,
    client: UserClient,
) -> StudentSignalResponse:
    """Get a single signal by ID (scoped to the authenticated user)."""
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
    current_user: CurrentUser,
    client: UserClient,
) -> StudentSignalResponse:
    """Update a signal (scoped to the authenticated user)."""
    updates = data.model_dump(exclude_unset=True, mode="json")
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
    current_user: CurrentUser,
    client: UserClient,
) -> None:
    """Delete a signal (scoped to the authenticated user)."""
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
