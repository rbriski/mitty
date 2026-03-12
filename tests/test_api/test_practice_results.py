"""Tests for practice_results CRUD router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.routers.practice_results import router

USER_ID = "12345678-1234-5678-1234-567812345678"

SAMPLE_RESULT = {
    "id": 1,
    "user_id": USER_ID,
    "study_block_id": 5,
    "course_id": 10,
    "concept": "Quadratics",
    "practice_type": "multiple_choice",
    "question_text": "Solve x^2 + 2x + 1 = 0",
    "student_answer": "x = -1",
    "correct_answer": "x = -1",
    "is_correct": True,
    "confidence_before": 3.0,
    "time_spent_seconds": 120,
    "score": 1.0,
    "feedback": "Correct!",
    "misconceptions_detected": None,
    "created_at": "2025-01-01T00:00:00",
}


@pytest.fixture()
def mock_client() -> MagicMock:
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


class TestCreatePracticeResult:
    def test_create_returns_201(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock(SAMPLE_RESULT)
        mock_client.table.return_value = chain

        response = client.post(
            "/practice-results/",
            json={
                "user_id": USER_ID,
                "course_id": 10,
                "practice_type": "multiple_choice",
                "question_text": "Solve x^2 + 2x + 1 = 0",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["user_id"] == USER_ID
        assert body["practice_type"] == "multiple_choice"

    def test_create_injects_user_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock(SAMPLE_RESULT)
        mock_client.table.return_value = chain

        client.post(
            "/practice-results/",
            json={
                "user_id": USER_ID,
                "course_id": 10,
                "practice_type": "multiple_choice",
                "question_text": "test",
            },
        )

        call_args = chain.insert.call_args
        assert call_args[0][0]["user_id"] == USER_ID


class TestGetPracticeResult:
    def test_get_returns_result(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_RESULT])
        mock_client.table.return_value = chain

        response = client.get("/practice-results/1")

        assert response.status_code == 200
        assert response.json()["id"] == 1

    def test_get_not_found(self, client: TestClient, mock_client: MagicMock) -> None:
        chain = _chain_mock([])
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=None))
        mock_client.table.return_value = chain

        response = client.get("/practice-results/999")

        assert response.status_code == 404


class TestListPracticeResults:
    def test_list_returns_paginated(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_RESULT], count=1)
        mock_client.table.return_value = chain

        response = client.get("/practice-results/")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1

    def test_list_orders_by_created_at_desc(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([], count=0)
        mock_client.table.return_value = chain

        client.get("/practice-results/")

        chain.order.assert_called_once_with("created_at", desc=True)

    def test_list_filters_by_course_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([], count=0)
        mock_client.table.return_value = chain

        client.get("/practice-results/?course_id=10")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("course_id", 10) for call in eq_calls)

    def test_list_filters_by_study_block_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([], count=0)
        mock_client.table.return_value = chain

        client.get("/practice-results/?study_block_id=5")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("study_block_id", 5) for call in eq_calls)


class TestUpdatePracticeResult:
    def test_update_returns_updated(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        updated = {**SAMPLE_RESULT, "is_correct": False}
        chain = _chain_mock(updated)
        mock_client.table.return_value = chain

        response = client.put("/practice-results/1", json={"is_correct": False})

        assert response.status_code == 200

    def test_update_empty_body_returns_400(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        response = client.put("/practice-results/1", json={})

        assert response.status_code == 400

    def test_update_not_found(self, client: TestClient, mock_client: MagicMock) -> None:
        chain = _chain_mock([])
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=None))
        mock_client.table.return_value = chain

        response = client.put("/practice-results/999", json={"is_correct": True})

        assert response.status_code == 404


class TestDeletePracticeResult:
    def test_delete_returns_204(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock(SAMPLE_RESULT)
        mock_client.table.return_value = chain

        response = client.delete("/practice-results/1")

        assert response.status_code == 204

    def test_delete_not_found(self, client: TestClient, mock_client: MagicMock) -> None:
        chain = _chain_mock([])
        chain.execute = AsyncMock(return_value=MagicMock(data=[], count=None))
        mock_client.table.return_value = chain

        response = client.delete("/practice-results/999")

        assert response.status_code == 404


class TestUserIsolation:
    def test_get_filters_by_user_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([SAMPLE_RESULT])
        mock_client.table.return_value = chain

        client.get("/practice-results/1")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_ID) for call in eq_calls)

    def test_list_filters_by_user_id(
        self, client: TestClient, mock_client: MagicMock
    ) -> None:
        chain = _chain_mock([], count=0)
        mock_client.table.return_value = chain

        client.get("/practice-results/")

        eq_calls = chain.eq.call_args_list
        assert any(call[0] == ("user_id", USER_ID) for call in eq_calls)
