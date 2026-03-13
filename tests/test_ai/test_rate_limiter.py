"""Tests for mitty.ai.rate_limiter — per-user sliding window rate limiter."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mitty.ai.errors import RateLimitError
from mitty.ai.rate_limiter import RateLimiter


class TestRateLimiterRequestsPerMinute:
    """RateLimiter enforces requests-per-minute limits."""

    async def test_allows_requests_under_limit(self) -> None:
        limiter = RateLimiter(requests_per_minute=5, tokens_per_minute=100_000)

        for _ in range(4):
            await limiter.check_rate_limit("user-1")
            await limiter.record_usage("user-1", 100)

        # 5th check should still pass (only 4 recorded)
        await limiter.check_rate_limit("user-1")

    async def test_blocks_requests_at_limit(self) -> None:
        limiter = RateLimiter(requests_per_minute=3, tokens_per_minute=100_000)

        for _ in range(3):
            await limiter.record_usage("user-1", 100)

        with pytest.raises(RateLimitError, match="requests per minute"):
            await limiter.check_rate_limit("user-1")

    async def test_different_users_independent(self) -> None:
        limiter = RateLimiter(requests_per_minute=2, tokens_per_minute=100_000)

        for _ in range(2):
            await limiter.record_usage("user-a", 100)

        # user-a should be blocked
        with pytest.raises(RateLimitError):
            await limiter.check_rate_limit("user-a")

        # user-b should still be fine
        await limiter.check_rate_limit("user-b")


class TestRateLimiterTokensPerMinute:
    """RateLimiter enforces tokens-per-minute limits."""

    async def test_blocks_when_token_limit_exceeded(self) -> None:
        limiter = RateLimiter(requests_per_minute=100, tokens_per_minute=1000)

        await limiter.record_usage("user-1", 600)
        await limiter.record_usage("user-1", 500)

        with pytest.raises(RateLimitError, match="tokens per minute"):
            await limiter.check_rate_limit("user-1")

    async def test_allows_under_token_limit(self) -> None:
        limiter = RateLimiter(requests_per_minute=100, tokens_per_minute=1000)

        await limiter.record_usage("user-1", 400)
        await limiter.record_usage("user-1", 400)

        # 800 < 1000, should be fine
        await limiter.check_rate_limit("user-1")


class TestRateLimiterSlidingWindow:
    """Old entries are pruned when the window slides."""

    async def test_old_entries_pruned(self) -> None:
        limiter = RateLimiter(requests_per_minute=2, tokens_per_minute=100_000)

        # Record 2 requests
        await limiter.record_usage("user-1", 100)
        await limiter.record_usage("user-1", 100)

        # Should be blocked
        with pytest.raises(RateLimitError):
            await limiter.check_rate_limit("user-1")

        # Move time forward past the window by patching time.monotonic
        import time

        future = time.monotonic() + 61.0
        with patch("mitty.ai.rate_limiter.time.monotonic", return_value=future):
            # Now should be allowed again
            await limiter.check_rate_limit("user-1")
