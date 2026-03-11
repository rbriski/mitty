"""Tests for mastery_states CRUD router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.routers.mastery_states import router

USER_ID = "12345678-1234-5678-1234-567812345678"
OTHER_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

SAMPLE_STATE = {
    "id": 1,
    "user_id": USER_ID,
    "course_id": 10,
    "concept": "Algebra",
    "mastery_level": 0.7,
    "confidence_self_report": 0.5,
    "last_retrieval_at": None,
    "next_review_at": None,
    "retrieval_count": 3,
    "success_rate": 0.8,
    "updated_at": "2025-01-01T00:00:00",
}


@pytest.fixture()
def mock_client() -> MagicMock:
    """A sync MagicMock Supabase client (table() is sync, execute() is async)."""
    return MagicMock()


@pytest.fixture()
def app(mock_client: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _user() -> dict[str, str]:
        return {"user_id": USER_ID, "email": "student@example.com"}

    async def _client() -> MagicMock:
        return mock_client

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_user_client] = _client
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _chain_mock(data: list | dict, count: int | None = None) -> MagicMock:
    """Build a fluent chained mock that returns the given data on .execute()."""
    result = MagicMock()
    result.data = data if isinstance(data, list) else [data]
    result.count = count
    terminal = AsyncMock(return_value=result)

    chain = MagicMock()
    chain.execute = terminal
    # Every chained method returns itself (sync MagicMock for fluent API)
    for attr in (
        "select",
        "insert",
        "upsert",
        "update",
        "delete",
        "eq",
        "order",
        "range",
    ):
        getattr(chain, attr).return_value = chain
    return chain


class TestCreateMasteryState:
    def test_create_upserts_and_returns_201(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock(SAMPLE_STATE)
        mock_client.table.return_value = chain

        response = client.post(
            "/mastery-states/",
            json={
                "user_id": USER_ID,
                "course_id": 10,
                "concept": "Algebra",
                "mastery_level": 0.7,
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["concept"] == "Algebra"
        assert body["user_id"] == USER_ID
        chain.upsert.assert_called_once()
        # Verify user_id was injected from auth
        call_args = chain.upsert.call_args
        assert call_args[0][0]["user_id"] == USER_ID

    def test_create_overrides_user_id_from_body(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        """Even if body sends a different user_id, auth user_id wins."""
        chain = _chain_mock(SAMPLE_STATE)
        mock_client.table.return_value = chain

        response = client.post(
            "/mastery-states/",
            json={
                "user_id": OTHER_USER_ID,
                "course_id": 10,
                "concept": "Algebra",
            },
        )

        assert response.status_code == 201
        call_args = chain.upsert.call_args
        assert call_args[0][0]["user_id"] == USER_ID


class TestGetMasteryState:
    def test_get_returns_state(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_STATE])
        mock_client.table.return_value = chain

        response = client.get("/mastery-states/1")

        assert response.status_code == 200
        assert response.json()["id"] == 1

    def test_get_not_found(self, client: TestClient, mock_client: MagicMock) -> None:
        chain = _chain_mock([])
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=None))
        mock_client.table.return_value = chain

        response = client.get("/mastery-states/999")

        assert response.status_code == 404


class TestListMasteryStates:
    def test_list_returns_paginated(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_STATE], count=1)
        mock_client.table.return_value = chain

        response = client.get("/mastery-states/")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1
        assert body["offset"] == 0
        assert body["limit"] == 50

    def test_list_filters_by_course_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_STATE], count=1)
        mock_client.table.return_value = chain

        response = client.get("/mastery-states/?course_id=10")

        assert response.status_code == 200
        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("course_id", 10) for call in eq_calls)


class TestUpdateMasteryState:
    def test_update_returns_updated(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        updated = {**SAMPLE_STATE, "mastery_level": 0.9}
        chain = _chain_mock(updated)
        mock_client.table.return_value = chain

        response = client.put("/mastery-states/1", json={"mastery_level": 0.9})

        assert response.status_code == 200
        assert response.json()["mastery_level"] == 0.9

    def test_update_empty_body_returns_400(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        response = client.put("/mastery-states/1", json={})

        assert response.status_code == 400

    def test_update_not_found(self, client: TestClient, mock_client: MagicMock) -> None:
        chain = _chain_mock([])
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=None))
        mock_client.table.return_value = chain

        response = client.put("/mastery-states/999", json={"mastery_level": 0.5})

        assert response.status_code == 404


class TestDeleteMasteryState:
    def test_delete_returns_204(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock(SAMPLE_STATE)
        mock_client.table.return_value = chain

        response = client.delete("/mastery-states/1")

        assert response.status_code == 204

    def test_delete_not_found(self, client: TestClient, mock_client: MagicMock) -> None:
        chain = _chain_mock([])
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=None))
        mock_client.table.return_value = chain

        response = client.delete("/mastery-states/999")

        assert response.status_code == 404


class TestUserIsolation:
    """Verify that user_id filter is always applied."""

    def test_get_filters_by_user_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_STATE])
        mock_client.table.return_value = chain

        client.get("/mastery-states/1")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_ID) for call in eq_calls)

    def test_list_filters_by_user_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([], count=0)
        mock_client.table.return_value = chain

        client.get("/mastery-states/")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_ID) for call in eq_calls)

    def test_delete_filters_by_user_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock(SAMPLE_STATE)
        mock_client.table.return_value = chain

        client.delete("/mastery-states/1")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_ID) for call in eq_calls)
