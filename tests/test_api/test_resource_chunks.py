"""Tests for the resource_chunks CRUD router."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Generator

SAMPLE_CHUNK = {
    "id": 1,
    "resource_id": 5,
    "chunk_index": 0,
    "content_text": "Polynomials are expressions.",
    "token_count": 42,
    "created_at": "2026-03-01T00:00:00",
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
        app.state.supabase_admin = mock_supabase_client
        app.state.supabase_client = mock_supabase_client
        yield tc


class TestCreateResourceChunk:
    def test_create_returns_201(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[SAMPLE_CHUNK]))

        response = client.post(
            "/resource-chunks/",
            json={
                "resource_id": 5,
                "chunk_index": 0,
                "content_text": "Polynomials are expressions.",
                "token_count": 42,
            },
            headers=authenticated_headers,
        )

        assert response.status_code == 201
        assert response.json()["resource_id"] == 5

    def test_create_requires_auth(self, client: TestClient) -> None:
        response = client.post(
            "/resource-chunks/",
            json={
                "resource_id": 5,
                "chunk_index": 0,
                "content_text": "text",
                "token_count": 1,
            },
        )
        assert response.status_code == 401


class TestGetResourceChunk:
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
        mock_table.maybe_single.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=SAMPLE_CHUNK))

        response = client.get("/resource-chunks/1", headers=authenticated_headers)

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
        mock_table.maybe_single.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=None))

        response = client.get("/resource-chunks/999", headers=authenticated_headers)

        assert response.status_code == 404

    def test_get_requires_auth(self, client: TestClient) -> None:
        response = client.get("/resource-chunks/1")
        assert response.status_code == 401


class TestListResourceChunks:
    def test_list_returns_paginated(
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
            return_value=MagicMock(data=[SAMPLE_CHUNK], count=1)
        )

        response = client.get(
            "/resource-chunks/?resource_id=5",
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1

    def test_list_requires_resource_id(
        self,
        client: TestClient,
        authenticated_headers: dict[str, str],
    ) -> None:
        """resource_id is a required query param."""
        response = client.get("/resource-chunks/", headers=authenticated_headers)
        assert response.status_code == 422

    def test_list_requires_auth(self, client: TestClient) -> None:
        response = client.get("/resource-chunks/?resource_id=5")
        assert response.status_code == 401


class TestUpdateResourceChunk:
    def test_update_returns_200(
        self,
        client: TestClient,
        mock_supabase_client: AsyncMock,
        authenticated_headers: dict[str, str],
    ) -> None:
        updated = {**SAMPLE_CHUNK, "content_text": "Updated content."}
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[updated]))

        response = client.put(
            "/resource-chunks/1",
            json={"content_text": "Updated content."},
            headers=authenticated_headers,
        )

        assert response.status_code == 200
        assert response.json()["content_text"] == "Updated content."

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
            "/resource-chunks/999",
            json={"content_text": "Updated."},
            headers=authenticated_headers,
        )

        assert response.status_code == 404

    def test_update_requires_auth(self, client: TestClient) -> None:
        response = client.put(
            "/resource-chunks/1",
            json={"content_text": "Updated."},
        )
        assert response.status_code == 401


class TestDeleteResourceChunk:
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
        mock_table.execute = AsyncMock(return_value=MagicMock(data=[SAMPLE_CHUNK]))

        response = client.delete("/resource-chunks/1", headers=authenticated_headers)

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

        response = client.delete("/resource-chunks/999", headers=authenticated_headers)

        assert response.status_code == 404

    def test_delete_requires_auth(self, client: TestClient) -> None:
        response = client.delete("/resource-chunks/1")
        assert response.status_code == 401
