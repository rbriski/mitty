"""Tests for test prep API endpoints (US-010).

Covers:
- POST /test-prep/analyze-homework  (SSE stream)
- GET  /test-prep/mastery-profile   (mastery profile)
- POST /test-prep/sessions          (create session)
- GET  /test-prep/sessions/{id}     (get session)
- POST /test-prep/sessions/{id}/answer   (submit answer)
- POST /test-prep/sessions/{id}/skip-phase  (advance phase)
- POST /test-prep/sessions/{id}/complete    (complete session)

Traces: DEC-002, DEC-006, DEC-008, DEC-010.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mitty.api.auth import get_current_user
from mitty.api.dependencies import get_ai_client, get_user_client
from mitty.api.routers.test_prep import router

USER_ID = "12345678-1234-5678-1234-567812345678"
OTHER_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

SESSION_ID = str(uuid4())

SAMPLE_STATE_JSON = {
    "session_id": SESSION_ID,
    "user_id": USER_ID,
    "course_id": 100,
    "phase": "diagnostic",
    "difficulty": 0.5,
    "concepts": ["polynomial long division"],
    "concept_mastery": {},
    "total_problems": 0,
    "total_correct": 0,
    "consecutive_correct": 0,
    "consecutive_wrong": 0,
    "phase_problems": {},
    "phase_correct": {},
}

SAMPLE_SESSION_ROW = {
    "id": SESSION_ID,
    "user_id": USER_ID,
    "course_id": 100,
    "assessment_id": 5,
    "state_json": SAMPLE_STATE_JSON,
    "started_at": "2026-03-14T10:00:00",
    "completed_at": None,
    "total_problems": 0,
    "total_correct": 0,
    "duration_seconds": None,
    "phase_reached": "diagnostic",
}

SAMPLE_RESULT_ROW = {
    "id": 1,
    "user_id": USER_ID,
    "session_id": SESSION_ID,
    "concept": "polynomial long division",
    "problem_json": {
        "id": "p-1",
        "prompt": "Divide x^3 + 2x by x",
        "correct_answer": "x^2 + 2",
    },
    "student_answer": "x^2 + 2",
    "is_correct": True,
    "score": 1.0,
    "feedback": "Correct!",
    "hints_used": 0,
    "worked_example_shown": False,
    "time_spent_seconds": 30,
    "difficulty": 0.5,
    "created_at": "2026-03-14T10:01:00",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_ai() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def app(mock_client: MagicMock, mock_ai: MagicMock) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(router)

    async def _user() -> dict[str, str]:
        return {
            "user_id": USER_ID,
            "email": "student@example.com",
            "access_token": "test-jwt",
        }

    async def _client() -> MagicMock:
        return mock_client

    async def _ai() -> MagicMock:
        return mock_ai

    test_app.dependency_overrides[get_current_user] = _user
    test_app.dependency_overrides[get_user_client] = _client
    test_app.dependency_overrides[get_ai_client] = _ai
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


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
        "order",
        "range",
        "limit",
        "maybe_single",
        "in_",
        "is_",
    ):
        getattr(chain, attr).return_value = chain
    return chain


# ---------------------------------------------------------------------------
# Auth required — all endpoints must return 401/500 without auth
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """Verify all endpoints require authentication."""

    def test_analyze_homework_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        with TestClient(test_app) as tc:
            resp = tc.post(
                "/test-prep/analyze-homework",
                json={"assignment_id": 1, "course_id": 100},
            )
        assert resp.status_code in (401, 500)

    def test_mastery_profile_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        with TestClient(test_app) as tc:
            resp = tc.get("/test-prep/mastery-profile?course_id=100&assignment_id=1")
        assert resp.status_code in (401, 500)

    def test_create_session_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        with TestClient(test_app) as tc:
            resp = tc.post(
                "/test-prep/sessions",
                json={
                    "course_id": 100,
                    "concepts": ["polynomial long division"],
                },
            )
        assert resp.status_code in (401, 500)

    def test_get_session_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        with TestClient(test_app) as tc:
            resp = tc.get(f"/test-prep/sessions/{uuid4()}")
        assert resp.status_code in (401, 500)

    def test_submit_answer_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        sid = str(uuid4())
        with TestClient(test_app) as tc:
            resp = tc.post(
                f"/test-prep/sessions/{sid}/answer",
                json={
                    "session_id": sid,
                    "problem_id": 1,
                    "student_answer": "42",
                },
            )
        assert resp.status_code in (401, 500)

    def test_skip_phase_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        with TestClient(test_app) as tc:
            resp = tc.post(f"/test-prep/sessions/{uuid4()}/skip-phase")
        assert resp.status_code in (401, 500)

    def test_complete_requires_auth(self) -> None:
        test_app = FastAPI()
        test_app.include_router(router)
        with TestClient(test_app) as tc:
            resp = tc.post(f"/test-prep/sessions/{uuid4()}/complete")
        assert resp.status_code in (401, 500)


# ---------------------------------------------------------------------------
# POST /test-prep/analyze-homework (SSE)
# ---------------------------------------------------------------------------


class TestAnalyzeHomeworkSSE:
    """POST /test-prep/analyze-homework — SSE streaming endpoint."""

    def test_sse_stream(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: MagicMock,
    ) -> None:
        """Returns SSE events with text/event-stream content type."""
        analysis_results = [
            {
                "assignment_id": 1,
                "page_number": 0,
                "per_problem_json": [
                    {
                        "problem_number": 1,
                        "correctness": 1.0,
                        "error_type": None,
                        "concept": "polynomial long division",
                    }
                ],
                "analysis_json": {
                    "overall": "Good",
                    "strengths": ["division"],
                    "areas_for_improvement": [],
                },
            }
        ]

        with patch(
            "mitty.api.routers.test_prep.analyze_homework_set",
            new_callable=AsyncMock,
            return_value=analysis_results,
        ):
            resp = client.post(
                "/test-prep/analyze-homework",
                json={"assignment_id": 1, "course_id": 100},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Parse SSE events from the response body
        lines = resp.text.strip().split("\n")
        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # Should have at least: started, complete
        assert len(events) >= 2
        assert events[0]["status"] == "started"
        assert events[-1]["status"] == "complete"

    def test_sse_error_handling(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: MagicMock,
    ) -> None:
        """SSE emits an error event when analysis fails."""
        with patch(
            "mitty.api.routers.test_prep.analyze_homework_set",
            new_callable=AsyncMock,
            side_effect=RuntimeError("AI down"),
        ):
            resp = client.post(
                "/test-prep/analyze-homework",
                json={"assignment_id": 1, "course_id": 100},
            )

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # Should have started + error events
        statuses = [e["status"] for e in events]
        assert "started" in statuses
        assert "error" in statuses

    def test_sse_ai_unavailable(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Returns 503 when AI client is None."""
        test_app = FastAPI()
        test_app.include_router(router)

        async def _user() -> dict[str, str]:
            return {
                "user_id": USER_ID,
                "email": "student@example.com",
                "access_token": "test-jwt",
            }

        async def _client() -> MagicMock:
            return mock_client

        async def _ai() -> None:
            return None

        test_app.dependency_overrides[get_current_user] = _user
        test_app.dependency_overrides[get_user_client] = _client
        test_app.dependency_overrides[get_ai_client] = _ai

        with TestClient(test_app) as tc:
            resp = tc.post(
                "/test-prep/analyze-homework",
                json={"assignment_id": 1, "course_id": 100},
            )

        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /test-prep/mastery-profile
# ---------------------------------------------------------------------------


class TestMasteryProfile:
    """GET /test-prep/mastery-profile."""

    def test_mastery_profile(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns mastery profiles for the specified course/assignment."""
        from mitty.api.schemas import TestPrepMasteryProfile

        profiles = [
            TestPrepMasteryProfile(
                concept="polynomial long division",
                mastery_level=0.75,
                problems_attempted=4,
                problems_correct=3,
                avg_time_seconds=45.0,
                error_types=["procedural"],
            )
        ]

        with patch(
            "mitty.api.routers.test_prep.build_mastery_profile",
            new_callable=AsyncMock,
            return_value=profiles,
        ):
            resp = client.get(
                "/test-prep/mastery-profile?course_id=100&assignment_id=1"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["concept"] == "polynomial long division"
        assert body[0]["mastery_level"] == 0.75

    def test_mastery_profile_empty(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns empty list when no analyses exist."""
        with patch(
            "mitty.api.routers.test_prep.build_mastery_profile",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                "/test-prep/mastery-profile?course_id=100&assignment_id=1"
            )

        assert resp.status_code == 200
        assert resp.json() == []

    def test_mastery_profile_missing_params(
        self,
        client: TestClient,
    ) -> None:
        """Returns 422 when required query params missing."""
        resp = client.get("/test-prep/mastery-profile")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /test-prep/sessions
# ---------------------------------------------------------------------------


class TestCreateSession:
    """POST /test-prep/sessions."""

    def test_create_session(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Creates a new session and returns it."""
        insert_chain = _chain_mock([SAMPLE_SESSION_ROW])
        mock_client.table = MagicMock(return_value=insert_chain)

        resp = client.post(
            "/test-prep/sessions",
            json={
                "course_id": 100,
                "assessment_id": 5,
                "concepts": ["polynomial long division"],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["user_id"] == USER_ID
        assert body["course_id"] == 100
        assert body["state_json"] is not None

    def test_create_session_requires_concepts(
        self,
        client: TestClient,
    ) -> None:
        """Returns 422 when concepts list is empty."""
        resp = client.post(
            "/test-prep/sessions",
            json={"course_id": 100, "concepts": []},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /test-prep/sessions/{session_id}
# ---------------------------------------------------------------------------


class TestGetSession:
    """GET /test-prep/sessions/{session_id}."""

    def test_get_session(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns session for the authenticated user."""
        session_chain = _chain_mock(SAMPLE_SESSION_ROW, raw=True)
        mock_client.table = MagicMock(return_value=session_chain)

        resp = client.get(f"/test-prep/sessions/{SESSION_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == SESSION_ID
        assert body["course_id"] == 100

    def test_other_user_404(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when session belongs to another user."""
        # The ownership filter .eq("user_id", ...) will return no data
        session_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=session_chain)

        resp = client.get(f"/test-prep/sessions/{uuid4()}")

        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "SESSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/answer
# ---------------------------------------------------------------------------


class TestSubmitAnswer:
    """POST /test-prep/sessions/{session_id}/answer."""

    def test_submit_answer(
        self,
        client: TestClient,
        mock_client: MagicMock,
        mock_ai: MagicMock,
    ) -> None:
        """Submits an answer and gets evaluation result."""
        # Session fetch
        session_chain = _chain_mock(SAMPLE_SESSION_ROW, raw=True)

        # Problem lookup — find the pending problem from test_prep_results
        problem_row = {
            **SAMPLE_RESULT_ROW,
            "student_answer": None,
            "is_correct": None,
        }
        problem_chain = _chain_mock(problem_row, raw=True)

        # Update chain for saving result
        updated_result = {
            **SAMPLE_RESULT_ROW,
            "is_correct": True,
            "score": 1.0,
            "feedback": "Correct!",
        }
        update_chain = _chain_mock([updated_result])

        # Session update chain
        session_update_chain = _chain_mock([SAMPLE_SESSION_ROW])

        call_count = {"n": 0}

        def route_table(name: str) -> MagicMock:
            if name == "test_prep_sessions":
                call_count["n"] += 1
                # First call: fetch session, subsequent: update session
                if call_count["n"] == 1:
                    return session_chain
                return session_update_chain
            # test_prep_results
            call_count["n"] += 1
            if call_count["n"] == 2:
                return problem_chain
            return update_chain

        mock_client.table = MagicMock(side_effect=route_table)

        with patch(
            "mitty.api.routers.test_prep._evaluate_answer",
            new_callable=AsyncMock,
            return_value={
                "is_correct": True,
                "score": 1.0,
                "explanation": "Correct!",
            },
        ):
            resp = client.post(
                f"/test-prep/sessions/{SESSION_ID}/answer",
                json={
                    "session_id": SESSION_ID,
                    "problem_id": 1,
                    "student_answer": "x^2 + 2",
                    "time_spent_seconds": 30,
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_correct"] is True
        assert body["score"] == 1.0

    def test_stale_problem(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 409 when problem was already answered."""
        # Session exists
        session_chain = _chain_mock(SAMPLE_SESSION_ROW, raw=True)

        # Problem already has an answer
        problem_chain = _chain_mock(None, raw=True)

        def route_table(name: str) -> MagicMock:
            if name == "test_prep_sessions":
                return session_chain
            return problem_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.post(
            f"/test-prep/sessions/{SESSION_ID}/answer",
            json={
                "session_id": SESSION_ID,
                "problem_id": 1,
                "student_answer": "x^2 + 2",
            },
        )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "PROBLEM_NOT_FOUND"


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/skip-phase
# ---------------------------------------------------------------------------


class TestSkipPhase:
    """POST /test-prep/sessions/{session_id}/skip-phase."""

    def test_skip_phase(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Advances to the next phase and returns updated session."""
        session_chain = _chain_mock(SAMPLE_SESSION_ROW, raw=True)
        updated_state = {
            **SAMPLE_STATE_JSON,
            "phase": "focused_practice",
        }
        updated_session = {
            **SAMPLE_SESSION_ROW,
            "state_json": updated_state,
            "phase_reached": "focused_practice",
        }
        update_chain = _chain_mock([updated_session])

        call_count = {"n": 0}

        def route_table(name: str) -> MagicMock:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return session_chain
            return update_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.post(f"/test-prep/sessions/{SESSION_ID}/skip-phase")

        assert resp.status_code == 200
        body = resp.json()
        assert body["phase_reached"] == "focused_practice"

    def test_skip_phase_at_final(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 400 when already at the final phase."""
        final_state = {**SAMPLE_STATE_JSON, "phase": "calibration"}
        final_session = {
            **SAMPLE_SESSION_ROW,
            "state_json": final_state,
            "phase_reached": "calibration",
        }
        session_chain = _chain_mock(final_session, raw=True)
        mock_client.table = MagicMock(return_value=session_chain)

        resp = client.post(f"/test-prep/sessions/{SESSION_ID}/skip-phase")

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "FINAL_PHASE"

    def test_skip_phase_session_not_found(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 404 when session does not exist."""
        session_chain = _chain_mock(None, raw=True)
        mock_client.table = MagicMock(return_value=session_chain)

        resp = client.post(f"/test-prep/sessions/{uuid4()}/skip-phase")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /test-prep/sessions/{session_id}/complete
# ---------------------------------------------------------------------------


class TestCompleteSession:
    """POST /test-prep/sessions/{session_id}/complete."""

    def test_complete_session(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Marks session as completed and returns summary."""
        session_chain = _chain_mock(SAMPLE_SESSION_ROW, raw=True)

        completed_session = {
            **SAMPLE_SESSION_ROW,
            "completed_at": "2026-03-14T10:30:00",
            "total_problems": 10,
            "total_correct": 8,
            "duration_seconds": 1800,
        }
        update_chain = _chain_mock([completed_session])

        # Results for summary
        results_chain = _chain_mock([SAMPLE_RESULT_ROW])

        call_count = {"n": 0}

        def route_table(name: str) -> MagicMock:
            call_count["n"] += 1
            if name == "test_prep_sessions":
                if call_count["n"] == 1:
                    return session_chain
                return update_chain
            return results_chain

        mock_client.table = MagicMock(side_effect=route_table)

        resp = client.post(f"/test-prep/sessions/{SESSION_ID}/complete")

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == SESSION_ID
        assert "phase_scores" in body

    def test_complete_already_completed(
        self,
        client: TestClient,
        mock_client: MagicMock,
    ) -> None:
        """Returns 400 when session is already completed."""
        completed_session = {
            **SAMPLE_SESSION_ROW,
            "completed_at": "2026-03-14T10:30:00",
        }
        session_chain = _chain_mock(completed_session, raw=True)
        mock_client.table = MagicMock(return_value=session_chain)

        resp = client.post(f"/test-prep/sessions/{SESSION_ID}/complete")

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "ALREADY_COMPLETED"
