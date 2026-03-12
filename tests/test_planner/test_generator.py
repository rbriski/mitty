"""Tests for mitty.planner.generator — plan generation orchestrator.

Uses a mock Supabase client to verify the full generate_plan() flow
and all error/edge-case paths.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mitty.planner.generator import (
    PlanGenerationError,
    StudyPlan,
    generate_plan,
)

# ---------------------------------------------------------------------------
# Mock Supabase client helpers
# ---------------------------------------------------------------------------


def _mock_response(data: list[dict[str, Any]]) -> MagicMock:
    """Create a mock response object with .data attribute."""
    resp = MagicMock()
    resp.data = data
    return resp


class _QueryChain:
    """Fluent query builder mock that captures chained calls and returns a response."""

    def __init__(self, data: list[dict[str, Any]]) -> None:
        self._data = data

    def select(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def gte(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def in_(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def insert(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def upsert(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    def delete(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return self

    async def execute(self) -> MagicMock:
        return _mock_response(self._data)


class _InsertChain(_QueryChain):
    """Insert chain that captures inserted rows and returns them with an id."""

    def __init__(self, id_start: int = 1) -> None:
        super().__init__([])
        self._id_counter = id_start
        self._inserted: list[dict[str, Any]] = []

    def insert(self, rows: Any, **_kwargs: Any) -> _InsertChain:
        if isinstance(rows, dict):
            rows = [rows]
        self._inserted = rows
        return self

    async def execute(self) -> MagicMock:
        result = []
        for row in self._inserted:
            row_with_id = {**row, "id": self._id_counter}
            result.append(row_with_id)
            self._id_counter += 1
        return _mock_response(result)


def _build_mock_client(
    *,
    signal: list[dict[str, Any]] | None = None,
    assignments: list[dict[str, Any]] | None = None,
    enrollments: list[dict[str, Any]] | None = None,
    submissions: list[dict[str, Any]] | None = None,
    assessments: list[dict[str, Any]] | None = None,
    grade_snapshots: list[dict[str, Any]] | None = None,
    mastery_states: list[dict[str, Any]] | None = None,
    courses: list[dict[str, Any]] | None = None,
    existing_plans: list[dict[str, Any]] | None = None,
    plan_id_start: int = 100,
) -> AsyncMock:
    """Build a mock Supabase client with table routing."""
    client = AsyncMock()

    # Default data.
    if signal is None:
        signal = [_default_signal()]
    if assignments is None:
        assignments = [_default_assignment()]
    if enrollments is None:
        enrollments = [_default_enrollment()]
    if submissions is None:
        submissions = [_default_submission()]
    if assessments is None:
        assessments = []
    if grade_snapshots is None:
        grade_snapshots = []
    if mastery_states is None:
        mastery_states = []
    if courses is None:
        courses = [{"id": 1, "name": "Algebra 2"}]
    if existing_plans is None:
        existing_plans = []

    table_data: dict[str, list[dict[str, Any]]] = {
        "student_signals": signal,
        "assignments": assignments,
        "enrollments": enrollments,
        "submissions": submissions,
        "assessments": assessments,
        "grade_snapshots": grade_snapshots,
        "mastery_states": mastery_states,
        "courses": courses,
        "study_plans": existing_plans,
        "study_blocks": [],
    }

    def _table(name: str) -> Any:
        if name in ("study_plans", "study_blocks"):
            # For writes, return insert chain; for reads (select), return query.
            # We use a hybrid object.
            return _WritableTable(
                read_data=table_data.get(name, []),
                insert_chain=_InsertChain(id_start=plan_id_start),
            )
        return _QueryChain(table_data.get(name, []))

    client.table = _table
    return client


class _WritableTable:
    """Table mock that supports both select-based reads and insert/delete writes."""

    def __init__(
        self,
        read_data: list[dict[str, Any]],
        insert_chain: _InsertChain,
    ) -> None:
        self._read_data = read_data
        self._insert_chain = insert_chain

    def select(self, *_args: Any, **_kwargs: Any) -> _QueryChain:
        return _QueryChain(self._read_data)

    def insert(self, rows: Any, **_kwargs: Any) -> _InsertChain:
        return self._insert_chain.insert(rows)

    def delete(self, **_kwargs: Any) -> _QueryChain:
        return _QueryChain([])

    def eq(self, *_args: Any, **_kwargs: Any) -> _WritableTable:
        return self


# ---------------------------------------------------------------------------
# Default test data factories
# ---------------------------------------------------------------------------

PLAN_DATE = date(2026, 3, 11)
USER_ID = "00000000-0000-0000-0000-000000000001"


def _default_signal() -> dict[str, Any]:
    return {
        "id": 1,
        "user_id": USER_ID,
        "recorded_at": datetime(2026, 3, 11, 6, 0, tzinfo=UTC).isoformat(),
        "available_minutes": 60,
        "confidence_level": 3,
        "energy_level": 3,
        "stress_level": 3,
        "blockers": None,
        "preferences": {"preferred_course_ids": [1]},
        "notes": None,
    }


def _default_assignment() -> dict[str, Any]:
    return {
        "id": 101,
        "course_id": 1,
        "name": "Chapter 5 Homework",
        "due_at": (datetime(2026, 3, 12, 23, 59, tzinfo=UTC).isoformat()),
        "points_possible": 100.0,
        "html_url": None,
        "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
    }


def _default_enrollment() -> dict[str, Any]:
    return {
        "id": 201,
        "course_id": 1,
        "type": "StudentEnrollment",
        "enrollment_state": "active",
        "current_score": 85.0,
        "current_grade": "B",
        "final_score": None,
        "final_grade": None,
        "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
    }


def _default_submission() -> dict[str, Any]:
    return {
        "assignment_id": 101,
        "score": None,
        "grade": None,
        "submitted_at": None,
        "workflow_state": "unsubmitted",
        "late": False,
        "missing": True,
        "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_plan_happy_path() -> None:
    """Full flow with minimal data produces a valid plan."""
    client = _build_mock_client()
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert result.user_id == USER_ID
    assert result.plan_date == PLAN_DATE
    assert result.status == "draft"
    assert result.plan_id >= 1
    assert len(result.blocks) > 0
    assert result.total_minutes > 0
    assert result.total_minutes <= 60  # available_minutes from signal


@pytest.mark.asyncio
async def test_generate_plan_with_assessment() -> None:
    """Plan includes assessment opportunities when assessments exist."""
    assessments = [
        {
            "id": 301,
            "course_id": 1,
            "name": "Chapter 5 Test",
            "assessment_type": "test",
            "scheduled_date": datetime(2026, 3, 13, 10, 0, tzinfo=UTC).isoformat(),
            "weight": None,
            "unit_or_topic": "Chapter 5",
        }
    ]
    client = _build_mock_client(assessments=assessments)
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


@pytest.mark.asyncio
async def test_generate_plan_with_grade_snapshots() -> None:
    """Grade snapshots provide volatility data to scoring."""
    snapshots = [
        {
            "id": 1,
            "course_id": 1,
            "enrollment_id": 201,
            "current_score": 85.0,
            "scraped_at": datetime(2026, 3, 11, tzinfo=UTC).isoformat(),
        },
        {
            "id": 2,
            "course_id": 1,
            "enrollment_id": 201,
            "current_score": 90.0,
            "scraped_at": datetime(2026, 3, 9, tzinfo=UTC).isoformat(),
        },
    ]
    client = _build_mock_client(grade_snapshots=snapshots)
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


# ---------------------------------------------------------------------------
# Tests — signal errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_signal_raises() -> None:
    """Missing student signal raises PlanGenerationError."""
    client = _build_mock_client(signal=[])
    with pytest.raises(PlanGenerationError, match="No student signal found"):
        await generate_plan(client, USER_ID, PLAN_DATE)


# ---------------------------------------------------------------------------
# Tests — critical data errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_assignments_raises() -> None:
    """Empty assignments table raises PlanGenerationError."""
    client = _build_mock_client(assignments=[])
    with pytest.raises(PlanGenerationError, match="No assignments found"):
        await generate_plan(client, USER_ID, PLAN_DATE)


@pytest.mark.asyncio
async def test_no_enrollments_raises() -> None:
    """Empty enrollments table raises PlanGenerationError."""
    client = _build_mock_client(enrollments=[])
    with pytest.raises(PlanGenerationError, match="No enrollments found"):
        await generate_plan(client, USER_ID, PLAN_DATE)


# ---------------------------------------------------------------------------
# Tests — non-critical degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_grade_snapshots_degrades_gracefully() -> None:
    """Plan generates successfully without grade snapshots."""
    client = _build_mock_client(grade_snapshots=[])
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


@pytest.mark.asyncio
async def test_no_mastery_states_degrades_gracefully() -> None:
    """Plan generates successfully without mastery states."""
    client = _build_mock_client(mastery_states=[])
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


@pytest.mark.asyncio
async def test_no_submissions_degrades_gracefully() -> None:
    """Plan generates without submissions — no late/missing flags set."""
    client = _build_mock_client(submissions=[])
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


# ---------------------------------------------------------------------------
# Tests — existing plan conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_plan_raises() -> None:
    """An active plan on the same date raises PlanGenerationError."""
    existing = [{"id": 50, "status": "active"}]
    client = _build_mock_client(existing_plans=existing)
    with pytest.raises(PlanGenerationError, match="status 'active'"):
        await generate_plan(client, USER_ID, PLAN_DATE)


@pytest.mark.asyncio
async def test_completed_plan_raises() -> None:
    """A completed plan on the same date raises PlanGenerationError."""
    existing = [{"id": 51, "status": "completed"}]
    client = _build_mock_client(existing_plans=existing)
    with pytest.raises(PlanGenerationError, match="status 'completed'"):
        await generate_plan(client, USER_ID, PLAN_DATE)


@pytest.mark.asyncio
async def test_draft_plan_is_replaced() -> None:
    """An existing draft plan is deleted and replaced."""
    existing = [{"id": 52, "status": "draft"}]
    client = _build_mock_client(existing_plans=existing)
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    # Should succeed — draft was replaced.
    assert isinstance(result, StudyPlan)
    assert result.status == "draft"


# ---------------------------------------------------------------------------
# Tests — plan structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_blocks_have_plan_bookends() -> None:
    """Generated blocks start with 'plan' and end with 'reflection'."""
    client = _build_mock_client()
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert len(result.blocks) >= 2
    assert result.blocks[0].block_type == "plan"
    assert result.blocks[-1].block_type == "reflection"


@pytest.mark.asyncio
async def test_total_minutes_matches_block_sum() -> None:
    """StudyPlan.total_minutes equals sum of block durations."""
    client = _build_mock_client()
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    block_sum = sum(b.duration_minutes for b in result.blocks)
    assert result.total_minutes == block_sum


@pytest.mark.asyncio
async def test_total_minutes_does_not_exceed_available() -> None:
    """Total minutes never exceeds the student's available time."""
    signal = _default_signal()
    signal["available_minutes"] = 30
    client = _build_mock_client(signal=[signal])
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert result.total_minutes <= 30


# ---------------------------------------------------------------------------
# Tests — multiple courses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_courses() -> None:
    """Plan handles assignments from multiple courses."""
    assignments = [
        _default_assignment(),
        {
            "id": 102,
            "course_id": 2,
            "name": "Essay Draft",
            "due_at": datetime(2026, 3, 13, 23, 59, tzinfo=UTC).isoformat(),
            "points_possible": 50.0,
            "html_url": None,
            "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
        },
    ]
    enrollments = [
        _default_enrollment(),
        {
            "id": 202,
            "course_id": 2,
            "type": "StudentEnrollment",
            "enrollment_state": "active",
            "current_score": 72.0,
            "current_grade": "C-",
            "final_score": None,
            "final_grade": None,
            "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
        },
    ]
    courses = [
        {"id": 1, "name": "Algebra 2"},
        {"id": 2, "name": "English 3"},
    ]
    client = _build_mock_client(
        assignments=assignments,
        enrollments=enrollments,
        courses=courses,
    )
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) >= 2  # at least plan + reflection


# ---------------------------------------------------------------------------
# Tests — mastery data integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_plan_with_mastery_states() -> None:
    """Mastery states are read and factored into opportunity scoring."""
    mastery_states = [
        {
            "id": 1,
            "user_id": USER_ID,
            "course_id": 1,
            "concept": "Quadratic Equations",
            "mastery_level": 0.3,
            "confidence_self_report": 0.8,
            "retrieval_count": 2,
            "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
        },
        {
            "id": 2,
            "user_id": USER_ID,
            "course_id": 1,
            "concept": "Factoring",
            "mastery_level": 0.5,
            "confidence_self_report": 0.6,
            "retrieval_count": 3,
            "updated_at": datetime(2026, 3, 10, tzinfo=UTC).isoformat(),
        },
    ]
    client = _build_mock_client(mastery_states=mastery_states)
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


@pytest.mark.asyncio
async def test_mastery_states_empty_degrades_gracefully() -> None:
    """Plan generates without mastery states — gaps default to 0.0."""
    client = _build_mock_client(mastery_states=[])
    result = await generate_plan(client, USER_ID, PLAN_DATE)

    assert isinstance(result, StudyPlan)
    assert len(result.blocks) > 0


@pytest.mark.asyncio
async def test_mastery_gaps_computed_from_states() -> None:
    """Verify _compute_mastery_gaps produces correct gap values."""
    from mitty.planner.generator import _compute_mastery_gaps

    mastery_states = [
        {
            "course_id": 1,
            "mastery_level": 0.3,
            "confidence_self_report": 0.8,
        },
        {
            "course_id": 1,
            "mastery_level": 0.5,
            "confidence_self_report": 0.6,
        },
        {
            "course_id": 2,
            "mastery_level": 0.9,
            "confidence_self_report": 0.85,
        },
    ]
    gaps = _compute_mastery_gaps(mastery_states)

    # Course 1: avg mastery = 0.4, mastery_gap = 0.6
    #           avg confidence = 0.7, confidence_gap = 0.7 - 0.4 = 0.3
    assert 1 in gaps
    mg1, cg1 = gaps[1]
    assert abs(mg1 - 0.6) < 0.01
    assert abs(cg1 - 0.3) < 0.01

    # Course 2: avg mastery = 0.9, mastery_gap = 0.1
    #           avg confidence = 0.85, confidence_gap = -0.05
    assert 2 in gaps
    mg2, cg2 = gaps[2]
    assert abs(mg2 - 0.1) < 0.01
    assert abs(cg2 - (-0.05)) < 0.01


@pytest.mark.asyncio
async def test_mastery_gaps_empty_states() -> None:
    """Empty mastery states produce empty gaps dict."""
    from mitty.planner.generator import _compute_mastery_gaps

    gaps = _compute_mastery_gaps([])
    assert gaps == {}


@pytest.mark.asyncio
async def test_mastery_gaps_missing_confidence() -> None:
    """Mastery states without confidence_self_report default confidence_gap to 0."""
    from mitty.planner.generator import _compute_mastery_gaps

    mastery_states = [
        {
            "course_id": 1,
            "mastery_level": 0.4,
            "confidence_self_report": None,
        },
    ]
    gaps = _compute_mastery_gaps(mastery_states)
    assert 1 in gaps
    mg, cg = gaps[1]
    assert abs(mg - 0.6) < 0.01
    assert cg == 0.0  # no confidence data
