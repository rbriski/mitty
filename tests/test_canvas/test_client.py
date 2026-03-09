"""Tests for mitty.canvas.client — CanvasClient async HTTP client."""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx

from mitty.canvas.client import (
    CanvasAPIError,
    CanvasAuthError,
    CanvasClient,
    _cache_key,
    _parse_link_header,
)
from mitty.config import Settings


async def _nosleep(seconds: float) -> None:
    """No-op sleep replacement for fast, deterministic tests."""


def _make_settings(**overrides: object) -> Settings:
    """Build a Settings instance with sensible test defaults."""
    defaults: dict[str, object] = {
        "canvas_token": "test-token-abc",
        "canvas_base_url": "https://canvas.test",
        "request_delay": 0.0,
        "max_retries": 3,
        "max_concurrent": 3,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestAuthHeader:
    """GET requests include a Bearer token in the Authorization header."""

    @respx.mock
    async def test_get_sends_bearer_token(self) -> None:
        settings = _make_settings()
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            await client.get("/api/v1/courses")

        assert route.called
        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer test-token-abc"

    @respx.mock
    async def test_get_passes_query_params(self) -> None:
        settings = _make_settings()
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            await client.get("/api/v1/courses", params={"per_page": "10"})

        request = route.calls[0].request
        assert "per_page=10" in str(request.url)


class TestAuthErrors:
    """401 and 403 responses raise CanvasAuthError without retrying."""

    @respx.mock
    async def test_401_raises_canvas_auth_error(self) -> None:
        settings = _make_settings()
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            with pytest.raises(CanvasAuthError, match="401"):
                await client.get("/api/v1/courses")

        # Must NOT retry on auth errors
        assert route.call_count == 1

    @respx.mock
    async def test_403_raises_canvas_auth_error(self) -> None:
        settings = _make_settings()
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            with pytest.raises(CanvasAuthError, match="403"):
                await client.get("/api/v1/courses")

        assert route.call_count == 1


class TestAPIErrors:
    """Other 4xx responses raise CanvasAPIError without retrying."""

    @respx.mock
    async def test_404_raises_canvas_api_error(self) -> None:
        settings = _make_settings()
        route = respx.get("https://canvas.test/api/v1/courses/999").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            with pytest.raises(CanvasAPIError, match="404"):
                await client.get("/api/v1/courses/999")

        assert route.call_count == 1

    @respx.mock
    async def test_422_raises_canvas_api_error(self) -> None:
        settings = _make_settings()
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(422, json={"message": "Unprocessable"})
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            with pytest.raises(CanvasAPIError, match="422"):
                await client.get("/api/v1/courses")

        assert route.call_count == 1


class TestRetryOn429:
    """429 Too Many Requests triggers retry with exponential backoff."""

    @respx.mock
    async def test_429_retries_then_succeeds(self) -> None:
        settings = _make_settings(max_retries=3)
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(429),
                httpx.Response(200, json={"ok": True}),
            ]
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            resp = await client.get("/api/v1/courses")

        assert resp.status_code == 200
        assert route.call_count == 3

    @respx.mock
    async def test_429_exhausts_retries_raises_api_error(self) -> None:
        settings = _make_settings(max_retries=2)
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(429),
                httpx.Response(429),
            ]
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            with pytest.raises(CanvasAPIError, match="429"):
                await client.get("/api/v1/courses")

        # 1 initial + 2 retries = 3 total
        assert route.call_count == 3


class TestRetryOn5xx:
    """5xx server errors trigger retry with exponential backoff."""

    @respx.mock
    async def test_500_retries_then_succeeds(self) -> None:
        settings = _make_settings(max_retries=3)
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(200, json={"ok": True}),
            ]
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            resp = await client.get("/api/v1/courses")

        assert resp.status_code == 200
        assert route.call_count == 2

    @respx.mock
    async def test_503_exhausts_retries_raises_api_error(self) -> None:
        settings = _make_settings(max_retries=2)
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(503),
            ]
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            with pytest.raises(CanvasAPIError, match="503"):
                await client.get("/api/v1/courses")

        assert route.call_count == 3


class TestBackoffSleepDurations:
    """Verify exponential backoff sleep durations on retries."""

    @respx.mock
    async def test_backoff_sleep_durations(self) -> None:
        sleep_calls: list[float] = []

        async def _tracking_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        settings = _make_settings(max_retries=3, request_delay=0.0)
        respx.get("https://canvas.test/api/v1/courses").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json={"ok": True}),
            ]
        )

        async with CanvasClient(settings, _sleep=_tracking_sleep) as client:
            await client.get("/api/v1/courses")

        # request_delay=0.0, so rate-limit sleeps are 0.0
        # Backoff sleeps: 1s after 1st failure, 2s after 2nd
        backoff_sleeps = [s for s in sleep_calls if s > 0]
        assert backoff_sleeps == [1.0, 2.0]


class TestRateLimitDelay:
    """Rate-limit delay is applied before each request."""

    @respx.mock
    async def test_rate_limit_sleep_called(self) -> None:
        sleep_calls: list[float] = []

        async def _tracking_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        settings = _make_settings(request_delay=0.5)
        respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with CanvasClient(settings, _sleep=_tracking_sleep) as client:
            await client.get("/api/v1/courses")

        # The rate-limit delay of 0.5 should appear in sleep calls
        assert 0.5 in sleep_calls


class TestContextManager:
    """CanvasClient works as an async context manager."""

    async def test_client_opens_and_closes(self) -> None:
        settings = _make_settings()

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            assert client._http is not None
            assert not client._http.is_closed

        assert client._http.is_closed


# ------------------------------------------------------------------ #
#  New test classes — pagination & caching (US-005)
# ------------------------------------------------------------------ #


class TestParseLinkHeader:
    """_parse_link_header extracts the 'next' URL from Canvas Link headers."""

    def test_extracts_next_url(self) -> None:
        header = (
            '<https://canvas.test/api/v1/courses?page=2&per_page=100>; rel="next", '
            '<https://canvas.test/api/v1/courses?page=5&per_page=100>; rel="last"'
        )
        assert (
            _parse_link_header(header)
            == "https://canvas.test/api/v1/courses?page=2&per_page=100"
        )

    def test_returns_none_when_no_next(self) -> None:
        header = (
            '<https://canvas.test/api/v1/courses?page=1&per_page=100>; rel="current", '
            '<https://canvas.test/api/v1/courses?page=5&per_page=100>; rel="last"'
        )
        assert _parse_link_header(header) is None

    def test_case_insensitive_rel(self) -> None:
        header = '<https://canvas.test/api/v1/courses?page=3&per_page=100>; rel="Next"'
        assert (
            _parse_link_header(header)
            == "https://canvas.test/api/v1/courses?page=3&per_page=100"
        )


class TestGetPaginated:
    """get_paginated follows Link headers and concatenates pages."""

    @respx.mock
    async def test_multi_page_pagination(self) -> None:
        """Two pages are concatenated into a single list."""
        settings = _make_settings(cache_enabled=False)

        page1_data = [{"id": 1}, {"id": 2}]
        page2_data = [{"id": 3}]

        page2_url = "https://canvas.test/api/v1/courses?page=2&per_page=100"
        link = f'<{page2_url}>; rel="next", <{page2_url}>; rel="last"'

        # Both requests go to /api/v1/courses (page 2 has query params).
        # Use side_effect to return different responses for each call.
        respx.get(url__startswith="https://canvas.test/api/v1/courses").mock(
            side_effect=[
                httpx.Response(200, json=page1_data, headers={"Link": link}),
                httpx.Response(200, json=page2_data),
            ]
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]

    @respx.mock
    async def test_single_page_no_link_header(self) -> None:
        """Single page response (no Link header) returns items directly."""
        settings = _make_settings(cache_enabled=False)
        data = [{"id": 1}]

        respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=data)
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == [{"id": 1}]

    @respx.mock
    async def test_empty_response(self) -> None:
        """Empty JSON array returns empty list."""
        settings = _make_settings(cache_enabled=False)

        respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == []


class TestCache:
    """File-based JSON caching for get_paginated."""

    @respx.mock
    async def test_cache_hit_returns_cached_data(self, tmp_path: object) -> None:
        """When a valid cache file exists, no HTTP call is made."""
        from pathlib import Path

        cache_dir = Path(str(tmp_path))
        settings = _make_settings(
            cache_enabled=True,
            cache_dir=cache_dir,
            cache_ttl_seconds=3600,
        )

        # Pre-populate cache
        full_url = f"{settings.canvas_base_url}/api/v1/courses"
        key = _cache_key(full_url, None)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps([{"id": 99, "cached": True}]))

        # No HTTP route mocked — if the client tries to fetch, respx will error
        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == [{"id": 99, "cached": True}]

    @respx.mock
    async def test_cache_miss_makes_http_call_and_writes(
        self, tmp_path: object
    ) -> None:
        """On cache miss, data is fetched and written to the cache file."""
        from pathlib import Path

        cache_dir = Path(str(tmp_path))
        settings = _make_settings(
            cache_enabled=True,
            cache_dir=cache_dir,
            cache_ttl_seconds=3600,
        )

        data = [{"id": 1}]
        respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=data)
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == [{"id": 1}]

        # Verify cache file was written
        full_url = f"{settings.canvas_base_url}/api/v1/courses"
        key = _cache_key(full_url, None)
        cache_file = cache_dir / f"{key}.json"
        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == [{"id": 1}]

        # Verify 0600 permissions
        import stat

        mode = cache_file.stat().st_mode
        assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR

    @respx.mock
    async def test_cache_disabled_always_fetches(self, tmp_path: object) -> None:
        """When cache_enabled=False, HTTP is always called even if file exists."""
        from pathlib import Path

        cache_dir = Path(str(tmp_path))
        settings = _make_settings(
            cache_enabled=False,
            cache_dir=cache_dir,
            cache_ttl_seconds=3600,
        )

        # Pre-populate cache file (should be ignored)
        full_url = f"{settings.canvas_base_url}/api/v1/courses"
        key = _cache_key(full_url, None)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps([{"id": 99, "stale": True}]))

        fresh_data = [{"id": 1, "fresh": True}]
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=fresh_data)
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == [{"id": 1, "fresh": True}]
        assert route.called

    @respx.mock
    async def test_cache_expiry_refetches(self, tmp_path: object) -> None:
        """Expired cache entry is ignored; fresh data is fetched."""
        from pathlib import Path

        cache_dir = Path(str(tmp_path))
        settings = _make_settings(
            cache_enabled=True,
            cache_dir=cache_dir,
            cache_ttl_seconds=60,
        )

        # Pre-populate cache with an old mtime
        full_url = f"{settings.canvas_base_url}/api/v1/courses"
        key = _cache_key(full_url, None)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps([{"id": 99, "expired": True}]))

        import os

        old_time = time.time() - 120  # 120 seconds ago (> 60s TTL)
        os.utime(cache_file, (old_time, old_time))

        fresh_data = [{"id": 1, "fresh": True}]
        route = respx.get("https://canvas.test/api/v1/courses").mock(
            return_value=httpx.Response(200, json=fresh_data)
        )

        async with CanvasClient(settings, _sleep=_nosleep) as client:
            result = await client.get_paginated("/api/v1/courses")

        assert result == [{"id": 1, "fresh": True}]
        assert route.called
