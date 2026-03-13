"""Tests for coach chat endpoints — send message and get history."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_ai_client, get_user_client
from mitty.api.routers.coach import router

USER_ID = "12345678-1234-5678-1234-567812345678"

SAMPLE_BLOCK = {
    "id": 10,
    "plan_id": 1,
    "block_type": "retrieval",
    "title": "Review Quadratics",
    "description": "Practice quadratic equations",
    "target_minutes": 25,
    "actual_minutes": None,
    "course_id": 100,
    "assessment_id": 5,
    "sort_order": 0,
    "status": "pending",
    "started_at": None,
    "completed_at": None,
}

SAMPLE_MESSAGE = {
    "id": 1,
    "user_id": USER_ID,
    "study_block_id": 10,
    "role": "student",
    "content": "Can you explain quadratic equations?",
    "sources_cited": None,
    "created_at": "2026-03-12T10:00:00",
}

SAMPLE_COACH_MESSAGE = {
    "id": 2,
    "user_id": USER_ID,
    "study_block_id": 10,
    "role": "coach",
    "content": "Sure! A quadratic equation has the form ax^2 + bx + c = 0.",
    "sources_cited": [{"chunk_id": 1, "title": "Algebra Notes", "excerpt": "..."}],
    "created_at": "2026-03-12T10:00:01",
}


@pytest.fixture()
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_ai() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def app(mock_client: MagicMock, mock_ai: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _user() -> dict[str, str]:
        return {"user_id": USER_ID, "email": "student@example.com"}

    async def _client() -> MagicMock:
        return mock_client

    async def _ai() -> AsyncMock:
        return mock_ai

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_user_client] = _client
    app.dependency_overrides[get_ai_client] = _ai
    return app


@pytest.fixture()
def app_no_ai(mock_client: MagicMock) -> FastAPI:
    """App with ai_client returning None."""
    app = FastAPI()
    app.include_router(router)

    async def _user() -> dict[str, str]:
        return {"user_id": USER_ID, "email": "student@example.com"}

    async def _client() -> MagicMock:
        return mock_client

    async def _ai() -> None:
        return None

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_user_client] = _client
    app.dependency_overrides[get_ai_client] = _ai
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _chain_mock(
    data: list | dict | None,
    count: int | None = None,
    *,
    raw: bool = False,
) -> MagicMock:
    """Build a fluent chained mock that returns the given data on .execute().

    When *raw* is True, ``result.data`` is set exactly as passed (useful for
    ``maybe_single()`` which returns a dict or None, not a list).
    """
    result = MagicMock()
    if raw:
        result.data = data
    else:
        result.data = data if isinstance(data, list) else ([data] if data else [])
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
        "limit",
        "maybe_single",
        "in_",
    ):
        getattr(chain, attr).return_value = chain
    return chain


class TestSendCoachMessage:
    """POST /study-blocks/{block_id}/coach/messages."""

    def test_happy_path(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """Sends message, gets coach response."""
        from mitty.ai.coach import CoachResponse

        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        msg_chain = _chain_mock({"created_at": "2026-03-12T10:00:00+00:00"}, raw=True)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return msg_chain

        mock_client.table = MagicMock(side_effect=route_table)

        coach_resp = CoachResponse(
            content="A quadratic equation has the form ax^2 + bx + c = 0.",
            sources_cited=[{"chunk_id": 1, "title": "Algebra Notes", "excerpt": "..."}],
            message_id=2,
        )

        with patch(
            "mitty.api.routers.coach.coach_chat",
            new_callable=AsyncMock,
            return_value=coach_resp,
        ):
            resp = client.post(
                "/study-blocks/10/coach/messages",
                json={"message": "Can you explain quadratic equations?"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "coach"
        assert body["id"] == 2
        assert body["study_block_id"] == 10
        assert "quadratic" in body["content"].lower()
        assert body["sources_cited"] is not None
        assert len(body["sources_cited"]) == 1

    def test_503_when_ai_unavailable(
        self,
        mock_client: MagicMock,
        app_no_ai: FastAPI,
    ) -> None:
        """Returns 503 when ai_client is None."""
        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        tc = TestClient(app_no_ai)
        resp = tc.post(
            "/study-blocks/10/coach/messages",
            json={"message": "Help me study"},
        )

        assert resp.status_code == 503

    def test_404_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when block not found or not owned."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.post(
            "/study-blocks/999/coach/messages",
            json={"message": "Help me study"},
        )

        assert resp.status_code == 404


class TestGetCoachMessages:
    """GET /study-blocks/{block_id}/coach/messages."""

    def test_happy_path(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns paginated messages."""
        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        messages_chain = _chain_mock([SAMPLE_MESSAGE, SAMPLE_COACH_MESSAGE], count=2)

        call_count = {"study_blocks": 0, "coach_messages": 0}

        def route_table(name: str) -> MagicMock:
            call_count[name] = call_count.get(name, 0) + 1
            if name == "study_blocks":
                return block_chain
            return messages_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/coach/messages")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["data"]) == 2
        assert body["data"][0]["role"] == "student"
        assert body["data"][1]["role"] == "coach"
        assert body["offset"] == 0
        assert body["limit"] == 50

    def test_empty_list(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns empty list when no messages exist."""
        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        empty_chain = _chain_mock([], count=0)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return empty_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/coach/messages")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["data"] == []

    def test_pagination(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Offset and limit parameters are respected."""
        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        messages_chain = _chain_mock([SAMPLE_COACH_MESSAGE], count=5)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return messages_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/coach/messages?offset=2&limit=1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["offset"] == 2
        assert body["limit"] == 1
        assert len(body["data"]) == 1

    def test_404_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when block not found."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.get("/study-blocks/999/coach/messages")

        assert resp.status_code == 404


class TestAuthRequired:
    """Verify endpoints require authentication."""

    def test_post_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-blocks/10/coach/messages",
                json={"message": "Hello"},
            )
        assert resp.status_code in (401, 500)

    def test_get_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/10/coach/messages")
        assert resp.status_code in (401, 500)
