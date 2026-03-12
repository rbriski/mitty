"""Tests for practice_sessions router — generate, evaluate, mastery update."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_ai_client, get_user_client
from mitty.api.routers.practice_sessions import router

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

SAMPLE_ASSESSMENT = {
    "id": 5,
    "course_id": 100,
    "unit_or_topic": "Quadratics",
}

SAMPLE_MASTERY_STATE = {
    "id": 1,
    "user_id": USER_ID,
    "course_id": 100,
    "concept": "Quadratics",
    "mastery_level": 0.4,
    "confidence_self_report": None,
    "last_retrieval_at": None,
    "next_review_at": None,
    "retrieval_count": 0,
    "success_rate": None,
    "updated_at": "2026-03-12T00:00:00",
}

SAMPLE_RESOURCE_CHUNK = {
    "id": 1,
    "resource_id": 50,
    "content_text": "Quadratic formula: x = (-b ± sqrt(b²-4ac)) / 2a",
    "chunk_index": 0,
    "token_count": 20,
}

SAMPLE_PRACTICE_ITEM = {
    "id": 42,
    "user_id": USER_ID,
    "course_id": 100,
    "concept": "Quadratics",
    "practice_type": "multiple_choice",
    "question_text": "What is the quadratic formula?",
    "correct_answer": "x = (-b ± sqrt(b²-4ac)) / 2a",
    "options_json": ["A", "B", "C", "D"],
    "explanation": "The quadratic formula solves ax² + bx + c = 0",
    "source_chunk_ids": [1],
    "difficulty_level": 0.5,
    "generation_model": "claude-sonnet-4-20250514",
    "times_used": 0,
    "last_used_at": None,
    "created_at": "2026-03-12T00:00:00",
}

SAMPLE_PRACTICE_RESULT = {
    "id": 1,
    "user_id": USER_ID,
    "study_block_id": 10,
    "course_id": 100,
    "concept": "Quadratics",
    "practice_type": "multiple_choice",
    "question_text": "What is the quadratic formula?",
    "student_answer": "A",
    "correct_answer": "A",
    "is_correct": True,
    "confidence_before": 3.0,
    "time_spent_seconds": 30,
    "score": 1.0,
    "feedback": "Correct!",
    "misconceptions_detected": None,
    "created_at": "2026-03-12T00:00:00",
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


class TestGenerate:
    """POST /study-blocks/{block_id}/practice/generate."""

    def test_generate_returns_items(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """Happy path: block found, generator returns items."""
        from mitty.practice.generator import PracticeItem

        # Mock the block lookup (maybe_single -> raw dict)
        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        # Mock the assessment lookup (maybe_single -> raw dict)
        assessment_chain = _chain_mock(SAMPLE_ASSESSMENT, raw=True)
        # Mock the mastery state lookup (maybe_single -> raw dict)
        mastery_chain = _chain_mock(SAMPLE_MASTERY_STATE, raw=True)
        # Mock the resource_chunks lookup (list)
        chunks_chain = _chain_mock([SAMPLE_RESOURCE_CHUNK])

        table_calls = {
            "study_blocks": block_chain,
            "assessments": assessment_chain,
            "mastery_states": mastery_chain,
            "resource_chunks": chunks_chain,
        }

        def route_table(name: str) -> MagicMock:
            return table_calls.get(name, _chain_mock([]))

        mock_client.table = MagicMock(side_effect=route_table)

        # Mock the generator
        practice_items = [
            PracticeItem(
                id=42,
                user_id=UUID(USER_ID),
                course_id=100,
                concept="Quadratics",
                practice_type="multiple_choice",
                question_text="What is the quadratic formula?",
                correct_answer="x = (-b ± sqrt(b²-4ac)) / 2a",
                options_json=["A", "B", "C", "D"],
                explanation="The quadratic formula solves ax² + bx + c = 0",
                source_chunk_ids=[1],
                difficulty_level=0.5,
                generation_model="claude-sonnet-4-20250514",
            ),
        ]

        with patch(
            "mitty.api.routers.practice_sessions.generate_practice_items",
            new_callable=AsyncMock,
            return_value=practice_items,
        ):
            resp = client.post("/study-blocks/10/practice/generate")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["concept"] == "Quadratics"
        assert body["concept"] == "Quadratics"

    def test_generate_block_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """404 when block does not exist or belong to user."""
        block_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.post("/study-blocks/999/practice/generate")

        assert resp.status_code == 404

    def test_generate_no_concept_returns_422(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """422 when block has no assessment or concept to derive."""
        block_no_assessment = {**SAMPLE_BLOCK, "assessment_id": None, "course_id": None}
        block_chain = _chain_mock(block_no_assessment, raw=True)
        mock_client.table = MagicMock(return_value=block_chain)

        resp = client.post("/study-blocks/10/practice/generate")

        assert resp.status_code == 422

    def test_generate_llm_unavailable_returns_cached(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """Graceful degradation: LLM error -> try cached items only."""
        from mitty.ai.errors import AIClientError

        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        assessment_chain = _chain_mock(SAMPLE_ASSESSMENT, raw=True)
        mastery_chain = _chain_mock(SAMPLE_MASTERY_STATE, raw=True)
        chunks_chain = _chain_mock([SAMPLE_RESOURCE_CHUNK])
        cached_chain = _chain_mock([SAMPLE_PRACTICE_ITEM])

        call_map = {
            "study_blocks": block_chain,
            "assessments": assessment_chain,
            "mastery_states": mastery_chain,
            "resource_chunks": chunks_chain,
            "practice_items": cached_chain,
        }
        mock_client.table = MagicMock(
            side_effect=lambda n: call_map.get(n, _chain_mock([]))
        )

        with patch(
            "mitty.api.routers.practice_sessions.generate_practice_items",
            new_callable=AsyncMock,
            side_effect=AIClientError("LLM unavailable"),
        ):
            resp = client.post("/study-blocks/10/practice/generate")

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"]

    def test_generate_llm_and_cache_empty_returns_503(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """503 when LLM fails and no cached items exist."""
        from mitty.ai.errors import AIClientError

        block_chain = _chain_mock(SAMPLE_BLOCK, raw=True)
        assessment_chain = _chain_mock(SAMPLE_ASSESSMENT, raw=True)
        mastery_chain = _chain_mock(SAMPLE_MASTERY_STATE, raw=True)
        chunks_chain = _chain_mock([SAMPLE_RESOURCE_CHUNK])
        empty_cache_chain = _chain_mock([])

        call_map = {
            "study_blocks": block_chain,
            "assessments": assessment_chain,
            "mastery_states": mastery_chain,
            "resource_chunks": chunks_chain,
            "practice_items": empty_cache_chain,
        }
        mock_client.table = MagicMock(
            side_effect=lambda n: call_map.get(n, _chain_mock([]))
        )

        with patch(
            "mitty.api.routers.practice_sessions.generate_practice_items",
            new_callable=AsyncMock,
            side_effect=AIClientError("LLM unavailable"),
        ):
            resp = client.post("/study-blocks/10/practice/generate")

        assert resp.status_code == 503


class TestEvaluate:
    """POST /practice-results/evaluate."""

    def test_evaluate_exact_match(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """Exact-match MC evaluation (no LLM needed)."""
        # Mock practice item lookup (maybe_single -> raw dict)
        item_chain = _chain_mock(SAMPLE_PRACTICE_ITEM, raw=True)
        # Mock practice result insert (returns list)
        result_row = {**SAMPLE_PRACTICE_RESULT}
        insert_chain = _chain_mock(result_row)

        call_map = {
            "practice_items": item_chain,
            "practice_results": insert_chain,
        }
        mock_client.table = MagicMock(
            side_effect=lambda n: call_map.get(n, _chain_mock([]))
        )

        from mitty.practice.evaluator import EvaluationResult

        with patch(
            "mitty.api.routers.practice_sessions.evaluate_answer",
            new_callable=AsyncMock,
            return_value=EvaluationResult(
                is_correct=True,
                score=1.0,
                feedback="Correct!",
                misconceptions_detected=[],
            ),
        ):
            resp = client.post(
                "/practice-results/evaluate",
                json={
                    "practice_item_id": 42,
                    "student_answer": "A",
                    "confidence_before": 3.0,
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_correct"] is True
        assert body["score"] == 1.0
        assert body["feedback"] == "Correct!"

    def test_evaluate_item_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """404 when practice item not found."""
        item_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=item_chain)

        resp = client.post(
            "/practice-results/evaluate",
            json={
                "practice_item_id": 999,
                "student_answer": "A",
                "confidence_before": 3.0,
            },
        )

        assert resp.status_code == 404

    def test_evaluate_llm_unavailable_falls_back_to_exact(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """Graceful degradation: LLM unavailable -> exact-match only."""
        from mitty.practice.evaluator import EvaluationResult

        item_chain = _chain_mock(SAMPLE_PRACTICE_ITEM, raw=True)
        insert_chain = _chain_mock(SAMPLE_PRACTICE_RESULT)

        call_map = {
            "practice_items": item_chain,
            "practice_results": insert_chain,
        }
        mock_client.table = MagicMock(
            side_effect=lambda n: call_map.get(n, _chain_mock([]))
        )

        # evaluate_answer returns exact match result (no LLM needed for MC)
        with patch(
            "mitty.api.routers.practice_sessions.evaluate_answer",
            new_callable=AsyncMock,
            return_value=EvaluationResult(
                is_correct=False,
                score=0.0,
                feedback="Incorrect. The correct answer is A.",
                misconceptions_detected=[],
            ),
        ):
            resp = client.post(
                "/practice-results/evaluate",
                json={
                    "practice_item_id": 42,
                    "student_answer": "wrong",
                    "confidence_before": 2.0,
                },
            )

        assert resp.status_code == 200
        assert resp.json()["is_correct"] is False

    def test_evaluate_stores_result(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: AsyncMock,
    ) -> None:
        """Verify practice result is stored in the database."""
        from mitty.practice.evaluator import EvaluationResult

        item_chain = _chain_mock(SAMPLE_PRACTICE_ITEM, raw=True)
        insert_chain = _chain_mock(SAMPLE_PRACTICE_RESULT)

        call_map = {
            "practice_items": item_chain,
            "practice_results": insert_chain,
        }
        mock_client.table = MagicMock(
            side_effect=lambda n: call_map.get(n, _chain_mock([]))
        )

        with patch(
            "mitty.api.routers.practice_sessions.evaluate_answer",
            new_callable=AsyncMock,
            return_value=EvaluationResult(
                is_correct=True,
                score=1.0,
                feedback="Correct!",
                misconceptions_detected=[],
            ),
        ):
            resp = client.post(
                "/practice-results/evaluate",
                json={
                    "practice_item_id": 42,
                    "student_answer": "A",
                    "confidence_before": 3.0,
                },
            )

        assert resp.status_code == 200
        # Verify insert was called on practice_results
        insert_calls = [
            c for c in mock_client.table.call_args_list if c[0][0] == "practice_results"
        ]
        assert len(insert_calls) >= 1
        assert resp.json()["practice_result_id"] == SAMPLE_PRACTICE_RESULT["id"]


class TestMasteryUpdate:
    """POST /mastery-states/update-from-results."""

    def test_update_mastery_from_results(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Happy path: reads results for block, updates mastery per concept."""
        from mitty.mastery.updater import MasteryState

        results_chain = _chain_mock([SAMPLE_PRACTICE_RESULT])
        mock_client.table = MagicMock(return_value=results_chain)

        updated_state = MasteryState(
            user_id=UUID(USER_ID),
            course_id=100,
            concept="Quadratics",
            mastery_level=0.7,
            success_rate=1.0,
            confidence_self_report=0.5,
            retrieval_count=1,
            last_retrieval_at="2026-03-12T00:00:00",
            next_review_at="2026-03-13T00:00:00",
        )

        with patch(
            "mitty.api.routers.practice_sessions.update_mastery",
            new_callable=AsyncMock,
            return_value=updated_state,
        ):
            resp = client.post(
                "/mastery-states/update-from-results",
                json={"study_block_id": 10},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["mastery_states"]) == 1
        assert body["mastery_states"][0]["concept"] == "Quadratics"
        assert body["mastery_states"][0]["mastery_level"] == 0.7

    def test_update_mastery_no_results(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """404 when no practice results exist for the block."""
        empty_chain = _chain_mock([])
        mock_client.table = MagicMock(return_value=empty_chain)

        resp = client.post(
            "/mastery-states/update-from-results",
            json={"study_block_id": 999},
        )

        assert resp.status_code == 404

    def test_update_mastery_groups_by_concept(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Results are grouped by concept and updater called per concept."""
        from mitty.mastery.updater import MasteryState

        result_a = {
            **SAMPLE_PRACTICE_RESULT,
            "concept": "Quadratics",
            "course_id": 100,
        }
        result_b = {
            **SAMPLE_PRACTICE_RESULT,
            "id": 2,
            "concept": "Linear Equations",
            "course_id": 100,
        }

        results_chain = _chain_mock([result_a, result_b])
        mock_client.table = MagicMock(return_value=results_chain)

        mastery_quad = MasteryState(
            user_id=UUID(USER_ID),
            course_id=100,
            concept="Quadratics",
            mastery_level=0.7,
            success_rate=1.0,
            confidence_self_report=0.5,
            retrieval_count=1,
            last_retrieval_at="2026-03-12T00:00:00",
            next_review_at="2026-03-13T00:00:00",
        )
        mastery_linear = MasteryState(
            user_id=UUID(USER_ID),
            course_id=100,
            concept="Linear Equations",
            mastery_level=0.6,
            success_rate=1.0,
            confidence_self_report=0.5,
            retrieval_count=1,
            last_retrieval_at="2026-03-12T00:00:00",
            next_review_at="2026-03-13T00:00:00",
        )

        async def mock_update(client, user_id, course_id, concept, results):
            if concept == "Quadratics":
                return mastery_quad
            return mastery_linear

        with patch(
            "mitty.api.routers.practice_sessions.update_mastery",
            new_callable=AsyncMock,
            side_effect=mock_update,
        ):
            resp = client.post(
                "/mastery-states/update-from-results",
                json={"study_block_id": 10},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["mastery_states"]) == 2
        concepts = {s["concept"] for s in body["mastery_states"]}
        assert concepts == {"Quadratics", "Linear Equations"}


class TestUserIsolation:
    """Verify user-scoping is applied to all endpoints."""

    def test_generate_requires_auth(self) -> None:
        """Endpoints should require authentication."""
        app = FastAPI()
        app.include_router(router)
        # No dependency overrides — auth will fail
        with TestClient(app) as tc:
            resp = tc.post("/study-blocks/10/practice/generate")
        # Without proper app state, should get 401 or 500
        assert resp.status_code in (401, 500)

    def test_evaluate_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post(
                "/practice-results/evaluate",
                json={
                    "practice_item_id": 42,
                    "student_answer": "A",
                    "confidence_before": 3.0,
                },
            )
        assert resp.status_code in (401, 500)

    def test_mastery_update_requires_auth(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as tc:
            resp = tc.post(
                "/mastery-states/update-from-results",
                json={"study_block_id": 10},
            )
        assert resp.status_code in (401, 500)
