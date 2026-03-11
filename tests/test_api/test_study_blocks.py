"""Tests for the study_blocks CRUD router.

Ownership is verified via plan_id join — blocks inherit user scope
from their parent study plan.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.routers.study_blocks import router

USER_A_ID = "12345678-1234-5678-1234-567812345678"
USER_B_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

SAMPLE_BLOCK = {
    "id": 1,
    "plan_id": 10,
    "block_type": "plan",
    "title": "Review chapter 5",
    "description": None,
    "target_minutes": 30,
    "actual_minutes": None,
    "course_id": None,
    "assessment_id": None,
    "sort_order": 1,
    "status": "pending",
    "started_at": None,
    "completed_at": None,
}

SAMPLE_BLOCK_WITH_JOIN = {
    **SAMPLE_BLOCK,
    "study_plans": {"user_id": USER_A_ID},
}

PLAN_ROW = {"id": 10}


def _make_app(supabase_client: AsyncMock, user_id: str = USER_A_ID) -> FastAPI:
    app = FastAPI()
    app.state.supabase_client = supabase_client

    mock_user = MagicMock()
    mock_user.id = UUID(user_id)
    mock_user.email = "test@example.com"
    auth_response = MagicMock()
    auth_response.user = mock_user
    supabase_client.auth.get_user = AsyncMock(return_value=auth_response)

    app.include_router(router)
    return app


def _make_chain(data: list | dict | None, count: int | None = None) -> MagicMock:
    """Create a single mock chain that returns the given data."""
    result = MagicMock()
    result.data = data
    result.count = count

    chain = AsyncMock()
    chain.execute = AsyncMock(return_value=result)
    chain.eq = MagicMock(return_value=chain)
    chain.order = MagicMock(return_value=chain)
    chain.range = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.select = MagicMock(return_value=chain)
    chain.insert = MagicMock(return_value=chain)
    chain.update = MagicMock(return_value=chain)
    chain.delete = MagicMock(return_value=chain)
    return chain


HEADERS = {"Authorization": "Bearer test-jwt-token"}


class TestCreateBlock:
    def test_create_block_with_owned_plan(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """Creating a block succeeds when the plan belongs to the user."""
        # First call: plan ownership check, second call: insert
        plan_chain = _make_chain(PLAN_ROW)
        block_chain = _make_chain([SAMPLE_BLOCK])
        mock_supabase_client.table = MagicMock(side_effect=[plan_chain, block_chain])

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-blocks/",
                json={
                    "plan_id": 10,
                    "block_type": "plan",
                    "title": "Review chapter 5",
                    "target_minutes": 30,
                    "sort_order": 1,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Review chapter 5"

    def test_create_block_for_other_users_plan_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        """User B cannot create a block on user A's plan."""
        plan_chain = _make_chain(None)  # ownership check fails
        mock_supabase_client.table = MagicMock(return_value=plan_chain)

        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-blocks/",
                json={
                    "plan_id": 10,
                    "block_type": "plan",
                    "title": "Sneak in",
                    "target_minutes": 30,
                    "sort_order": 1,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PLAN_NOT_FOUND"

    def test_create_returns_401_without_auth(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-blocks/",
                json={
                    "plan_id": 10,
                    "block_type": "plan",
                    "title": "X",
                    "target_minutes": 30,
                    "sort_order": 1,
                },
            )
        assert resp.status_code == 401


class TestGetBlock:
    def test_get_own_block(self, mock_supabase_client: AsyncMock) -> None:
        chain = _make_chain(SAMPLE_BLOCK_WITH_JOIN)
        mock_supabase_client.table = MagicMock(return_value=chain)

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/1", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        # Nested join data should be stripped
        assert "study_plans" not in body

    def test_get_other_users_block_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        chain = _make_chain(None)  # join returns nothing
        mock_supabase_client.table = MagicMock(return_value=chain)

        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/1", headers=HEADERS)
        assert resp.status_code == 404


class TestListBlocks:
    def test_list_blocks_for_owned_plan(self, mock_supabase_client: AsyncMock) -> None:
        plan_chain = _make_chain(PLAN_ROW)
        block_chain = _make_chain([SAMPLE_BLOCK], count=1)
        mock_supabase_client.table = MagicMock(side_effect=[plan_chain, block_chain])

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/?plan_id=10", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1

    def test_list_blocks_for_other_users_plan_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        plan_chain = _make_chain(None)
        mock_supabase_client.table = MagicMock(return_value=plan_chain)

        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/?plan_id=10", headers=HEADERS)
        assert resp.status_code == 404

    def test_list_blocks_requires_plan_id(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/", headers=HEADERS)
        assert resp.status_code == 422  # validation error


class TestUpdateBlock:
    def test_update_own_block(self, mock_supabase_client: AsyncMock) -> None:
        ownership_chain = _make_chain(SAMPLE_BLOCK_WITH_JOIN)
        updated = {**SAMPLE_BLOCK, "title": "Updated title"}
        update_chain = _make_chain([updated])
        mock_supabase_client.table = MagicMock(
            side_effect=[ownership_chain, update_chain]
        )

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.put(
                "/study-blocks/1",
                json={"title": "Updated title"},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated title"

    def test_update_other_users_block_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        ownership_chain = _make_chain(None)
        mock_supabase_client.table = MagicMock(return_value=ownership_chain)

        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.put(
                "/study-blocks/1",
                json={"title": "Nope"},
                headers=HEADERS,
            )
        assert resp.status_code == 404


class TestDeleteBlock:
    def test_delete_own_block(self, mock_supabase_client: AsyncMock) -> None:
        ownership_chain = _make_chain(SAMPLE_BLOCK_WITH_JOIN)
        delete_chain = _make_chain([SAMPLE_BLOCK])
        mock_supabase_client.table = MagicMock(
            side_effect=[ownership_chain, delete_chain]
        )

        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.delete("/study-blocks/1", headers=HEADERS)
        assert resp.status_code == 204

    def test_delete_other_users_block_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        ownership_chain = _make_chain(None)
        mock_supabase_client.table = MagicMock(return_value=ownership_chain)

        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.delete("/study-blocks/1", headers=HEADERS)
        assert resp.status_code == 404
