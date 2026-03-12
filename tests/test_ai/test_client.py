"""Tests for mitty.ai.client — AIClient structured output wrapper.

Covers: happy path, retry on 429/5xx, permanent failure on 4xx,
max-retry exhaustion, token/cost logging, and missing-key guard.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from anthropic import APIStatusError

from mitty.ai.client import AIClient
from mitty.ai.errors import AIClientError, RateLimitError

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class FruitClassification(pydantic.BaseModel):
    """Simple response model for testing structured output."""

    name: str
    color: str
    is_citrus: bool


def _make_tool_use_block(
    data: dict[str, Any],
    *,
    block_id: str = "toolu_test",
    name: str = "FruitClassification",
) -> MagicMock:
    """Create a mock ToolUseBlock content block."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = block_id
    block.name = name
    block.input = data
    return block


def _make_message(
    data: dict[str, Any],
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    model: str = "claude-sonnet-4-20250514",
) -> MagicMock:
    """Build a mock Message with a single tool_use content block."""
    msg = MagicMock()
    msg.content = [_make_tool_use_block(data)]
    msg.model = model
    msg.usage = MagicMock()
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    return msg


def _make_api_status_error(status_code: int, message: str = "err") -> APIStatusError:
    """Build an APIStatusError with the given status code."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.text = message
    err = APIStatusError.__new__(APIStatusError)
    err.status_code = status_code
    err.message = message
    err.response = mock_response
    err.body = None
    err.args = (message,)
    return err


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCallStructuredReturnsParsedModel:
    """call_structured returns a validated pydantic model on success."""

    async def test_call_structured_returns_parsed_model(self) -> None:
        client = AIClient(api_key="sk-test", model="claude-sonnet-4-20250514")

        mock_msg = _make_message(
            {"name": "Lemon", "color": "yellow", "is_citrus": True}
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_msg

            result = await client.call_structured(
                system="You classify fruits.",
                user_prompt="Classify a lemon.",
                response_model=FruitClassification,
            )

        assert isinstance(result, FruitClassification)
        assert result.name == "Lemon"
        assert result.color == "yellow"
        assert result.is_citrus is True


class TestRetriesOn429ThenSucceeds:
    """call_structured retries on 429 and eventually succeeds."""

    async def test_retries_on_429_then_succeeds(self) -> None:
        client = AIClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
            max_retries=3,
        )

        rate_err = _make_api_status_error(429, "rate limited")
        mock_msg = _make_message(
            {"name": "Orange", "color": "orange", "is_citrus": True}
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = [rate_err, mock_msg]

            result = await client.call_structured(
                system="Classify.",
                user_prompt="Classify an orange.",
                response_model=FruitClassification,
            )

        assert result.name == "Orange"
        assert mock_create.call_count == 2


class TestRetriesOn500ThenSucceeds:
    """call_structured retries on 5xx server errors and succeeds."""

    async def test_retries_on_500_then_succeeds(self) -> None:
        client = AIClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
            max_retries=3,
        )

        server_err = _make_api_status_error(500, "internal server error")
        mock_msg = _make_message(
            {"name": "Banana", "color": "yellow", "is_citrus": False}
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = [server_err, mock_msg]

            result = await client.call_structured(
                system="Classify.",
                user_prompt="Classify a banana.",
                response_model=FruitClassification,
            )

        assert result.name == "Banana"
        assert mock_create.call_count == 2


class TestRaisesOn401NoRetry:
    """call_structured raises immediately on 401 without retrying."""

    async def test_raises_on_401_no_retry(self) -> None:
        client = AIClient(
            api_key="sk-bad",
            model="claude-sonnet-4-20250514",
            max_retries=3,
        )

        auth_err = _make_api_status_error(401, "invalid api key")

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = auth_err

            with pytest.raises(AIClientError, match="invalid api key"):
                await client.call_structured(
                    system="Classify.",
                    user_prompt="Classify a grape.",
                    response_model=FruitClassification,
                )

        assert mock_create.call_count == 1


class TestRaisesAfterMaxRetriesExhausted:
    """call_structured raises after exhausting all retries."""

    async def test_raises_after_max_retries_exhausted(self) -> None:
        client = AIClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
            max_retries=3,
        )

        rate_err = _make_api_status_error(429, "rate limited")

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = rate_err

            with pytest.raises(RateLimitError):
                await client.call_structured(
                    system="Classify.",
                    user_prompt="Classify a grape.",
                    response_model=FruitClassification,
                )

        # 1 initial + 3 retries = 4 total attempts
        assert mock_create.call_count == 4


class TestLogsTokenUsageAndCost:
    """call_structured logs model, tokens, cost, and elapsed time at INFO."""

    async def test_logs_token_usage_and_cost(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = AIClient(api_key="sk-test", model="claude-sonnet-4-20250514")

        mock_msg = _make_message(
            {"name": "Apple", "color": "red", "is_citrus": False},
            input_tokens=200,
            output_tokens=80,
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_msg

            with caplog.at_level(logging.INFO, logger="mitty.ai.client"):
                await client.call_structured(
                    system="Classify.",
                    user_prompt="Classify an apple.",
                    response_model=FruitClassification,
                )

        # Verify the log message contains key fields
        assert len(caplog.records) >= 1
        log_text = caplog.text
        assert "claude-sonnet-4-20250514" in log_text
        assert "input_tokens=200" in log_text
        assert "output_tokens=80" in log_text
        assert "cost=" in log_text
        assert "elapsed=" in log_text


class TestClientNotCreatedWithoutApiKey:
    """AIClient raises ValueError when created without an API key."""

    def test_client_not_created_without_api_key(self) -> None:
        with pytest.raises(AIClientError, match="API key"):
            AIClient(api_key="", model="claude-sonnet-4-20250514")

    def test_client_not_created_with_none_api_key(self) -> None:
        with pytest.raises(AIClientError, match="API key"):
            AIClient(api_key=None, model="claude-sonnet-4-20250514")  # type: ignore[arg-type]
