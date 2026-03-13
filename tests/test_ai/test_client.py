"""Tests for mitty.ai.client — AIClient structured output wrapper.

Covers: happy path, retry on 429/5xx, permanent failure on 4xx,
max-retry exhaustion, token/cost logging, missing-key guard,
audit logging, cost calculation, budget checks, and prompt integration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from anthropic import APIStatusError

from mitty.ai.client import AIClient, _calculate_cost
from mitty.ai.errors import AIClientError, BudgetExceededError, RateLimitError

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


def _mock_supabase() -> AsyncMock:
    """Create a mock Supabase AsyncClient with chained table().insert().execute()."""
    mock_client = AsyncMock()
    mock_table = AsyncMock()
    mock_insert = AsyncMock()
    mock_execute = AsyncMock(return_value=MagicMock(data=[]))
    mock_insert.execute = mock_execute
    mock_table.insert = MagicMock(return_value=mock_insert)
    mock_client.table = MagicMock(return_value=mock_table)
    return mock_client


# ---------------------------------------------------------------------------
# Original Tests (backward compatibility)
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


# ---------------------------------------------------------------------------
# New Tests: Cost calculation
# ---------------------------------------------------------------------------


class TestCostCalculation:
    """_calculate_cost returns correct values for different models."""

    def test_sonnet_cost(self) -> None:
        cost = _calculate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
        # input: 3.0, output: 15.0
        assert cost == pytest.approx(18.0)

    def test_haiku_cost(self) -> None:
        cost = _calculate_cost("claude-haiku-3-5-20241022", 1_000_000, 1_000_000)
        # input: 0.80, output: 4.0
        assert cost == pytest.approx(4.8)

    def test_unknown_model_uses_default(self) -> None:
        cost = _calculate_cost("unknown-model", 1000, 500)
        # default: input=3.0/M, output=15.0/M
        expected = 1000 * 3.0 / 1_000_000 + 500 * 15.0 / 1_000_000
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self) -> None:
        cost = _calculate_cost("claude-sonnet-4-20250514", 0, 0)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# New Tests: Audit logging
# ---------------------------------------------------------------------------


class TestAuditLogging:
    """Audit rows are written to ai_audit_log via Supabase."""

    async def test_audit_row_written_on_success(self) -> None:
        mock_sb = _mock_supabase()
        client = AIClient(api_key="sk-test", budget_per_session=0, budget_per_day=0)

        mock_msg = _make_message(
            {"name": "Lemon", "color": "yellow", "is_citrus": True},
            input_tokens=100,
            output_tokens=50,
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_msg

            await client.call_structured(
                system="Classify.",
                user_prompt="Classify a lemon.",
                response_model=FruitClassification,
                user_id="user-123",
                call_type="test_call",
                supabase_client=mock_sb,
            )

        # Let fire-and-forget task run
        await asyncio.sleep(0.05)

        mock_sb.table.assert_called_with("ai_audit_log")
        insert_call = mock_sb.table.return_value.insert
        assert insert_call.call_count == 1
        row = insert_call.call_args[0][0]
        assert row["user_id"] == "user-123"
        assert row["call_type"] == "test_call"
        assert row["status"] == "success"
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["cost_usd"] > 0
        assert row["error_msg"] is None

    async def test_audit_row_written_on_error(self) -> None:
        mock_sb = _mock_supabase()
        client = AIClient(api_key="sk-test", budget_per_session=0, budget_per_day=0)

        auth_err = _make_api_status_error(401, "invalid api key")

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = auth_err

            with pytest.raises(AIClientError):
                await client.call_structured(
                    system="Classify.",
                    user_prompt="Classify.",
                    response_model=FruitClassification,
                    user_id="user-456",
                    call_type="test_error",
                    supabase_client=mock_sb,
                )

        await asyncio.sleep(0.05)

        insert_call = mock_sb.table.return_value.insert
        assert insert_call.call_count == 1
        row = insert_call.call_args[0][0]
        assert row["status"] == "error"
        assert row["error_msg"] is not None
        assert "invalid api key" in row["error_msg"]

    async def test_audit_write_failure_does_not_block_response(self) -> None:
        mock_sb = _mock_supabase()
        # Make the insert raise an exception
        mock_sb.table.return_value.insert.return_value.execute = AsyncMock(
            side_effect=RuntimeError("DB down")
        )

        client = AIClient(api_key="sk-test", budget_per_session=0, budget_per_day=0)

        mock_msg = _make_message(
            {"name": "Lemon", "color": "yellow", "is_citrus": True}
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_msg

            # Should still return the result even though audit write fails
            result = await client.call_structured(
                system="Classify.",
                user_prompt="Classify.",
                response_model=FruitClassification,
                user_id="user-789",
                call_type="test_fail_audit",
                supabase_client=mock_sb,
            )

        assert result.name == "Lemon"

        # Let the fire-and-forget task run (and fail silently)
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# New Tests: Prompt version in audit log
# ---------------------------------------------------------------------------


class TestPromptVersionInAuditLog:
    """Prompt version (content_hash) is recorded when role is provided."""

    async def test_prompt_version_recorded(self) -> None:
        mock_sb = _mock_supabase()
        client = AIClient(api_key="sk-test", budget_per_session=0, budget_per_day=0)

        mock_msg = _make_message(
            {"name": "Lemon", "color": "yellow", "is_citrus": True}
        )

        with patch.object(
            client._client.messages, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_msg

            await client.call_structured(
                system="Classify.",
                user_prompt="Classify.",
                response_model=FruitClassification,
                user_id="user-abc",
                call_type="test_prompt",
                supabase_client=mock_sb,
                role="evaluator",
            )

        await asyncio.sleep(0.05)

        insert_call = mock_sb.table.return_value.insert
        row = insert_call.call_args[0][0]
        # prompt_version should be the content_hash from the evaluator prompt
        assert row["prompt_version"] != ""
        assert len(row["prompt_version"]) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# New Tests: Budget exceeded
# ---------------------------------------------------------------------------


class TestBudgetExceeded:
    """BudgetExceededError is raised when budget is exceeded."""

    async def test_session_budget_exceeded(self) -> None:
        client = AIClient(
            api_key="sk-test",
            budget_per_session=0.001,
            budget_per_day=0,
        )
        # Simulate prior spending
        client._session_cost = 0.002

        with pytest.raises(BudgetExceededError, match="Session"):
            await client.call_structured(
                system="Classify.",
                user_prompt="Classify.",
                response_model=FruitClassification,
            )

    async def test_daily_budget_exceeded(self) -> None:
        mock_sb = _mock_supabase()
        # Mock daily cost query to return high total
        mock_select = AsyncMock()
        mock_eq1 = AsyncMock()
        mock_gte = AsyncMock()
        mock_eq2 = AsyncMock()
        mock_execute = AsyncMock(return_value=MagicMock(data=[{"cost_usd": "10.0"}]))
        mock_sb.table = MagicMock(return_value=mock_select)
        mock_select.select = MagicMock(return_value=mock_eq1)
        mock_eq1.eq = MagicMock(return_value=mock_gte)
        mock_gte.gte = MagicMock(return_value=mock_eq2)
        mock_eq2.eq = MagicMock(return_value=mock_execute)
        mock_execute.execute = AsyncMock(
            return_value=MagicMock(data=[{"cost_usd": "10.0"}])
        )

        client = AIClient(
            api_key="sk-test",
            budget_per_session=0,
            budget_per_day=5.0,
        )

        with pytest.raises(BudgetExceededError, match="Daily"):
            await client.call_structured(
                system="Classify.",
                user_prompt="Classify.",
                response_model=FruitClassification,
                user_id="user-budget",
                supabase_client=mock_sb,
            )
