"""CRUD endpoints for resources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    ListResponse,
    ResourceCreate,
    ResourceResponse,
    ResourceUpdate,
)
from supabase import AsyncClient

router = APIRouter(prefix="/resources", tags=["resources"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
SupabaseClient = Annotated[AsyncClient, Depends(get_user_client)]


@router.post("/", response_model=ResourceResponse, status_code=201)
async def create_resource(
    data: ResourceCreate,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> ResourceResponse:
    """Create a new resource."""
    result = (
        await client.table("resources").insert(data.model_dump(mode="json")).execute()
    )
    return ResourceResponse.model_validate(result.data[0])


@router.get("/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> ResourceResponse:
    """Get a single resource by ID."""
    result = (
        await client.table("resources")
        .select("*")
        .eq("id", resource_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Resource not found")
    return ResourceResponse.model_validate(result.data)


@router.get("/", response_model=ListResponse[ResourceResponse])
async def list_resources(
    current_user: CurrentUser,
    client: SupabaseClient,
    course_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> ListResponse[ResourceResponse]:
    """List resources with optional course_id filter and pagination."""
    query = client.table("resources").select("*", count="exact")
    if course_id is not None:
        query = query.eq("course_id", course_id)
    result = await query.range(offset, offset + limit - 1).execute()
    return ListResponse[ResourceResponse](
        data=[ResourceResponse.model_validate(r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.put("/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    resource_id: int,
    data: ResourceUpdate,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> ResourceResponse:
    """Update an existing resource."""
    payload = data.model_dump(mode="json", exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = (
        await client.table("resources").update(payload).eq("id", resource_id).execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Resource not found")
    return ResourceResponse.model_validate(result.data[0])


@router.delete("/{resource_id}", status_code=204)
async def delete_resource(
    resource_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> None:
    """Delete a resource."""
    result = await client.table("resources").delete().eq("id", resource_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Resource not found")
