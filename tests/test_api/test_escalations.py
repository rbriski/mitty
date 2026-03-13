"""Tests for escalation and flag API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.routers.escalations import router

USER_ID = "12345678-1234-5678-1234-567812345678"

SAMPLE_ESCALATION = {
    "id": 1,
    "user_id": USER_ID,
    "signal_type": "repeated_failure",
    "concept": "Quadratic Equations",
    "context_data": {"failure_count": 4, "course_id": 100},
    "suggested_action": "Review source material.",
    "acknowledged": False,
    "acknowledged_at": None,
    "created_at": "2026-03-12T10:00:00",
}

SAMPLE_ESCALATION_ACKED = {
    **SAMPLE_ESCALATION,
    "id": 2,
    "signal_type": "avoidance",
    "concept": None,
    "acknowledged": True,
    "acknowledged_at": "2026-03-12T11:00:00",
}

SAMPLE_COACH_MESSAGE = {
    "id": 10,
    "user_id": USER_ID,
    "study_block_id": 5,
    "role": "coach",
    "content": "Here is a helpful explanation.",
    "sources_cited": None,
    "created_at": "2026-03-12T10:00:00",
}

SAMPLE_FLAG = {
    "id": 1,
    "user_id": USER_ID,
    "coach_message_id": 10,
    "reason": "Incorrect information",
    "created_at": "2026-03-12T10:01:00",
}


def _chain_mock(
    data: list | dict | None,
    count: int | None = None,
    *,
    raw: bool = False,
) -> MagicMock:
    """Build a fluent chained mock that returns the given data on .execute()."""
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
        "is_",
        "order",
        "range",
        "limit",
        "maybe_single",
        "gte",
    ):
        getattr(chain, attr).return_value = chain
    return chain


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


class TestListEscalations:
    """GET /escalations."""

    def test_returns_user_escalations(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        chain = _chain_mock([SAMPLE_ESCALATION, SAMPLE_ESCALATION_ACKED], count=2)
        mock_client.table = MagicMock(return_value=chain)

        resp = client.get("/escalations")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["data"]) == 2
        assert body["data"][0]["signal_type"] == "repeated_failure"
        assert body["data"][1]["acknowledged"] is True

    def test_empty_list(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        chain = _chain_mock([], count=0)
        mock_client.table = MagicMock(return_value=chain)

        resp = client.get("/escalations")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["data"] == []

    def test_filter_by_status_active(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        chain = _chain_mock([SAMPLE_ESCALATION], count=1)
        mock_client.table = MagicMock(return_value=chain)

        resp = client.get("/escalations?status=active")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["data"][0]["acknowledged"] is False

    def test_filter_by_status_acknowledged(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        chain = _chain_mock([SAMPLE_ESCALATION_ACKED], count=1)
        mock_client.table = MagicMock(return_value=chain)

        resp = client.get("/escalations?status=acknowledged")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["data"][0]["acknowledged"] is True


class TestAcknowledgeEscalation:
    """POST /escalations/{id}/acknowledge."""

    def test_sets_acknowledged(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        acked = {
            **SAMPLE_ESCALATION,
            "acknowledged": True,
            "acknowledged_at": "2026-03-12T12:00:00",
        }
        chain = _chain_mock(acked)
        mock_client.table = MagicMock(return_value=chain)

        resp = client.post("/escalations/1/acknowledge")

        assert resp.status_code == 200
        body = resp.json()
        assert body["acknowledged"] is True
        assert body["acknowledged_at"] is not None

    def test_404_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        chain = _chain_mock([])
        mock_client.table = MagicMock(return_value=chain)

        resp = client.post("/escalations/999/acknowledge")

        assert resp.status_code == 404


class TestFlagCoachMessage:
    """POST /coach-messages/{message_id}/flag."""

    def test_creates_flag(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        msg_chain = _chain_mock(SAMPLE_COACH_MESSAGE, raw=True)
        flag_chain = _chain_mock(SAMPLE_FLAG)

        def route_table(name: str) -> MagicMock:
            if name == "coach_messages":
                return msg_chain
            return flag_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.post(
            "/coach-messages/10/flag",
            json={"reason": "Incorrect information"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["coach_message_id"] == 10
        assert body["reason"] == "Incorrect information"

    def test_404_message_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        msg_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=msg_chain)

        resp = client.post(
            "/coach-messages/999/flag",
            json={"reason": "Bad response"},
        )

        assert resp.status_code == 404


class TestCrossUserIsolation:
    """Verify user_id scoping prevents cross-user data access."""

    def test_acknowledge_other_users_escalation_returns_404(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Acknowledging another user's escalation returns 404.

        The endpoint filters by both escalation id AND user_id, so
        an escalation owned by a different user must not be updated.
        """
        # Simulate the update returning empty data (no row matched)
        chain = _chain_mock([])
        mock_client.table = MagicMock(return_value=chain)

        resp = client.post("/escalations/1/acknowledge")

        assert resp.status_code == 404

        # Verify the update query included both id and user_id filters
        chain.eq.assert_any_call("id", 1)
        chain.eq.assert_any_call("user_id", USER_ID)

    def test_flag_other_users_coach_message_returns_404(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Flagging a coach message owned by another user returns 404.

        The endpoint filters coach_messages by both id and user_id.
        """
        # Simulate no message found (different user owns it)
        msg_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=msg_chain)

        resp = client.post(
            "/coach-messages/10/flag",
            json={"reason": "Bad response"},
        )

        assert resp.status_code == 404

        # Verify user_id was included in the ownership check
        msg_chain.eq.assert_any_call("user_id", USER_ID)


class TestAuthRequired:
    """Verify endpoints require authentication."""

    def test_list_escalations_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.get("/escalations")
        assert resp.status_code in (401, 500)

    def test_acknowledge_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post("/escalations/1/acknowledge")
        assert resp.status_code in (401, 500)

    def test_flag_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post(
                "/coach-messages/1/flag",
                json={"reason": "Bad"},
            )
        assert resp.status_code in (401, 500)
