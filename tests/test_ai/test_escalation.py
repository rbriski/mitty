"""Tests for mitty.ai.escalation — heuristic escalation detector.

Covers: repeated failure, avoidance, confidence crash signals,
deduplication, and the check_escalations orchestrator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from mitty.ai.escalation import (
    check_avoidance,
    check_confidence_crash,
    check_escalations,
    check_repeated_failure,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = str(uuid4())
COURSE_ID = 101
CONCEPT = "quadratic equations"


def _mock_response(data: list | dict | None = None) -> MagicMock:
    """Build a mock Supabase execute() response."""
    resp = MagicMock()
    resp.data = data
    resp.count = len(data) if isinstance(data, list) else (1 if data else 0)
    return resp


def _chain_mock(final_response: MagicMock) -> MagicMock:
    """Build a chainable Supabase query builder mock.

    Every attribute access / method call on the chain returns itself,
    except .execute() which returns the final_response wrapped in a coroutine.
    """
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.gt.return_value = chain
    chain.lt.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.is_.return_value = chain
    chain.neq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.insert.return_value = chain
    chain.execute = AsyncMock(return_value=final_response)
    return chain


def _make_client(*table_responses: tuple[str, MagicMock]) -> MagicMock:
    """Build a mock AsyncClient that returns different chains per table name.

    Usage:
        client = _make_client(
            ("practice_results", chain1),
            ("escalation_log", chain2),
        )
    """
    client = MagicMock()
    table_map: dict[str, MagicMock] = {}
    for name, chain in table_responses:
        table_map[name] = chain
    client.table.side_effect = lambda t: table_map.get(
        t, _chain_mock(_mock_response([]))
    )
    return client


# ---------------------------------------------------------------------------
# check_repeated_failure
# ---------------------------------------------------------------------------


class TestRepeatedFailure:
    """Tests for the repeated_failure signal."""

    @pytest.mark.asyncio
    async def test_triggers_when_3_or_more_incorrect(self) -> None:
        """3+ incorrect answers on same concept triggers escalation."""
        results_chain = _chain_mock(_mock_response([{"id": 1}, {"id": 2}, {"id": 3}]))
        client = _make_client(("practice_results", results_chain))

        esc = await check_repeated_failure(client, USER_ID, COURSE_ID, CONCEPT)

        assert esc is not None
        assert esc.signal_type == "repeated_failure"
        assert esc.concept == CONCEPT
        assert esc.context_data["failure_count"] == 3

    @pytest.mark.asyncio
    async def test_no_trigger_when_2_incorrect(self) -> None:
        """2 incorrect answers does not trigger."""
        results_chain = _chain_mock(_mock_response([{"id": 1}, {"id": 2}]))
        client = _make_client(("practice_results", results_chain))

        esc = await check_repeated_failure(client, USER_ID, COURSE_ID, CONCEPT)

        assert esc is None

    @pytest.mark.asyncio
    async def test_boundary_exactly_3(self) -> None:
        """Exactly 3 incorrect triggers (boundary)."""
        results_chain = _chain_mock(_mock_response([{"id": 1}, {"id": 2}, {"id": 3}]))
        client = _make_client(("practice_results", results_chain))

        esc = await check_repeated_failure(
            client, USER_ID, COURSE_ID, CONCEPT, threshold=3
        )

        assert esc is not None
        assert esc.context_data["failure_count"] == 3

    @pytest.mark.asyncio
    async def test_custom_threshold(self) -> None:
        """Custom threshold of 5: 4 incorrect does not trigger."""
        results_chain = _chain_mock(_mock_response([{"id": i} for i in range(4)]))
        client = _make_client(("practice_results", results_chain))

        esc = await check_repeated_failure(
            client, USER_ID, COURSE_ID, CONCEPT, threshold=5
        )

        assert esc is None


# ---------------------------------------------------------------------------
# check_avoidance
# ---------------------------------------------------------------------------


class TestAvoidance:
    """Tests for the avoidance signal."""

    @pytest.mark.asyncio
    async def test_triggers_when_3_days_skipped(self) -> None:
        """3+ consecutive days with no completed blocks triggers escalation."""
        # Return no completed blocks at all in recent days
        blocks_chain = _chain_mock(_mock_response([]))
        plans_chain = _chain_mock(_mock_response([]))
        client = _make_client(
            ("study_blocks", blocks_chain),
            ("study_plans", plans_chain),
        )

        esc = await check_avoidance(client, USER_ID, threshold_days=3)

        assert esc is not None
        assert esc.signal_type == "avoidance"
        assert esc.concept is None

    @pytest.mark.asyncio
    async def test_no_trigger_when_2_days_skipped(self) -> None:
        """2 days skipped does not trigger with threshold=3."""
        # Return a completed block from 2 days ago (within the lookback)
        now = datetime.now(UTC)
        two_days_ago = (now - timedelta(days=2)).isoformat()
        blocks_chain = _chain_mock(_mock_response([{"completed_at": two_days_ago}]))
        plans_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "id": 1,
                        "plan_date": (now - timedelta(days=1)).date().isoformat(),
                    },
                    {
                        "id": 2,
                        "plan_date": (now - timedelta(days=2)).date().isoformat(),
                    },
                ]
            )
        )
        client = _make_client(
            ("study_blocks", blocks_chain),
            ("study_plans", plans_chain),
        )

        esc = await check_avoidance(client, USER_ID, threshold_days=3)

        assert esc is None

    @pytest.mark.asyncio
    async def test_suggested_action_text(self) -> None:
        """Avoidance escalation has the correct suggested action."""
        blocks_chain = _chain_mock(_mock_response([]))
        plans_chain = _chain_mock(_mock_response([]))
        client = _make_client(
            ("study_blocks", blocks_chain),
            ("study_plans", plans_chain),
        )

        esc = await check_avoidance(client, USER_ID, threshold_days=3)

        assert esc is not None
        assert "haven't studied" in esc.suggested_action


# ---------------------------------------------------------------------------
# check_confidence_crash
# ---------------------------------------------------------------------------


class TestConfidenceCrash:
    """Tests for the confidence_crash signal."""

    @pytest.mark.asyncio
    async def test_triggers_on_large_drop(self) -> None:
        """Drop of 0.4 (> 0.3 threshold) triggers escalation."""
        # Two mastery snapshots: previous confidence 0.8, current 0.4
        mastery_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "confidence_self_report": 0.4,
                        "updated_at": "2025-01-02T00:00:00",
                    },
                    {
                        "confidence_self_report": 0.8,
                        "updated_at": "2025-01-01T00:00:00",
                    },
                ]
            )
        )
        client = _make_client(("mastery_states", mastery_chain))

        esc = await check_confidence_crash(client, USER_ID, COURSE_ID, CONCEPT)

        assert esc is not None
        assert esc.signal_type == "confidence_crash"
        assert esc.context_data["drop"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_no_trigger_on_small_drop(self) -> None:
        """Drop of 0.2 (< 0.3 threshold) does not trigger."""
        mastery_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "confidence_self_report": 0.6,
                        "updated_at": "2025-01-02T00:00:00",
                    },
                    {
                        "confidence_self_report": 0.8,
                        "updated_at": "2025-01-01T00:00:00",
                    },
                ]
            )
        )
        client = _make_client(("mastery_states", mastery_chain))

        esc = await check_confidence_crash(client, USER_ID, COURSE_ID, CONCEPT)

        assert esc is None

    @pytest.mark.asyncio
    async def test_no_trigger_when_only_one_record(self) -> None:
        """Only one mastery record means no comparison possible."""
        mastery_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "confidence_self_report": 0.5,
                        "updated_at": "2025-01-01T00:00:00",
                    },
                ]
            )
        )
        client = _make_client(("mastery_states", mastery_chain))

        esc = await check_confidence_crash(client, USER_ID, COURSE_ID, CONCEPT)

        assert esc is None

    @pytest.mark.asyncio
    async def test_no_trigger_when_confidence_increases(self) -> None:
        """Confidence going up is not a crash."""
        mastery_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "confidence_self_report": 0.9,
                        "updated_at": "2025-01-02T00:00:00",
                    },
                    {
                        "confidence_self_report": 0.5,
                        "updated_at": "2025-01-01T00:00:00",
                    },
                ]
            )
        )
        client = _make_client(("mastery_states", mastery_chain))

        esc = await check_confidence_crash(client, USER_ID, COURSE_ID, CONCEPT)

        assert esc is None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Tests for 24h deduplication in check_escalations."""

    @pytest.mark.asyncio
    async def test_skips_duplicate_within_24h(self) -> None:
        """Same signal+concept within 24h should not create a new escalation."""
        # repeated_failure triggers (3 results)
        results_chain = _chain_mock(_mock_response([{"id": 1}, {"id": 2}, {"id": 3}]))
        # confidence_crash: only 1 record so no trigger
        mastery_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "confidence_self_report": 0.5,
                        "updated_at": "2025-01-01T00:00:00",
                    },
                ]
            )
        )
        # avoidance: has recent completed blocks so no trigger
        blocks_chain = _chain_mock(
            _mock_response([{"completed_at": datetime.now(UTC).isoformat()}])
        )
        plans_chain = _chain_mock(
            _mock_response(
                [
                    {"id": 1, "plan_date": datetime.now(UTC).date().isoformat()},
                ]
            )
        )
        # Dedup check: existing escalation within 24h
        dedup_chain = _chain_mock(
            _mock_response([{"id": 99, "signal_type": "repeated_failure"}])
        )
        insert_chain = _chain_mock(_mock_response([{"id": 100}]))

        client = MagicMock()
        call_count = {"escalation_log": 0}

        def table_router(name: str) -> MagicMock:
            if name == "practice_results":
                return results_chain
            if name == "mastery_states":
                return mastery_chain
            if name == "study_blocks":
                return blocks_chain
            if name == "study_plans":
                return plans_chain
            if name == "escalation_log":
                call_count["escalation_log"] += 1
                # First call is dedup check (select), return existing
                if call_count["escalation_log"] == 1:
                    return dedup_chain
                return insert_chain
            return _chain_mock(_mock_response([]))

        client.table.side_effect = table_router

        escalations = await check_escalations(
            client, USER_ID, COURSE_ID, concept=CONCEPT
        )

        # Should be empty because dedup filtered it out
        assert len(escalations) == 0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestCheckEscalations:
    """Tests for the check_escalations orchestrator."""

    @pytest.mark.asyncio
    async def test_runs_all_signals(self) -> None:
        """Orchestrator runs all 3 signals and returns triggered ones."""
        # repeated_failure: triggers (3 results)
        results_chain = _chain_mock(_mock_response([{"id": 1}, {"id": 2}, {"id": 3}]))
        # confidence_crash: triggers (big drop)
        mastery_chain = _chain_mock(
            _mock_response(
                [
                    {
                        "confidence_self_report": 0.2,
                        "updated_at": "2025-01-02T00:00:00",
                    },
                    {
                        "confidence_self_report": 0.8,
                        "updated_at": "2025-01-01T00:00:00",
                    },
                ]
            )
        )
        # avoidance: triggers (no blocks)
        blocks_chain = _chain_mock(_mock_response([]))
        plans_chain = _chain_mock(_mock_response([]))
        # Dedup: no existing escalations
        dedup_chain = _chain_mock(_mock_response([]))
        insert_chain = _chain_mock(_mock_response([{"id": 1}]))

        client = MagicMock()
        escalation_call = {"count": 0}

        def table_router(name: str) -> MagicMock:
            if name == "practice_results":
                return results_chain
            if name == "mastery_states":
                return mastery_chain
            if name == "study_blocks":
                return blocks_chain
            if name == "study_plans":
                return plans_chain
            if name == "escalation_log":
                escalation_call["count"] += 1
                # Odd calls are dedup checks (select), even are inserts
                if escalation_call["count"] % 2 == 1:
                    return dedup_chain
                return insert_chain
            return _chain_mock(_mock_response([]))

        client.table.side_effect = table_router

        escalations = await check_escalations(
            client, USER_ID, COURSE_ID, concept=CONCEPT
        )

        signal_types = {e.signal_type for e in escalations}
        assert "repeated_failure" in signal_types
        assert "avoidance" in signal_types
        assert "confidence_crash" in signal_types
        assert len(escalations) == 3

    @pytest.mark.asyncio
    async def test_writes_to_escalation_log(self) -> None:
        """New escalations are written to the escalation_log table."""
        # Only repeated_failure triggers
        results_chain = _chain_mock(_mock_response([{"id": 1}, {"id": 2}, {"id": 3}]))
        # confidence: no data
        mastery_chain = _chain_mock(_mock_response([]))
        # avoidance: has recent blocks
        blocks_chain = _chain_mock(
            _mock_response([{"completed_at": datetime.now(UTC).isoformat()}])
        )
        plans_chain = _chain_mock(
            _mock_response(
                [
                    {"id": 1, "plan_date": datetime.now(UTC).date().isoformat()},
                ]
            )
        )
        # Dedup: nothing existing
        dedup_chain = _chain_mock(_mock_response([]))

        client = MagicMock()
        inserted_rows: list[dict] = []
        escalation_call = {"count": 0}

        def table_router(name: str) -> MagicMock:
            if name == "practice_results":
                return results_chain
            if name == "mastery_states":
                return mastery_chain
            if name == "study_blocks":
                return blocks_chain
            if name == "study_plans":
                return plans_chain
            if name == "escalation_log":
                escalation_call["count"] += 1
                if escalation_call["count"] % 2 == 1:
                    return dedup_chain
                # Capture inserted data
                chain = _chain_mock(_mock_response([{"id": 42}]))
                original_insert = chain.insert

                def capture_insert(row: dict) -> MagicMock:
                    inserted_rows.append(row)
                    return original_insert(row)

                chain.insert = capture_insert
                return chain
            return _chain_mock(_mock_response([]))

        client.table.side_effect = table_router

        escalations = await check_escalations(
            client, USER_ID, COURSE_ID, concept=CONCEPT
        )

        assert len(escalations) == 1
        assert escalations[0].signal_type == "repeated_failure"
        # Verify insert was called (at least the escalation_log table was accessed)
        assert escalation_call["count"] >= 2  # dedup check + insert

    @pytest.mark.asyncio
    async def test_no_concept_skips_concept_signals(self) -> None:
        """When concept is None, only avoidance runs."""
        # avoidance triggers
        blocks_chain = _chain_mock(_mock_response([]))
        plans_chain = _chain_mock(_mock_response([]))
        dedup_chain = _chain_mock(_mock_response([]))
        insert_chain = _chain_mock(_mock_response([{"id": 1}]))

        client = MagicMock()
        escalation_call = {"count": 0}

        def table_router(name: str) -> MagicMock:
            if name == "study_blocks":
                return blocks_chain
            if name == "study_plans":
                return plans_chain
            if name == "escalation_log":
                escalation_call["count"] += 1
                if escalation_call["count"] % 2 == 1:
                    return dedup_chain
                return insert_chain
            return _chain_mock(_mock_response([]))

        client.table.side_effect = table_router

        escalations = await check_escalations(client, USER_ID, COURSE_ID, concept=None)

        assert len(escalations) == 1
        assert escalations[0].signal_type == "avoidance"
