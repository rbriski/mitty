"""Per-user rate limiting for AI calls using a sliding window algorithm.

Provides ``RateLimiter`` — an in-memory tracker that enforces configurable
requests-per-minute and tokens-per-minute limits on a per-user basis.

The primary entry point is ``acquire()``, which atomically checks limits
and reserves a request slot under a per-user lock to prevent TOCTOU races.
After the AI call completes, ``adjust_tokens()`` corrects the estimated
token count with the actual value.
"""

from __future__ import annotations

import asyncio
import time

from mitty.ai.errors import RateLimitError

# Window size in seconds
_WINDOW_SECONDS = 60.0


class RateLimiter:
    """In-memory sliding-window rate limiter for AI API calls.

    Tracks per-user request counts and token usage over a rolling
    60-second window.  Raises ``RateLimitError`` when a user exceeds
    either the requests-per-minute or tokens-per-minute limit.

    Uses per-user asyncio locks and an atomic ``acquire()`` method
    to prevent TOCTOU races between checking and recording.

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
        # user_id -> list of timestamps for request tracking
        self._request_log: dict[str, list[float]] = {}
        # user_id -> list of (timestamp, token_count) for token tracking
        self._token_log: dict[str, list[tuple[float, int]]] = {}
        # Per-user locks to serialize check + record
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        """Return (and lazily create) the per-user lock."""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

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

    async def acquire(self, user_id: str, estimated_tokens: int = 0) -> None:
        """Atomically check limits and reserve a request slot.

        This is the primary entry point.  It holds the per-user lock while
        checking **and** reserving, eliminating the TOCTOU gap that existed
        when ``check_rate_limit`` and ``record_usage`` were separate calls.

        Args:
            user_id: The user making the request.
            estimated_tokens: Estimated tokens for the upcoming call
                (use 0 if unknown; adjust later via ``adjust_tokens``).

        Raises:
            RateLimitError: If either RPM or TPM limit is exceeded.
        """
        if estimated_tokens < 0:
            msg = "estimated_tokens must be non-negative"
            raise ValueError(msg)

        async with self._get_lock(user_id):
            now = time.monotonic()
            self._prune_old_entries(user_id, now)

            # Check requests per minute
            request_count = len(self._request_log.get(user_id, []))
            if request_count >= self._rpm:
                raise RateLimitError(
                    f"Rate limit exceeded: {request_count}/{self._rpm}"
                    " requests per minute"
                )

            # Check tokens per minute
            token_entries = self._token_log.get(user_id, [])
            token_total = sum(count for _, count in token_entries)
            if token_total >= self._tpm:
                raise RateLimitError(
                    f"Rate limit exceeded: {token_total}/{self._tpm} tokens per minute"
                )

            # Reserve the slot immediately (under the same lock)
            self._request_log.setdefault(user_id, []).append(now)
            if estimated_tokens:
                self._token_log.setdefault(user_id, []).append((now, estimated_tokens))

    async def adjust_tokens(self, user_id: str, actual_tokens: int) -> None:
        """Record actual token usage after a request completes.

        Appends the real token count.  If ``acquire()`` was called with
        ``estimated_tokens=0`` (the common case), this is the only token
        entry for the request.

        Args:
            user_id: The user who made the request.
            actual_tokens: Total tokens consumed (input + output).
        """
        if actual_tokens < 0:
            msg = "actual_tokens must be non-negative"
            raise ValueError(msg)

        async with self._get_lock(user_id):
            now = time.monotonic()
            self._prune_old_entries(user_id, now)
            self._token_log.setdefault(user_id, []).append((now, actual_tokens))

    # ------------------------------------------------------------------
    # Legacy API — kept for backwards compatibility with existing callers.
    # Prefer ``acquire()`` + ``adjust_tokens()`` for new code.
    # ------------------------------------------------------------------

    async def check_rate_limit(self, user_id: str) -> None:
        """Check whether *user_id* is within rate limits.

        Does **not** reserve a slot — use ``acquire()`` for atomic
        check-and-reserve.  Kept for backward compat where callers
        pair ``check_rate_limit()`` + ``record_usage()``.

        .. deprecated:: Use ``acquire()`` for atomic check-and-reserve.
        """
        async with self._get_lock(user_id):
            now = time.monotonic()
            self._prune_old_entries(user_id, now)

            request_count = len(self._request_log.get(user_id, []))
            if request_count >= self._rpm:
                raise RateLimitError(
                    f"Rate limit exceeded: {request_count}/{self._rpm}"
                    " requests per minute"
                )

            token_entries = self._token_log.get(user_id, [])
            token_total = sum(count for _, count in token_entries)
            if token_total >= self._tpm:
                raise RateLimitError(
                    f"Rate limit exceeded: {token_total}/{self._tpm} tokens per minute"
                )

    async def record_usage(self, user_id: str, tokens: int) -> None:
        """Record a completed request and its token usage.

        Unlike ``adjust_tokens()``, this also records a request slot
        for backward compatibility (the old API recorded both).

        .. deprecated:: Use ``acquire()`` + ``adjust_tokens()``.
        """
        if tokens < 0:
            msg = "tokens must be non-negative"
            raise ValueError(msg)

        async with self._get_lock(user_id):
            now = time.monotonic()
            self._prune_old_entries(user_id, now)
            self._request_log.setdefault(user_id, []).append(now)
            self._token_log.setdefault(user_id, []).append((now, tokens))
