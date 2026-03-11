"""CRUD endpoints for assessments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import AsyncClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_supabase_client
from mitty.api.schemas import (
    AssessmentCreate,
    AssessmentResponse,
    AssessmentUpdate,
    ListResponse,
)

router = APIRouter(prefix="/assessments", tags=["assessments"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
SupabaseClient = Annotated[AsyncClient, Depends(get_supabase_client)]


@router.post("/", response_model=AssessmentResponse, status_code=201)
async def create_assessment(
    data: AssessmentCreate,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> AssessmentResponse:
    """Create a new assessment."""
    result = (
        await client.table("assessments").insert(data.model_dump(mode="json")).execute()
    )
    return AssessmentResponse.model_validate(result.data[0])


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(
    assessment_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> AssessmentResponse:
    """Get a single assessment by ID."""
    result = (
        await client.table("assessments")
        .select("*")
        .eq("id", assessment_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return AssessmentResponse.model_validate(result.data)


@router.get("/", response_model=ListResponse[AssessmentResponse])
async def list_assessments(
    current_user: CurrentUser,
    client: SupabaseClient,
    course_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> ListResponse[AssessmentResponse]:
    """List assessments with optional course_id filter and pagination."""
    query = client.table("assessments").select("*", count="exact")
    if course_id is not None:
        query = query.eq("course_id", course_id)
    result = await query.range(offset, offset + limit - 1).execute()
    return ListResponse[AssessmentResponse](
        data=[AssessmentResponse.model_validate(r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.put("/{assessment_id}", response_model=AssessmentResponse)
async def update_assessment(
    assessment_id: int,
    data: AssessmentUpdate,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> AssessmentResponse:
    """Update an existing assessment."""
    payload = data.model_dump(mode="json", exclude_unset=True)
    result = (
        await client.table("assessments")
        .update(payload)
        .eq("id", assessment_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return AssessmentResponse.model_validate(result.data[0])


@router.delete("/{assessment_id}", status_code=204)
async def delete_assessment(
    assessment_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> None:
    """Delete an assessment."""
    result = (
        await client.table("assessments").delete().eq("id", assessment_id).execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Assessment not found")
