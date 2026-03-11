"""CRUD routes for app_config (singleton, id=1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_supabase_client, get_user_client
from mitty.api.schemas import AppConfigResponse, AppConfigUpdate

if TYPE_CHECKING:
    from supabase import AsyncClient

router = APIRouter(prefix="/config", tags=["config"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
AnonClient = Annotated["AsyncClient", Depends(get_supabase_client)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]


@router.get("/", response_model=AppConfigResponse)
async def get_config(
    client: AnonClient,
) -> AppConfigResponse:
    """Read the app config singleton (public, no auth required)."""
    result = await client.table("app_config").select("*").eq("id", 1).single().execute()
    return AppConfigResponse(**result.data)


@router.put("/", response_model=AppConfigResponse)
async def update_config(
    data: AppConfigUpdate,
    current_user: CurrentUser,
    client: UserClient,
) -> AppConfigResponse:
    """Update the app config singleton (auth required)."""
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        # Nothing to update, just return current
        result = (
            await client.table("app_config").select("*").eq("id", 1).single().execute()
        )
        return AppConfigResponse(**result.data)
    result = await client.table("app_config").update(updates).eq("id", 1).execute()
    return AppConfigResponse(**result.data[0])
