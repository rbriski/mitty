"""Tests for the study_plans CRUD router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.routers.study_plans import router

USER_A_ID = "12345678-1234-5678-1234-567812345678"
USER_B_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

SAMPLE_PLAN = {
    "id": 1,
    "user_id": USER_A_ID,
    "plan_date": "2026-03-11",
    "total_minutes": 120,
    "status": "draft",
    "created_at": "2026-03-11T08:00:00",
    "updated_at": "2026-03-11T08:00:00",
}


def _make_app(supabase_client: AsyncMock, user_id: str = USER_A_ID) -> FastAPI:
    app = FastAPI()
    app.state.supabase_admin = supabase_client
    app.state.supabase_client = supabase_client

    mock_user = MagicMock()
    mock_user.id = UUID(user_id)
    mock_user.email = "test@example.com"
    auth_response = MagicMock()
    auth_response.user = mock_user
    supabase_client.auth.get_user = AsyncMock(return_value=auth_response)

    app.include_router(router)
    return app


def _mock_chain(
    client: AsyncMock, data: list | dict | None, count: int | None = None
) -> None:
    result = MagicMock()
    result.data = data
    result.count = count

    chain = AsyncMock()
    chain.execute = AsyncMock(return_value=result)
    chain.eq = MagicMock(return_value=chain)
    chain.gte = MagicMock(return_value=chain)
    chain.lte = MagicMock(return_value=chain)
    chain.order = MagicMock(return_value=chain)
    chain.range = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.select = MagicMock(return_value=chain)
    chain.insert = MagicMock(return_value=chain)
    chain.update = MagicMock(return_value=chain)
    chain.delete = MagicMock(return_value=chain)

    client.table = MagicMock(return_value=chain)


HEADERS = {"Authorization": "Bearer test-jwt-token"}


class TestCreatePlan:
    def test_create_injects_user_id(self, mock_supabase_client: AsyncMock) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN])
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-plans/",
                json={
                    "user_id": USER_B_ID,
                    "plan_date": "2026-03-11",
                    "total_minutes": 120,
                },
                headers=HEADERS,
            )
        assert resp.status_code == 201
        insert_call = mock_supabase_client.table.return_value.insert
        inserted_row = insert_call.call_args[0][0]
        assert inserted_row["user_id"] == USER_A_ID

    def test_create_returns_401_without_auth(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN])
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-plans/",
                json={
                    "user_id": USER_A_ID,
                    "plan_date": "2026-03-11",
                    "total_minutes": 120,
                },
            )
        assert resp.status_code == 401


class TestGetPlan:
    def test_get_own_plan(self, mock_supabase_client: AsyncMock) -> None:
        _mock_chain(mock_supabase_client, SAMPLE_PLAN)
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/1", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    def test_get_other_users_plan_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        _mock_chain(mock_supabase_client, None)
        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/1", headers=HEADERS)
        assert resp.status_code == 404


class TestListPlans:
    def test_list_own_plans(self, mock_supabase_client: AsyncMock) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN], count=1)
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1

    def test_list_with_date_filters(self, mock_supabase_client: AsyncMock) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN], count=1)
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.get(
                "/study-plans/?date_from=2026-03-01&date_to=2026-03-31",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        chain = mock_supabase_client.table.return_value
        chain.gte.assert_called_once_with("plan_date", "2026-03-01")
        chain.lte.assert_called_once_with("plan_date", "2026-03-31")

    def test_list_filters_by_user_id(self, mock_supabase_client: AsyncMock) -> None:
        _mock_chain(mock_supabase_client, [], count=0)
        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/", headers=HEADERS)
        assert resp.status_code == 200
        chain = mock_supabase_client.table.return_value
        eq_calls = [c for c in chain.eq.call_args_list if c[0][0] == "user_id"]
        assert len(eq_calls) == 1
        assert eq_calls[0][0][1] == USER_B_ID


class TestUpdatePlan:
    def test_update_own_plan(self, mock_supabase_client: AsyncMock) -> None:
        updated = {**SAMPLE_PLAN, "total_minutes": 90}
        _mock_chain(mock_supabase_client, [updated])
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.put(
                "/study-plans/1",
                json={"total_minutes": 90},
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["total_minutes"] == 90

    def test_update_other_users_plan_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        _mock_chain(mock_supabase_client, [])
        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.put(
                "/study-plans/1",
                json={"total_minutes": 90},
                headers=HEADERS,
            )
        assert resp.status_code == 404


class TestDeletePlan:
    def test_delete_own_plan(self, mock_supabase_client: AsyncMock) -> None:
        _mock_chain(mock_supabase_client, [SAMPLE_PLAN])
        app = _make_app(mock_supabase_client)
        with TestClient(app) as tc:
            resp = tc.delete("/study-plans/1", headers=HEADERS)
        assert resp.status_code == 204

    def test_delete_other_users_plan_returns_404(
        self, mock_supabase_client: AsyncMock
    ) -> None:
        _mock_chain(mock_supabase_client, [])
        app = _make_app(mock_supabase_client, user_id=USER_B_ID)
        with TestClient(app) as tc:
            resp = tc.delete("/study-plans/1", headers=HEADERS)
        assert resp.status_code == 404
