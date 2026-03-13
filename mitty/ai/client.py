"""Lightweight async Claude API wrapper with structured output.

Provides ``AIClient`` — a thin layer over the Anthropic SDK that:
- Extracts structured (Pydantic) responses via tool-use
- Retries on transient errors (429 / 5xx) with exponential backoff
- Logs per-call token usage, estimated cost, and wall-clock time
- Writes audit rows to ``ai_audit_log`` via Supabase
- Enforces per-user rate limits and cost budgets
- Integrates prompt management for role-based configuration
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import TYPE_CHECKING, Any, TypeVar

import pydantic
from anthropic import APIStatusError, AsyncAnthropic

from mitty.ai.errors import AIClientError, BudgetExceededError, RateLimitError

if TYPE_CHECKING:
    from mitty.ai.rate_limiter import RateLimiter
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=pydantic.BaseModel)

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens) — update when models change
# ---------------------------------------------------------------------------
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.0},
}
_DEFAULT_PRICING: dict[str, float] = {"input": 3.0, "output": 15.0}

# Status codes that are safe to retry
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Initial backoff delay in seconds
_BASE_BACKOFF = 0.5


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for a given model and token usage.

    Args:
        model: The model identifier string.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens consumed.

    Returns:
        Estimated cost in USD.
    """
    pricing = PRICING.get(model, _DEFAULT_PRICING)
    return (
        input_tokens * pricing["input"] / 1_000_000
        + output_tokens * pricing["output"] / 1_000_000
    )


class AIClient:
    """Async Claude API client with structured output support.

    Args:
        api_key: Anthropic API key.
        model: Model identifier (e.g. ``claude-sonnet-4-20250514``).
        max_retries: Maximum retry attempts for transient errors.
        max_tokens: Default max tokens for responses.
        rate_limiter: Optional ``RateLimiter`` instance for per-user limits.
        budget_per_session: Max USD spend per session (0 = unlimited).
        budget_per_day: Max USD spend per day (0 = unlimited).

    Raises:
        AIClientError: If *api_key* is empty or None.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
        max_tokens: int = 4096,
        rate_limiter: RateLimiter | None = None,
        budget_per_session: float = 1.0,
        budget_per_day: float = 5.0,
    ) -> None:
        if not api_key:
            msg = "Anthropic API key is required but was empty or None."
            raise AIClientError(msg)

        self._model = model
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key)
        self._rate_limiter = rate_limiter
        self._budget_per_session = budget_per_session
        self._budget_per_day = budget_per_day
        self._session_cost: float = 0.0
        # Cache for daily cost total: (date_str, cached_total)
        self._daily_cost_cache: tuple[str, float] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call_structured(
        self,
        *,
        system: str,
        user_prompt: str,
        response_model: type[T],
        max_tokens: int | None = None,
        user_id: str | None = None,
        call_type: str = "structured",
        supabase_client: AsyncClient | None = None,
        role: str | None = None,
    ) -> T:
        """Send a prompt and parse the response into *response_model*.

        Uses the Anthropic tool-use pattern: a single tool whose
        ``input_schema`` matches the Pydantic model's JSON schema.
        The model is forced to call that tool, yielding structured data.

        Args:
            system: System prompt.
            user_prompt: User message content.
            response_model: Pydantic model class to validate output.
            max_tokens: Override default max_tokens for this call.
            user_id: User ID for audit logging and rate limiting.
            call_type: Type of call for audit logging.
            supabase_client: Supabase client for writing audit rows.
            role: AI role name (from prompts.py) for config overrides.

        Returns:
            An instance of *response_model* populated from the API response.

        Raises:
            AIClientError: On permanent API errors (4xx except 429).
            RateLimitError: When retries are exhausted on 429 or
                per-user rate limit exceeded.
            BudgetExceededError: When session or daily budget exceeded.
        """
        # Resolve prompt configuration from role (if provided)
        prompt_version: str | None = None
        effective_model = self._model
        effective_max_tokens = max_tokens or self._max_tokens
        temperature: float | None = None

        if role is not None:
            from mitty.ai.prompts import get_prompt

            prompt_config = get_prompt(role)
            prompt_version = prompt_config.content_hash
            if prompt_config.model is not None:
                effective_model = prompt_config.model
            effective_max_tokens = max_tokens or prompt_config.max_tokens
            temperature = prompt_config.temperature

        # Rate limit check
        if user_id and self._rate_limiter:
            await self._rate_limiter.check_rate_limit(user_id)

        # Budget check
        if user_id and supabase_client:
            await self._check_budget(user_id, supabase_client)
        elif (
            self._budget_per_session > 0
            and self._session_cost >= self._budget_per_session
        ):
            raise BudgetExceededError(
                budget_type="session",
                limit_usd=self._budget_per_session,
                spent_usd=self._session_cost,
            )

        tool_name = response_model.__name__
        tool_def = {
            "name": tool_name,
            "description": f"Return structured {tool_name} data.",
            "input_schema": response_model.model_json_schema(),
        }

        start = time.monotonic()
        status = "success"
        error_msg: str | None = None
        input_tokens = 0
        output_tokens = 0
        cost = 0.0

        try:
            message = await self._call_with_retry(
                system=system,
                user_prompt=user_prompt,
                tools=[tool_def],
                tool_choice={"type": "tool", "name": tool_name},
                max_tokens=effective_max_tokens,
                model=effective_model,
                temperature=temperature,
            )

            elapsed = time.monotonic() - start
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = _calculate_cost(effective_model, input_tokens, output_tokens)
            self._log_usage(message, elapsed, cost)

            # Track session cost
            self._session_cost += cost

            # Record rate limit usage
            if user_id and self._rate_limiter:
                await self._rate_limiter.record_usage(
                    user_id, input_tokens + output_tokens
                )

            # Extract the tool_use block from the response
            for block in message.content:
                if block.type == "tool_use" and block.name == tool_name:
                    result = response_model.model_validate(block.input)

                    # Fire-and-forget audit write
                    if supabase_client and user_id:
                        asyncio.create_task(
                            self._write_audit_row(
                                supabase_client=supabase_client,
                                user_id=user_id,
                                call_type=call_type,
                                model=effective_model,
                                prompt_version=prompt_version,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cost_usd=cost,
                                duration_ms=int(elapsed * 1000),
                                status=status,
                                error_msg=None,
                            )
                        )

                    return result

            msg = f"No tool_use block named '{tool_name}' found in API response."
            raise AIClientError(msg)

        except (AIClientError, RateLimitError, BudgetExceededError) as exc:
            elapsed = time.monotonic() - start
            status = "rate_limited" if isinstance(exc, RateLimitError) else "error"
            error_msg = str(exc)

            # Fire-and-forget audit write on error
            if supabase_client and user_id:
                asyncio.create_task(
                    self._write_audit_row(
                        supabase_client=supabase_client,
                        user_id=user_id,
                        call_type=call_type,
                        model=effective_model,
                        prompt_version=prompt_version,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost,
                        duration_ms=int(elapsed * 1000),
                        status=status,
                        error_msg=error_msg,
                    )
                )

            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _check_budget(self, user_id: str, supabase_client: AsyncClient) -> None:
        """Check session and daily budgets, raising if exceeded."""
        # Session budget
        if (
            self._budget_per_session > 0
            and self._session_cost >= self._budget_per_session
        ):
            raise BudgetExceededError(
                budget_type="session",
                limit_usd=self._budget_per_session,
                spent_usd=self._session_cost,
            )

        # Daily budget
        if self._budget_per_day > 0:
            daily_total = await self._get_daily_cost(user_id, supabase_client)
            if daily_total >= self._budget_per_day:
                raise BudgetExceededError(
                    budget_type="daily",
                    limit_usd=self._budget_per_day,
                    spent_usd=daily_total,
                )

    async def _get_daily_cost(
        self, user_id: str, supabase_client: AsyncClient
    ) -> float:
        """Query ai_audit_log for today's total cost, with caching."""
        today_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")

        # Return cached value if same day
        if self._daily_cost_cache and self._daily_cost_cache[0] == today_str:
            return self._daily_cost_cache[1] + self._session_cost

        try:
            result = (
                await supabase_client.table("ai_audit_log")
                .select("cost_usd")
                .eq("user_id", user_id)
                .gte("created_at", f"{today_str}T00:00:00Z")
                .eq("status", "success")
                .execute()
            )
            db_total = sum(float(row["cost_usd"]) for row in (result.data or []))
            self._daily_cost_cache = (today_str, db_total)
            return db_total + self._session_cost
        except Exception:
            logger.warning(
                "Failed to query daily cost from ai_audit_log", exc_info=True
            )
            # Fall back to session cost only
            return self._session_cost

    async def _write_audit_row(
        self,
        *,
        supabase_client: AsyncClient,
        user_id: str,
        call_type: str,
        model: str,
        prompt_version: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        duration_ms: int,
        status: str,
        error_msg: str | None,
    ) -> None:
        """Write an audit row to ai_audit_log. Failures are logged, not raised."""
        row: dict[str, Any] = {
            "user_id": user_id,
            "call_type": call_type,
            "model": model,
            "prompt_version": prompt_version or "",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "status": status,
            "error_msg": error_msg,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        try:
            await supabase_client.table("ai_audit_log").insert(row).execute()
        except Exception:
            logger.warning(
                "Failed to write audit row to ai_audit_log",
                exc_info=True,
            )

    async def _call_with_retry(
        self,
        *,
        system: str,
        user_prompt: str,
        tools: list[dict],
        tool_choice: dict,
        max_tokens: int,
        model: str | None = None,
        temperature: float | None = None,
    ):
        """Execute the API call with exponential-backoff retry.

        Retries on 429 and 5xx status codes up to ``max_retries`` times.
        Non-retryable errors (e.g. 401, 400) raise immediately.
        """
        effective_model = model or self._model
        last_error: APIStatusError | None = None

        for attempt in range(1 + self._max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": effective_model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "tools": tools,
                    "tool_choice": tool_choice,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature

                message = await self._client.messages.create(**kwargs)
                return message

            except APIStatusError as exc:
                last_error = exc

                if exc.status_code not in _RETRYABLE_STATUS_CODES:
                    raise AIClientError(
                        exc.message,
                        status_code=exc.status_code,
                    ) from exc

                if attempt < self._max_retries:
                    delay = _BASE_BACKOFF * (2**attempt)
                    logger.warning(
                        "Anthropic API %d (attempt %d/%d), retrying in %.1fs",
                        exc.status_code,
                        attempt + 1,
                        1 + self._max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)

        # All retries exhausted
        assert last_error is not None
        if last_error.status_code == 429:
            raise RateLimitError(last_error.message) from last_error
        raise AIClientError(
            last_error.message,
            status_code=last_error.status_code,
        ) from last_error

    def _log_usage(self, message, elapsed: float, cost: float | None = None) -> None:
        """Log model, token counts, estimated cost, and elapsed time."""
        input_tok = message.usage.input_tokens
        output_tok = message.usage.output_tokens
        if cost is None:
            cost = _calculate_cost(message.model, input_tok, output_tok)

        logger.info(
            "LLM call: model=%s input_tokens=%d output_tokens=%d "
            "cost=$%.6f elapsed=%.2fs",
            message.model,
            input_tok,
            output_tok,
            cost,
            elapsed,
        )
