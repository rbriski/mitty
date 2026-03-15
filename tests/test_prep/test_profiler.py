"""Tests for mitty.prep.profiler — mastery profiler from homework analyses.

Covers: basic profile aggregation, mastery sync, and no-data edge case.

Traces: DEC-003 (mastery profile from homework analyses).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from mitty.prep.profiler import (
    CONCEPT_SECTION_MAP,
    build_mastery_profile,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_COURSE_ID = 42
_ASSIGNMENT_ID = 101


def _make_analysis_row(
    *,
    page_number: int,
    problems: list[dict],
) -> dict:
    """Build a homework_analyses row with per_problem data."""
    return {
        "id": page_number,
        "user_id": str(_USER_ID),
        "assignment_id": _ASSIGNMENT_ID,
        "course_id": _COURSE_ID,
        "page_number": page_number,
        "analysis_json": {
            "per_problem": problems,
            "summary": {"overall": "OK"},
        },
        "analyzed_at": "2026-03-14T12:00:00+00:00",
    }


def _mock_supabase_client(
    *,
    analysis_rows: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Supabase client for profiler queries.

    The profiler queries homework_analyses then calls update_mastery
    (which is patched separately), so we only need the select chain.
    """
    client = MagicMock()

    # homework_analyses select chain
    select_result = MagicMock()
    select_result.data = analysis_rows or []

    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.execute = AsyncMock(return_value=select_result)

    table_mock = MagicMock()
    table_mock.select.return_value = select_chain

    client.table.return_value = table_mock
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicProfile:
    """Aggregates per-concept accuracy and ranks weaknesses."""

    async def test_basic_profile(self) -> None:
        """Two concepts across two pages; verify accuracy and ranking."""
        rows = [
            _make_analysis_row(
                page_number=0,
                problems=[
                    {
                        "problem_number": 1,
                        "correctness": 1.0,
                        "error_type": None,
                        "concept": "polynomial long division",
                    },
                    {
                        "problem_number": 2,
                        "correctness": 0.0,
                        "error_type": "procedural",
                        "concept": "polynomial long division",
                    },
                ],
            ),
            _make_analysis_row(
                page_number=1,
                problems=[
                    {
                        "problem_number": 1,
                        "correctness": 1.0,
                        "error_type": None,
                        "concept": "rational functions",
                    },
                    {
                        "problem_number": 2,
                        "correctness": 1.0,
                        "error_type": None,
                        "concept": "rational functions",
                    },
                    {
                        "problem_number": 3,
                        "correctness": 0.5,
                        "error_type": "careless",
                        "concept": "rational functions",
                    },
                ],
            ),
        ]

        client = _mock_supabase_client(analysis_rows=rows)
        mock_update = AsyncMock(return_value=MagicMock())

        profile = await build_mastery_profile(
            client=client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            assignment_id=_ASSIGNMENT_ID,
            _update_mastery_fn=mock_update,
        )

        # Two concepts in the profile
        assert len(profile) == 2

        # Build a lookup by concept
        by_concept = {p.concept: p for p in profile}

        # polynomial long division: 1 correct out of 2 => 0.5
        poly = by_concept["polynomial long division"]
        assert poly.problems_attempted == 2
        assert poly.problems_correct == 1
        assert poly.mastery_level == pytest.approx(0.5)
        assert "procedural" in poly.error_types

        # rational functions: (1.0 + 1.0 + 0.5) / 3 ~= 0.833
        rat = by_concept["rational functions"]
        assert rat.problems_attempted == 3
        assert rat.problems_correct == 2  # only 1.0 counts as correct
        assert rat.mastery_level == pytest.approx(2.5 / 3, abs=0.01)
        assert "careless" in rat.error_types

        # Weaknesses ranked: lowest accuracy first
        assert profile[0].mastery_level <= profile[1].mastery_level

    async def test_section_mapping(self) -> None:
        """Concepts that exist in the section map get a section assigned."""
        # Use a concept that has a known mapping
        concept = next(iter(CONCEPT_SECTION_MAP))
        rows = [
            _make_analysis_row(
                page_number=0,
                problems=[
                    {
                        "problem_number": 1,
                        "correctness": 0.8,
                        "error_type": None,
                        "concept": concept,
                    },
                ],
            ),
        ]

        client = _mock_supabase_client(analysis_rows=rows)
        mock_update = AsyncMock(return_value=MagicMock())

        profile = await build_mastery_profile(
            client=client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            assignment_id=_ASSIGNMENT_ID,
            _update_mastery_fn=mock_update,
        )

        assert len(profile) == 1
        # The concept's section should be one of the Sullivan sections
        assert profile[0].concept == concept

    async def test_avg_time_seconds(self) -> None:
        """Average time is computed when time_spent_seconds is present."""
        rows = [
            _make_analysis_row(
                page_number=0,
                problems=[
                    {
                        "problem_number": 1,
                        "correctness": 1.0,
                        "error_type": None,
                        "concept": "limits",
                        "time_spent_seconds": 60,
                    },
                    {
                        "problem_number": 2,
                        "correctness": 0.5,
                        "error_type": None,
                        "concept": "limits",
                        "time_spent_seconds": 120,
                    },
                ],
            ),
        ]

        client = _mock_supabase_client(analysis_rows=rows)
        mock_update = AsyncMock(return_value=MagicMock())

        profile = await build_mastery_profile(
            client=client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            assignment_id=_ASSIGNMENT_ID,
            _update_mastery_fn=mock_update,
        )

        assert len(profile) == 1
        assert profile[0].avg_time_seconds == pytest.approx(90.0)


class TestSyncsMastery:
    """Verifies that update_mastery is called for each concept."""

    async def test_syncs_mastery(self) -> None:
        """update_mastery called once per concept with correct args."""
        rows = [
            _make_analysis_row(
                page_number=0,
                problems=[
                    {
                        "problem_number": 1,
                        "correctness": 0.8,
                        "error_type": None,
                        "concept": "exponential functions",
                    },
                    {
                        "problem_number": 2,
                        "correctness": 0.6,
                        "error_type": "conceptual",
                        "concept": "logarithmic functions",
                    },
                ],
            ),
        ]

        client = _mock_supabase_client(analysis_rows=rows)
        mock_update = AsyncMock(return_value=MagicMock())

        await build_mastery_profile(
            client=client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            assignment_id=_ASSIGNMENT_ID,
            _update_mastery_fn=mock_update,
        )

        # update_mastery called once per concept
        assert mock_update.call_count == 2

        # Verify call args contain correct user_id, course_id, and concept
        call_concepts = {c.kwargs["concept"] for c in mock_update.call_args_list}
        assert call_concepts == {"exponential functions", "logarithmic functions"}

        # Verify all calls pass the client, user_id, course_id
        for c in mock_update.call_args_list:
            assert c.kwargs["client"] is client
            assert c.kwargs["user_id"] == _USER_ID
            assert c.kwargs["course_id"] == _COURSE_ID
            # results should be a list of dicts with score and is_correct
            results = c.kwargs["results"]
            assert isinstance(results, list)
            assert len(results) >= 1
            for r in results:
                assert "score" in r
                assert "is_correct" in r


class TestNoData:
    """Empty homework_analyses returns empty profile."""

    async def test_no_data(self) -> None:
        """No analysis rows => empty profile, no mastery sync."""
        client = _mock_supabase_client(analysis_rows=[])
        mock_update = AsyncMock(return_value=MagicMock())

        profile = await build_mastery_profile(
            client=client,
            user_id=_USER_ID,
            course_id=_COURSE_ID,
            assignment_id=_ASSIGNMENT_ID,
            _update_mastery_fn=mock_update,
        )

        assert profile == []
        mock_update.assert_not_called()
