"""Tests for the resources CRUD router."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Generator

SAMPLE_RESOURCE = {
    "id": 1,
    "course_id": 10,
    "title": "Chapter 5: Polynomials",
    "resource_type": "textbook_chapter",
    "source_url": "https://example.com/ch5.pdf",
    "canvas_module_id": 77,
    "sort_order": 5,
    "created_at": "2026-03-01T00:00:00",
    "updated_at": "2026-03-01T00:00:00",
}


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
    monkeypatch.setenv("CANVAS_TOKEN", "test-token")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("FASTAPI_DEBUG", raising=False)


@pytest.fixture()
def client(
    _mock_env: None,
    mock_supabase_client: AsyncMock,
) -> Generator[TestClient]:
    from mitty.api.app import create_app

    app = create_app()
    mock_supabase_client.table = MagicMock()
    with TestClient(app) as tc:
        app.state.supabase_client = mock_supabase_client
        yield tc


class TestCreateResource:
    def test_create_returns_201(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[SAMPLE_RESOURCE]))

        response = client.post(
            "/resources/",
            json={
                "course_id": 10,
                "title": "Chapter 5: Polynomials",
                "resource_type": "textbook_chapter",
            },
            headers=authenticated_headers,
        )

        assert response.status_code == 201
        assert response.json()["title"] == "Chapter 5: Polynomials"

    def test_create_requires_auth(self, client: TestClient) -> None:
        response = client.post(
            "/resources/",
            json={
                "course_id": 10,
                "title": "Chapter 5",
                "resource_type": "textbook_chapter",
            },
        )
        assert response.status_code == 401


class TestGetResource:
    def test_get_returns_200(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=SAMPLE_RESOURCE))

        response = client.get("/resources/1", headers=authenticated_headers)

        assert response.status_code == 200
        assert response.json()["id"] == 1

    def test_get_not_found_returns_404(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=None))

        response = client.get("/resources/999", headers=authenticated_headers)

        assert response.status_code == 404

    def test_get_requires_auth(self, client: TestClient) -> None:
        response = client.get("/resources/1")
        assert response.status_code == 401


class TestListResources:
    def test_list_returns_paginated(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute = AsyncMock(
            return_value=MagicMock(data=[SAMPLE_RESOURCE], count=1)
        )

        response = client.get("/resources/", headers=authenticated_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1

    def test_list_with_course_filter(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute = AsyncMock(
            return_value=MagicMock(data=[SAMPLE_RESOURCE], count=1)
        )

        response = client.get(
            "/resources/?course_id=10",
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        mock_table.eq.assert_called_with("course_id", 10)

    def test_list_requires_auth(self, client: TestClient) -> None:
        response = client.get("/resources/")
        assert response.status_code == 401


class TestUpdateResource:
    def test_update_returns_200(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        updated = {**SAMPLE_RESOURCE, "title": "Chapter 6: Quadratics"}
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[updated]))

        response = client.put(
            "/resources/1",
            json={"title": "Chapter 6: Quadratics"},
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Chapter 6: Quadratics"

    def test_update_not_found_returns_404(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[]))

        response = client.put(
            "/resources/999",
            json={"title": "Chapter 6"},
            headers=authenticated_headers,
        )

        assert response.status_code == 404

    def test_update_requires_auth(self, client: TestClient) -> None:
        response = client.put("/resources/1", json={"title": "Chapter 6"})
        assert response.status_code == 401


class TestDeleteResource:
    def test_delete_returns_204(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.delete.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[SAMPLE_RESOURCE]))

        response = client.delete("/resources/1", headers=authenticated_headers)

        assert response.status_code == 204

    def test_delete_not_found_returns_404(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.delete.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[]))

        response = client.delete("/resources/999", headers=authenticated_headers)

        assert response.status_code == 404

    def test_delete_requires_auth(self, client: TestClient) -> None:
        response = client.delete("/resources/1")
        assert response.status_code == 401
