"""Lightweight async Claude API wrapper with structured output.

Provides ``AIClient`` — a thin layer over the Anthropic SDK that:
- Extracts structured (Pydantic) responses via tool-use
- Retries on transient errors (429 / 5xx) with exponential backoff
- Logs per-call token usage, estimated cost, and wall-clock time
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TypeVar

import pydantic
from anthropic import APIStatusError, AsyncAnthropic

from mitty.ai.errors import AIClientError, RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=pydantic.BaseModel)

# ---------------------------------------------------------------------------
# Pricing (USD per token) — update when models change
# ---------------------------------------------------------------------------
_PRICING: dict[str, tuple[float, float]] = {
    # (input_cost_per_token, output_cost_per_token)
    "claude-sonnet-4-20250514": (3.0 / 1_000_000, 15.0 / 1_000_000),
}
_DEFAULT_PRICING = (3.0 / 1_000_000, 15.0 / 1_000_000)

# Status codes that are safe to retry
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Initial backoff delay in seconds
_BASE_BACKOFF = 0.5


class AIClient:
    """Async Claude API client with structured output support.

    Args:
        api_key: Anthropic API key.
        model: Model identifier (e.g. ``claude-sonnet-4-20250514``).
        max_retries: Maximum retry attempts for transient errors.
        max_tokens: Default max tokens for responses.

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
    ) -> None:
        if not api_key:
            msg = "Anthropic API key is required but was empty or None."
            raise AIClientError(msg)

        self._model = model
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key)

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

        Returns:
            An instance of *response_model* populated from the API response.

        Raises:
            AIClientError: On permanent API errors (4xx except 429).
            RateLimitError: When retries are exhausted on 429.
        """
        tool_name = response_model.__name__
        tool_def = {
            "name": tool_name,
            "description": f"Return structured {tool_name} data.",
            "input_schema": response_model.model_json_schema(),
        }

        message = await self._call_with_retry(
            system=system,
            user_prompt=user_prompt,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
            max_tokens=max_tokens or self._max_tokens,
        )

        # Extract the tool_use block from the response
        for block in message.content:
            if block.type == "tool_use" and block.name == tool_name:
                return response_model.model_validate(block.input)

        msg = f"No tool_use block named '{tool_name}' found in API response."
        raise AIClientError(msg)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        *,
        system: str,
        user_prompt: str,
        tools: list[dict],
        tool_choice: dict,
        max_tokens: int,
    ):
        """Execute the API call with exponential-backoff retry.

        Retries on 429 and 5xx status codes up to ``max_retries`` times.
        Non-retryable errors (e.g. 401, 400) raise immediately.
        """
        last_error: APIStatusError | None = None

        for attempt in range(1 + self._max_retries):
            try:
                start = time.monotonic()
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_prompt}],
                    tools=tools,
                    tool_choice=tool_choice,
                )
                elapsed = time.monotonic() - start
                self._log_usage(message, elapsed)
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

    def _log_usage(self, message, elapsed: float) -> None:
        """Log model, token counts, estimated cost, and elapsed time."""
        input_tok = message.usage.input_tokens
        output_tok = message.usage.output_tokens
        in_cost, out_cost = _PRICING.get(self._model, _DEFAULT_PRICING)
        cost = input_tok * in_cost + output_tok * out_cost

        logger.info(
            "LLM call: model=%s input_tokens=%d output_tokens=%d "
            "cost=$%.6f elapsed=%.2fs",
            message.model,
            input_tok,
            output_tok,
            cost,
            elapsed,
        )
