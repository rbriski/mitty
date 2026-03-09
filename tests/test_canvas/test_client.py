"""Tests for mitty.canvas.client — CanvasClient async HTTP client."""

from __future__ import annotations

import httpx
import pytest
import respx

from mitty.canvas.client import CanvasAPIError, CanvasAuthError, CanvasClient
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
