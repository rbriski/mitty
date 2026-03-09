"""Canvas LMS async HTTP client with auth, retry, and rate limiting.

Provides ``CanvasClient``, an async context manager that wraps
``httpx.AsyncClient`` with Bearer-token authentication, exponential
backoff on transient errors (429 / 5xx), and a configurable
rate-limit delay between requests.

Exceptions:
    CanvasAuthError: Raised on 401/403 (never retried).
    CanvasAPIError:  Raised on other 4xx or exhausted retries.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from mitty.config import Settings

logger = logging.getLogger("mitty")


class CanvasAuthError(Exception):
    """Raised when Canvas returns 401 Unauthorized or 403 Forbidden."""


class CanvasAPIError(Exception):
    """Raised on non-retryable 4xx errors or after retries are exhausted."""


class CanvasClient:
    """Async HTTP client for the Canvas LMS REST API.

    Usage::

        async with CanvasClient(settings) as client:
            resp = await client.get("/api/v1/courses", params={"per_page": "50"})
            courses = resp.json()

    Args:
        settings: Application settings (token, base URL, retry config, etc.).
        _sleep: Async sleep callable; injectable for testing (DEC-010).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        _sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._sleep = _sleep
        self._http: httpx.AsyncClient = None  # type: ignore[assignment]
        self._semaphore = asyncio.Semaphore(settings.max_concurrent)

    async def __aenter__(self) -> CanvasClient:
        self._http = httpx.AsyncClient(
            base_url=self._settings.canvas_base_url,
            headers={"Authorization": f"Bearer {self._settings.canvas_token}"},
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send an authenticated GET request with retry and rate limiting.

        Args:
            path: API path appended to the base URL (e.g. ``/api/v1/courses``).
            params: Optional query parameters.

        Returns:
            The successful ``httpx.Response`` (2xx).

        Raises:
            CanvasAuthError: On 401 or 403 (immediate, no retry).
            CanvasAPIError: On other 4xx or after retries are exhausted.
        """
        max_retries = self._settings.max_retries

        for attempt in range(1 + max_retries):
            # Rate-limit delay before each request
            await self._sleep(self._settings.request_delay)

            async with self._semaphore:
                response = await self._http.get(path, params=params)

            status = response.status_code

            # Success
            if 200 <= status < 300:
                return response

            # Auth errors -- never retry
            if status in (401, 403):
                msg = (
                    f"Canvas authentication failed: "
                    f"{status} {response.reason_phrase} for {path}"
                )
                logger.warning(msg)
                raise CanvasAuthError(msg)

            # Retryable: 429 or 5xx
            if status == 429 or status >= 500:
                if attempt < max_retries:
                    backoff = 2**attempt  # 1, 2, 4, 8, ...
                    logger.info(
                        "Retryable %d on %s (attempt %d/%d), backing off %.1fs",
                        status,
                        path,
                        attempt + 1,
                        max_retries,
                        backoff,
                    )
                    await self._sleep(backoff)
                    continue

                # Exhausted retries
                msg = (
                    f"Canvas API error after {max_retries} retries: {status} for {path}"
                )
                logger.warning(msg)
                raise CanvasAPIError(msg)

            # Other 4xx -- never retry
            msg = f"Canvas API error: {status} {response.reason_phrase} for {path}"
            logger.warning(msg)
            raise CanvasAPIError(msg)

        # Should be unreachable, but satisfy type checkers
        msg = f"Unexpected state after retry loop for {path}"
        raise CanvasAPIError(msg)  # pragma: no cover
