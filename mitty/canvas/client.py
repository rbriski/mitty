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
import hashlib
import json
import logging
import re
import stat
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from types import TracebackType

    from mitty.config import Settings

logger = logging.getLogger("mitty")

_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"', re.IGNORECASE)


def _parse_link_header(header: str) -> str | None:
    """Extract the ``rel="next"`` URL from a Canvas ``Link`` header.

    Canvas format example::

        <https://canvas.test/api/v1/courses?page=2&per_page=100>; rel="next",
        <https://canvas.test/api/v1/courses?page=5&per_page=100>; rel="last"

    The ``rel`` comparison is case-insensitive.

    Returns:
        The URL for the next page, or *None* if there is no ``next`` link.
    """
    for match in _LINK_RE.finditer(header):
        url, rel = match.group(1), match.group(2)
        if rel.lower() == "next":
            return url
    return None


def _cache_key(url: str, params: dict[str, str] | None) -> str:
    """Return a SHA-256 hex digest of *url* combined with sorted *params*.

    The key is deterministic regardless of parameter insertion order.
    """
    parts = url
    if params:
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        parts = f"{url}?{sorted_params}"
    return hashlib.sha256(parts.encode()).hexdigest()


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

    # ------------------------------------------------------------------
    # Caching helpers
    # ------------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        """Return the filesystem path for a cache entry."""
        return self._settings.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> list[dict[str, Any]] | None:
        """Read cached JSON if the file exists and has not expired.

        Returns:
            The cached list, or *None* on miss / expiry.
        """
        path = self._cache_path(key)
        if not path.exists():
            return None

        age = time.time() - path.stat().st_mtime
        if age >= self._settings.cache_ttl_seconds:
            logger.debug("Cache expired for %s (%.0fs old)", key[:12], age)
            return None

        logger.debug("Cache hit for %s", key[:12])
        data: list[dict[str, Any]] = json.loads(path.read_text())
        return data

    def _write_cache(self, key: str, data: list[dict[str, Any]]) -> None:
        """Write *data* as JSON to the cache directory with 0600 permissions.

        Creates ``cache_dir`` (and parents) if it does not already exist.
        """
        cache_dir = self._settings.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

        path = self._cache_path(key)
        path.write_text(json.dumps(data))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

        logger.debug("Cache written for %s", key[:12])

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _url_to_path(self, url: str) -> str:
        """Strip the base URL from an absolute URL to get a relative path.

        Canvas ``Link`` headers contain absolute URLs.  Since our
        ``httpx.AsyncClient`` is configured with ``base_url``, we need to
        pass a relative path to ``self.get()``.
        """
        base = self._settings.canvas_base_url.rstrip("/")
        if url.startswith(base):
            return url[len(base) :]
        return url

    async def get_paginated(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated Canvas endpoint.

        Follows ``Link rel="next"`` headers until no more pages remain,
        concatenating the JSON arrays from each response.

        If caching is enabled and a valid cache entry exists, the cached
        data is returned without making any HTTP requests.

        Args:
            path: API path (e.g. ``/api/v1/courses``).
            params: Optional query parameters for the first request.

        Returns:
            A single list containing the items from all pages.
        """
        full_url = f"{self._settings.canvas_base_url}{path}"
        key = _cache_key(full_url, params)

        # Check cache
        if self._settings.cache_enabled:
            cached = self._read_cache(key)
            if cached is not None:
                return cached

        # First page — use self.get() which handles retry / rate-limit
        response = await self.get(path, params=params)
        items: list[dict[str, Any]] = response.json()

        # Follow pagination links
        link_header = response.headers.get("link")
        while link_header:
            next_url = _parse_link_header(link_header)
            if next_url is None:
                break

            # Convert absolute Link URL to relative path for self.get()
            response = await self.get(self._url_to_path(next_url))
            items.extend(response.json())
            link_header = response.headers.get("link")

        # Write cache
        if self._settings.cache_enabled:
            self._write_cache(key, items)

        return items
