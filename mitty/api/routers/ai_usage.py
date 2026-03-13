"""AI usage endpoint — cost summary from ai_audit_log."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.schemas import AICostSummaryResponse, CallTypeBreakdown

if TYPE_CHECKING:
    from supabase import AsyncClient

router = APIRouter(prefix="/ai", tags=["ai_usage"])

CurrentUser = Annotated[dict, Depends(get_current_user)]
UserClient = Annotated["AsyncClient", Depends(get_user_client)]


@router.get("/usage", response_model=AICostSummaryResponse)
async def get_ai_usage(
    current_user: CurrentUser,
    client: UserClient,
    start_date: str | None = Query(default=None),  # noqa: B008
    end_date: str | None = Query(default=None),  # noqa: B008
) -> AICostSummaryResponse:
    """Return aggregated AI usage cost summary for the current user."""
    query = (
        client.table("ai_audit_log")
        .select("call_type,input_tokens,output_tokens,cost_usd")
        .eq("user_id", current_user["user_id"])
    )

    if start_date is not None:
        query = query.gte("created_at", start_date)
    if end_date is not None:
        query = query.lte("created_at", end_date)

    result = await query.execute()
    rows = result.data or []

    # Aggregate in Python (fine for v1 — low volume)
    total_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0

    by_type: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )

    for row in rows:
        total_calls += 1
        inp = row.get("input_tokens") or 0
        out = row.get("output_tokens") or 0
        cost = float(row.get("cost_usd") or 0)
        total_input_tokens += inp
        total_output_tokens += out
        total_cost_usd += cost

        bucket = by_type[row.get("call_type") or "unknown"]
        bucket["calls"] += 1
        bucket["input_tokens"] += inp
        bucket["output_tokens"] += out
        bucket["cost_usd"] += cost

    breakdown = [
        CallTypeBreakdown(call_type=ct, **vals) for ct, vals in sorted(by_type.items())
    ]

    return AICostSummaryResponse(
        total_calls=total_calls,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cost_usd=total_cost_usd,
        breakdown=breakdown,
    )
