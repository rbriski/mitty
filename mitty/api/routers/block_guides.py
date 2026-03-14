"""Block guide and artifact endpoints for Phase 6 executable study guides.

- GET  /study-plans/{plan_id}/guides           — batch fetch all guides for a plan
- GET  /study-blocks/{block_id}/guide          — single guide for a block
- POST /study-blocks/{block_id}/guide/retry    — recompile guide (stub)
- POST /study-blocks/{block_id}/artifacts      — submit a student artifact
- GET  /study-blocks/{block_id}/artifacts      — list artifacts (paginated)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import (
    BlockArtifactCreate,
    BlockArtifactResponse,
    BlockGuideResponse,
    ListResponse,
)

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["block_guides"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _verify_block_ownership(
    client: AsyncClient,
    block_id: int,
    user_id: str,
) -> dict[str, Any]:
    """Fetch a study block, verifying ownership via plan join.

    Raises 404 with BLOCK_NOT_FOUND if the block does not exist or
    does not belong to the authenticated user.
    """
    result = await (
        client.table("study_blocks")
        .select("*, study_plans!inner(user_id)")
        .eq("id", block_id)
        .eq("study_plans.user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BLOCK_NOT_FOUND",
                "message": "Study block not found.",
            },
        )
    data = result.data
    data.pop("study_plans", None)
    return data


async def _verify_plan_ownership(
    client: AsyncClient,
    plan_id: int,
    user_id: str,
) -> None:
    """Raise 404 if the plan does not belong to the given user."""
    result = await (
        client.table("study_plans")
        .select("id")
        .eq("id", plan_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PLAN_NOT_FOUND",
                "message": "Study plan not found.",
            },
        )


# ---------------------------------------------------------------------------
# GET /study-plans/{plan_id}/guides
# ---------------------------------------------------------------------------


@router.get(
    "/study-plans/{plan_id}/guides",
    response_model=list[BlockGuideResponse],
)
async def batch_get_guides(
    plan_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> list[BlockGuideResponse]:
    """Fetch all compiled guides for every block in a study plan.

    Verifies plan ownership, then queries study_block_guides joined
    with study_blocks filtered by plan_id.
    """
    user_id = current_user["user_id"]
    await _verify_plan_ownership(client, plan_id, user_id)

    # Fetch block IDs for this plan
    blocks_result = await (
        client.table("study_blocks").select("id").eq("plan_id", plan_id).execute()
    )
    block_ids = [b["id"] for b in (blocks_result.data or [])]
    if not block_ids:
        return []

    # Fetch guides for those blocks
    guides_result = await (
        client.table("study_block_guides")
        .select("*")
        .in_("block_id", block_ids)
        .execute()
    )

    return [
        BlockGuideResponse.model_validate(row) for row in (guides_result.data or [])
    ]


# ---------------------------------------------------------------------------
# GET /study-blocks/{block_id}/guide
# ---------------------------------------------------------------------------


@router.get(
    "/study-blocks/{block_id}/guide",
    response_model=BlockGuideResponse,
)
async def get_guide(
    block_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> BlockGuideResponse:
    """Fetch the compiled guide for a single study block.

    Returns 404 GUIDE_NOT_FOUND if no guide has been compiled yet.
    """
    user_id = current_user["user_id"]
    await _verify_block_ownership(client, block_id, user_id)

    result = await (
        client.table("study_block_guides")
        .select("*")
        .eq("block_id", block_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "GUIDE_NOT_FOUND",
                "message": "No guide found for this block.",
            },
        )
    return BlockGuideResponse.model_validate(result.data)


# ---------------------------------------------------------------------------
# POST /study-blocks/{block_id}/guide/retry
# ---------------------------------------------------------------------------


@router.post(
    "/study-blocks/{block_id}/guide/retry",
    response_model=BlockGuideResponse,
    status_code=200,
)
async def retry_guide(
    block_id: int,
    current_user: CurrentUser,
    client: UserClient,
) -> BlockGuideResponse:
    """Recompile the guide for a study block.

    Currently returns 501 Not Implemented — compiler integration is
    handled by US-009.
    """
    user_id = current_user["user_id"]
    await _verify_block_ownership(client, block_id, user_id)

    raise HTTPException(
        status_code=501,
        detail={
            "code": "GUIDE_FAILED",
            "message": "Guide recompilation is not yet implemented.",
        },
    )


# ---------------------------------------------------------------------------
# POST /study-blocks/{block_id}/artifacts
# ---------------------------------------------------------------------------


@router.post(
    "/study-blocks/{block_id}/artifacts",
    response_model=BlockArtifactResponse,
    status_code=201,
)
async def create_artifact(
    block_id: int,
    data: BlockArtifactCreate,
    current_user: CurrentUser,
    client: UserClient,
) -> BlockArtifactResponse:
    """Submit a student artifact for a study block step."""
    user_id = current_user["user_id"]
    await _verify_block_ownership(client, block_id, user_id)

    row = {
        "block_id": block_id,
        "step_number": data.step_number,
        "artifact_type": data.artifact_type,
        "content_json": data.content_json,
    }
    result = await client.table("block_artifacts").insert(row).execute()
    if not result.data:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INSERT_FAILED",
                "message": "Failed to store artifact.",
            },
        )
    return BlockArtifactResponse.model_validate(result.data[0])


# ---------------------------------------------------------------------------
# GET /study-blocks/{block_id}/artifacts
# ---------------------------------------------------------------------------


@router.get(
    "/study-blocks/{block_id}/artifacts",
    response_model=ListResponse[BlockArtifactResponse],
)
async def list_artifacts(
    block_id: int,
    current_user: CurrentUser,
    client: UserClient,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> ListResponse[BlockArtifactResponse]:
    """List student artifacts for a study block, ordered by step number."""
    user_id = current_user["user_id"]
    await _verify_block_ownership(client, block_id, user_id)

    result = await (
        client.table("block_artifacts")
        .select("*", count="exact")
        .eq("block_id", block_id)
        .order("step_number")
        .range(offset, offset + limit - 1)
        .execute()
    )

    return ListResponse(
        data=[BlockArtifactResponse.model_validate(r) for r in (result.data or [])],
        total=result.count or 0,
        offset=offset,
        limit=limit,
    )
