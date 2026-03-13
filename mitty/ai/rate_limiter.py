"""Per-user rate limiting for AI calls using a sliding window algorithm.

Provides ``RateLimiter`` — an in-memory tracker that enforces configurable
requests-per-minute and tokens-per-minute limits on a per-user basis.
"""

from __future__ import annotations

import time

from mitty.ai.errors import RateLimitError

# Window size in seconds
_WINDOW_SECONDS = 60.0


class RateLimiter:
    """In-memory sliding-window rate limiter for AI API calls.

    Tracks per-user request counts and token usage over a rolling
    60-second window.  Raises ``RateLimitError`` when a user exceeds
    either the requests-per-minute or tokens-per-minute limit.

    Args:
        requests_per_minute: Maximum requests allowed per user per minute.
        tokens_per_minute: Maximum tokens allowed per user per minute.
    """

    def __init__(
        self,
        *,
        requests_per_minute: int = 30,
        tokens_per_minute: int = 100_000,
    ) -> None:
        self._rpm = requests_per_minute
        self._tpm = tokens_per_minute
        # user_id -> list of (timestamp,) for request tracking
        self._request_log: dict[str, list[float]] = {}
        # user_id -> list of (timestamp, token_count) for token tracking
        self._token_log: dict[str, list[tuple[float, int]]] = {}

    def _prune_old_entries(self, user_id: str, now: float) -> None:
        """Remove entries older than the sliding window."""
        cutoff = now - _WINDOW_SECONDS

        if user_id in self._request_log:
            self._request_log[user_id] = [
                ts for ts in self._request_log[user_id] if ts > cutoff
            ]

        if user_id in self._token_log:
            self._token_log[user_id] = [
                (ts, count) for ts, count in self._token_log[user_id] if ts > cutoff
            ]

    async def check_rate_limit(self, user_id: str) -> None:
        """Check whether *user_id* is within rate limits.

        Raises:
            RateLimitError: If either RPM or TPM limit is exceeded.
        """
        now = time.monotonic()
        self._prune_old_entries(user_id, now)

        # Check requests per minute
        request_count = len(self._request_log.get(user_id, []))
        if request_count >= self._rpm:
            raise RateLimitError(
                f"Rate limit exceeded: {request_count}/{self._rpm} requests per minute"
            )

        # Check tokens per minute
        token_entries = self._token_log.get(user_id, [])
        token_total = sum(count for _, count in token_entries)
        if token_total >= self._tpm:
            raise RateLimitError(
                f"Rate limit exceeded: {token_total}/{self._tpm} tokens per minute"
            )

    async def record_usage(self, user_id: str, tokens: int) -> None:
        """Record a completed request and its token usage.

        Args:
            user_id: The user making the request.
            tokens: Total tokens consumed (input + output).
        """
        now = time.monotonic()
        self._prune_old_entries(user_id, now)

        if user_id not in self._request_log:
            self._request_log[user_id] = []
        self._request_log[user_id].append(now)

        if user_id not in self._token_log:
            self._token_log[user_id] = []
        self._token_log[user_id].append((now, tokens))
