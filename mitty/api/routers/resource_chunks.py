"""CRUD endpoints for resource chunks."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import AsyncClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_supabase_client
from mitty.api.schemas import (
    ListResponse,
    ResourceChunkCreate,
    ResourceChunkResponse,
    ResourceChunkUpdate,
)

router = APIRouter(prefix="/resource-chunks", tags=["resource_chunks"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
SupabaseClient = Annotated[AsyncClient, Depends(get_supabase_client)]


@router.post("/", response_model=ResourceChunkResponse, status_code=201)
async def create_resource_chunk(
    data: ResourceChunkCreate,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> ResourceChunkResponse:
    """Create a new resource chunk."""
    result = (
        await client.table("resource_chunks")
        .insert(data.model_dump(mode="json"))
        .execute()
    )
    return ResourceChunkResponse.model_validate(result.data[0])


@router.get("/{chunk_id}", response_model=ResourceChunkResponse)
async def get_resource_chunk(
    chunk_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> ResourceChunkResponse:
    """Get a single resource chunk by ID."""
    result = (
        await client.table("resource_chunks")
        .select("*")
        .eq("id", chunk_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Resource chunk not found")
    return ResourceChunkResponse.model_validate(result.data)


@router.get("/", response_model=ListResponse[ResourceChunkResponse])
async def list_resource_chunks(
    resource_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> ListResponse[ResourceChunkResponse]:
    """List resource chunks for a given resource (resource_id required)."""
    result = (
        await client.table("resource_chunks")
        .select("*", count="exact")
        .eq("resource_id", resource_id)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return ListResponse[ResourceChunkResponse](
        data=[ResourceChunkResponse.model_validate(r) for r in result.data],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )


@router.put("/{chunk_id}", response_model=ResourceChunkResponse)
async def update_resource_chunk(
    chunk_id: int,
    data: ResourceChunkUpdate,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> ResourceChunkResponse:
    """Update an existing resource chunk."""
    payload = data.model_dump(mode="json", exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = (
        await client.table("resource_chunks")
        .update(payload)
        .eq("id", chunk_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Resource chunk not found")
    return ResourceChunkResponse.model_validate(result.data[0])


@router.delete("/{chunk_id}", status_code=204)
async def delete_resource_chunk(
    chunk_id: int,
    current_user: CurrentUser,
    client: SupabaseClient,
) -> None:
    """Delete a resource chunk."""
    result = await client.table("resource_chunks").delete().eq("id", chunk_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Resource chunk not found")
