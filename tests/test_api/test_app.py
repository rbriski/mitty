"""Tests for the FastAPI application scaffold."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set minimum env vars needed by load_settings()."""
    monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
    monkeypatch.setenv("CANVAS_TOKEN", "test-token")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("FASTAPI_DEBUG", raising=False)


@pytest.fixture()
def client(_mock_env: None) -> Generator[TestClient]:
    """Create a TestClient with mocked settings (lifespan enabled)."""
    from mitty.api.app import create_app

    app = create_app()
    with TestClient(app) as tc:
        yield tc


class TestHealthEndpoint:
    """GET /health returns status ok."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestErrorHandler:
    """Custom HTTPException handler returns ErrorDetail format."""

    def test_404_returns_error_detail_format(self, client: TestClient) -> None:
        response = client.get("/nonexistent-path")

        assert response.status_code == 404
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "404"
        assert body["error"]["message"] is not None
        assert "detail" in body["error"]


class TestCORSMiddleware:
    """CORS middleware is configured from ALLOWED_ORIGINS."""

    def test_cors_allows_configured_origin(
        self, monkeypatch: pytest.MonkeyPatch, _mock_env: None
    ) -> None:
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")

        from mitty.api.app import create_app

        app = create_app()
        with TestClient(app) as tc:
            response = tc.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert (
                response.headers.get("access-control-allow-origin")
                == "http://localhost:3000"
            )

    def test_cors_rejects_unknown_origin(
        self, monkeypatch: pytest.MonkeyPatch, _mock_env: None
    ) -> None:
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")

        from mitty.api.app import create_app

        app = create_app()
        with TestClient(app) as tc:
            response = tc.options(
                "/health",
                headers={
                    "Origin": "http://evil.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in response.headers


class TestSupabaseLifecycle:
    """Supabase client is created during lifespan when configured."""

    def test_supabase_clients_none_without_config(self, client: TestClient) -> None:
        assert client.app.state.supabase_admin is None
        assert client.app.state.supabase_client is None

    def test_supabase_clients_created_with_config(
        self, monkeypatch: pytest.MonkeyPatch, _mock_env: None
    ) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "srv-role-key")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")

        admin_client = AsyncMock()
        data_client = AsyncMock()
        with patch(
            "mitty.api._supabase.create_supabase_client",
            new_callable=AsyncMock,
            side_effect=[admin_client, data_client],
        ) as mock_create:
            from mitty.api.app import create_app

            app = create_app()
            with TestClient(app) as tc:
                assert mock_create.call_count == 2
                mock_create.assert_any_call("https://test.supabase.co", "srv-role-key")
                mock_create.assert_any_call("https://test.supabase.co", "anon-key")
                assert tc.app.state.supabase_admin is admin_client
                assert tc.app.state.supabase_client is data_client


class TestRequestLogging:
    """Request logging middleware logs at appropriate levels."""

    def test_successful_request_logs_info(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO", logger="mitty.api"):
            client.get("/health")

        assert any("GET /health" in record.message for record in caplog.records)
        assert any("200" in record.message for record in caplog.records)


class TestAppMetadata:
    """App factory sets correct metadata."""

    def test_app_title_and_version(self, client: TestClient) -> None:
        assert client.app.title == "Mitty API"
        assert client.app.version == "1.0.0"
