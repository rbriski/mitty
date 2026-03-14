"""Tests for block guide and artifact endpoints (Phase 6).

Covers:
- GET  /study-plans/{plan_id}/guides          (batch fetch)
- GET  /study-blocks/{block_id}/guide         (single guide)
- POST /study-blocks/{block_id}/guide/retry   (recompile stub)
- POST /study-blocks/{block_id}/artifacts     (submit artifact)
- GET  /study-blocks/{block_id}/artifacts     (list paginated)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_user_client
from mitty.api.routers.block_guides import router

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

SAMPLE_GUIDE = {
    "id": 1,
    "block_id": 10,
    "concepts_json": [{"name": "quadratics", "weight": 1.0}],
    "source_bundle_json": [{"chunk_id": 1, "content": "..."}],
    "steps_json": [{"step": 1, "instruction": "Read the notes"}],
    "warmup_items_json": [{"question": "What is 2+2?"}],
    "exit_items_json": [{"question": "Solve x^2=4"}],
    "completion_criteria_json": {"min_steps": 3},
    "success_criteria_json": ["Complete all steps", "Pass exit ticket"],
    "guide_version": "1.0",
    "generated_at": "2026-03-12T10:00:00",
}

SAMPLE_ARTIFACT = {
    "id": 1,
    "block_id": 10,
    "step_number": 1,
    "artifact_type": "answer",
    "content_json": {"text": "x = 2 or x = -2"},
    "created_at": "2026-03-12T10:05:00",
}

PLAN_ROW = {"id": 1}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GET /study-plans/{plan_id}/guides
# ---------------------------------------------------------------------------


class TestBatchGetGuides:
    """GET /study-plans/{plan_id}/guides."""

    def test_happy_path(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns all guides for blocks in the plan."""
        plan_chain = _chain_mock(PLAN_ROW, raw=True)
        blocks_chain = _chain_mock([{"id": 10}, {"id": 11}])
        guides_chain = _chain_mock([SAMPLE_GUIDE])

        def route_table(name: str) -> MagicMock:
            if name == "study_plans":
                return plan_chain
            if name == "study_blocks":
                return blocks_chain
            return guides_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-plans/1/guides")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["block_id"] == 10
        assert body[0]["guide_version"] == "1.0"

    def test_empty_when_no_blocks(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns empty list when plan has no blocks."""
        plan_chain = _chain_mock(PLAN_ROW, raw=True)
        blocks_chain = _chain_mock([])

        def route_table(name: str) -> MagicMock:
            if name == "study_plans":
                return plan_chain
            return blocks_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-plans/1/guides")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_plan_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when the plan does not exist or is not owned."""
        plan_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=plan_chain)

        resp = client.get("/study-plans/999/guides")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PLAN_NOT_FOUND"


# ---------------------------------------------------------------------------
# GET /study-blocks/{block_id}/guide
# ---------------------------------------------------------------------------


class TestGetGuide:
    """GET /study-blocks/{block_id}/guide."""

    def test_happy_path(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns the guide for a block the user owns."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        guide_chain = _chain_mock(SAMPLE_GUIDE, raw=True)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return guide_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/guide")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["block_id"] == 10
        assert body["concepts_json"] is not None

    def test_guide_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 GUIDE_NOT_FOUND when no guide exists."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        guide_chain = _chain_mock(None, raw=True)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return guide_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/guide")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "GUIDE_NOT_FOUND"

    def test_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 BLOCK_NOT_FOUND when block does not exist."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.get("/study-blocks/999/guide")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "BLOCK_NOT_FOUND"


# ---------------------------------------------------------------------------
# POST /study-blocks/{block_id}/guide/retry
# ---------------------------------------------------------------------------


class TestRetryGuide:
    """POST /study-blocks/{block_id}/guide/retry."""

    def test_returns_501(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 501 since compiler integration is not yet implemented."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.post("/study-blocks/10/guide/retry")

        assert resp.status_code == 501
        assert resp.json()["detail"]["code"] == "GUIDE_FAILED"

    def test_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when block does not exist."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.post("/study-blocks/999/guide/retry")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "BLOCK_NOT_FOUND"


# ---------------------------------------------------------------------------
# POST /study-blocks/{block_id}/artifacts
# ---------------------------------------------------------------------------


class TestCreateArtifact:
    """POST /study-blocks/{block_id}/artifacts."""

    def test_happy_path(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Creates an artifact and returns 201."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        artifact_chain = _chain_mock([SAMPLE_ARTIFACT])

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return artifact_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.post(
            "/study-blocks/10/artifacts",
            json={
                "step_number": 1,
                "artifact_type": "answer",
                "content_json": {"text": "x = 2 or x = -2"},
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == 1
        assert body["block_id"] == 10
        assert body["step_number"] == 1
        assert body["artifact_type"] == "answer"

    def test_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when block does not exist."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.post(
            "/study-blocks/999/artifacts",
            json={
                "step_number": 1,
                "artifact_type": "answer",
                "content_json": {"text": "test"},
            },
        )

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "BLOCK_NOT_FOUND"

    def test_validation_step_number_zero(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Rejects step_number < 1."""
        resp = client.post(
            "/study-blocks/10/artifacts",
            json={
                "step_number": 0,
                "artifact_type": "answer",
                "content_json": {"text": "test"},
            },
        )

        assert resp.status_code == 422

    def test_validation_artifact_type_too_long(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Rejects artifact_type longer than 50 chars."""
        resp = client.post(
            "/study-blocks/10/artifacts",
            json={
                "step_number": 1,
                "artifact_type": "x" * 51,
                "content_json": {"text": "test"},
            },
        )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /study-blocks/{block_id}/artifacts
# ---------------------------------------------------------------------------


class TestListArtifacts:
    """GET /study-blocks/{block_id}/artifacts."""

    def test_happy_path(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns paginated artifact list."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        artifacts_chain = _chain_mock([SAMPLE_ARTIFACT], count=1)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return artifacts_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/artifacts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["step_number"] == 1
        assert body["offset"] == 0
        assert body["limit"] == 20

    def test_empty_list(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns empty list when no artifacts exist."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        empty_chain = _chain_mock([], count=0)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return empty_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/artifacts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["data"] == []

    def test_pagination_params(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Offset and limit parameters are respected."""
        block_chain = _chain_mock(
            {**SAMPLE_BLOCK, "study_plans": {"user_id": USER_ID}}, raw=True
        )
        artifacts_chain = _chain_mock([SAMPLE_ARTIFACT], count=5)

        def route_table(name: str) -> MagicMock:
            if name == "study_blocks":
                return block_chain
            return artifacts_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.get("/study-blocks/10/artifacts?offset=2&limit=1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["offset"] == 2
        assert body["limit"] == 1

    def test_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when block does not exist."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.get("/study-blocks/999/artifacts")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "BLOCK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """Verify all endpoints require authentication."""

    def test_get_guides_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.get("/study-plans/1/guides")
        assert resp.status_code in (401, 500)

    def test_get_guide_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/10/guide")
        assert resp.status_code in (401, 500)

    def test_retry_guide_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post("/study-blocks/10/guide/retry")
        assert resp.status_code in (401, 500)

    def test_create_artifact_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post(
                "/study-blocks/10/artifacts",
                json={
                    "step_number": 1,
                    "artifact_type": "answer",
                    "content_json": {"text": "test"},
                },
            )
        assert resp.status_code in (401, 500)

    def test_list_artifacts_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.get("/study-blocks/10/artifacts")
        assert resp.status_code in (401, 500)
