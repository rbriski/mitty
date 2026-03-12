"""Tests for mitty.mastery.updater — mastery state updater.

Parametrized tests verifying that update_mastery() correctly computes
weighted moving average mastery, rolling success rate, confidence
calibration, and integrates with the spaced-repetition scheduler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from mitty.mastery.updater import (
    _compute_confidence_self_report,
    _compute_mastery_level,
    _compute_success_rate,
    _result_score,
    update_mastery,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
COURSE_ID = 101
CONCEPT = "quadratic equations"
NOW = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)


def _make_result(
    *,
    score: float | None = None,
    is_correct: bool | None = None,
    confidence_before: float | None = None,
) -> dict:
    """Build a minimal practice result dict."""
    return {
        "score": score,
        "is_correct": is_correct,
        "confidence_before": confidence_before,
    }


def _mock_upsert_client(*, existing_data: list[dict] | None = None) -> AsyncMock:
    """Build a mock AsyncClient supporting select chain and upsert chain.

    Select chain: table().select().eq().eq().eq().maybe_single().execute()
    Upsert chain: table().upsert().execute()

    ``existing_data``: pass a single-element list with the existing row dict,
    or None / empty list for "no existing row". maybe_single() returns a single
    dict (the first element) or None.
    """
    client = AsyncMock()

    select_result = MagicMock()
    # maybe_single returns a single row dict or None, not a list
    select_result.data = existing_data[0] if existing_data else None

    upsert_result = MagicMock()
    upsert_result.data = [
        {
            "id": 1,
            "user_id": str(USER_ID),
            "course_id": COURSE_ID,
            "concept": CONCEPT,
            "mastery_level": 0.5,
            "confidence_self_report": None,
            "last_retrieval_at": NOW.isoformat(),
            "next_review_at": NOW.isoformat(),
            "retrieval_count": 1,
            "success_rate": 1.0,
            "updated_at": NOW.isoformat(),
        }
    ]

    table_mock = MagicMock()

    # Select chain: table().select("*").eq().eq().eq().maybe_single().execute()
    select_builder = MagicMock()
    eq_builder_1 = MagicMock()
    eq_builder_2 = MagicMock()
    eq_builder_3 = MagicMock()
    maybe_single_builder = MagicMock()
    maybe_single_builder.execute = AsyncMock(return_value=select_result)
    eq_builder_3.maybe_single = MagicMock(return_value=maybe_single_builder)
    eq_builder_2.eq = MagicMock(return_value=eq_builder_3)
    eq_builder_1.eq = MagicMock(return_value=eq_builder_2)
    select_builder.eq = MagicMock(return_value=eq_builder_1)
    table_mock.select = MagicMock(return_value=select_builder)

    # Upsert chain: table().upsert().execute()
    upsert_builder = MagicMock()
    upsert_builder.execute = AsyncMock(return_value=upsert_result)
    table_mock.upsert = MagicMock(return_value=upsert_builder)

    client.table = MagicMock(return_value=table_mock)

    return client


# ---------------------------------------------------------------------------
# Unit tests: _result_score
# ---------------------------------------------------------------------------


class TestResultScore:
    """_result_score extracts a 0–1 score from a practice result."""

    def test_uses_score_when_present(self) -> None:
        assert _result_score({"score": 0.75, "is_correct": False}) == 0.75

    def test_uses_is_correct_true_when_score_null(self) -> None:
        assert _result_score({"score": None, "is_correct": True}) == 1.0

    def test_uses_is_correct_false_when_score_null(self) -> None:
        assert _result_score({"score": None, "is_correct": False}) == 0.0

    def test_both_null_defaults_to_zero(self) -> None:
        assert _result_score({"score": None, "is_correct": None}) == 0.0


# ---------------------------------------------------------------------------
# Unit tests: _compute_mastery_level (weighted moving average)
# ---------------------------------------------------------------------------


class TestComputeMasteryLevel:
    """Weighted moving average: recent results weighted more heavily."""

    def test_all_correct_gives_high_mastery(self) -> None:
        scores = [1.0, 1.0, 1.0]
        result = _compute_mastery_level(scores, existing_mastery=0.0)
        assert result > 0.6

    def test_all_incorrect_gives_low_mastery(self) -> None:
        scores = [0.0, 0.0, 0.0]
        result = _compute_mastery_level(scores, existing_mastery=0.5)
        assert result < 0.3

    def test_recent_weighted_more(self) -> None:
        """Most recent score has more weight — improving trend raises mastery."""
        improving = _compute_mastery_level([0.0, 0.5, 1.0], existing_mastery=0.0)
        declining = _compute_mastery_level([1.0, 0.5, 0.0], existing_mastery=0.0)
        assert improving > declining

    def test_partial_credit_proportional(self) -> None:
        """A 0.5 score should produce intermediate mastery."""
        all_half = _compute_mastery_level([0.5, 0.5, 0.5], existing_mastery=0.0)
        assert 0.3 < all_half < 0.7

    def test_blends_with_existing_mastery(self) -> None:
        """New results are blended with existing mastery."""
        fresh = _compute_mastery_level([1.0], existing_mastery=0.0)
        boosted = _compute_mastery_level([1.0], existing_mastery=0.8)
        # Starting from higher existing mastery should give higher result
        assert boosted > fresh


# ---------------------------------------------------------------------------
# Unit tests: _compute_success_rate (rolling window)
# ---------------------------------------------------------------------------


class TestComputeSuccessRate:
    """Rolling success rate over the last 20 attempts."""

    def test_all_correct(self) -> None:
        assert _compute_success_rate([1.0] * 5, existing_rate=None) == 1.0

    def test_all_incorrect(self) -> None:
        assert _compute_success_rate([0.0] * 5, existing_rate=None) == 0.0

    def test_mixed_results(self) -> None:
        scores = [1.0, 0.0, 1.0, 0.0]
        assert _compute_success_rate(scores, existing_rate=None) == pytest.approx(0.5)

    def test_rolling_window_last_20(self) -> None:
        """Only the last 20 scores should matter."""
        # 25 scores: first 5 are 0, last 20 are 1
        scores = [0.0] * 5 + [1.0] * 20
        assert _compute_success_rate(scores, existing_rate=None) == 1.0

    def test_partial_credit_counted(self) -> None:
        """Partial credit scores count proportionally toward success rate."""
        scores = [0.5, 0.5, 0.5, 0.5]
        assert _compute_success_rate(scores, existing_rate=None) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Unit tests: _compute_confidence_self_report
# ---------------------------------------------------------------------------


class TestComputeConfidenceSelfReport:
    """Average of confidence_before ratings, normalized to 0–1."""

    def test_with_ratings(self) -> None:
        results = [
            _make_result(confidence_before=3.0),
            _make_result(confidence_before=5.0),
        ]
        # Average is 4.0; normalized: (4.0 - 1) / (5 - 1) = 0.75
        assert _compute_confidence_self_report(results) == pytest.approx(0.75)

    def test_no_ratings_returns_none(self) -> None:
        results = [
            _make_result(confidence_before=None),
            _make_result(confidence_before=None),
        ]
        assert _compute_confidence_self_report(results) is None

    def test_mixed_ratings_ignores_none(self) -> None:
        results = [
            _make_result(confidence_before=5.0),
            _make_result(confidence_before=None),
            _make_result(confidence_before=3.0),
        ]
        # Average of [5, 3] = 4.0 -> (4-1)/(5-1) = 0.75
        assert _compute_confidence_self_report(results) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Integration: test_correct_answers_increase_mastery
# ---------------------------------------------------------------------------


class TestCorrectAnswersIncreaseMastery:
    @pytest.mark.asyncio
    async def test_correct_answers_increase_mastery(self) -> None:
        """All-correct results should raise mastery level."""
        client = _mock_upsert_client()
        results = [_make_result(score=1.0) for _ in range(3)]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        # Mastery should be above baseline (0.0)
        assert state.mastery_level > 0.5


# ---------------------------------------------------------------------------
# Integration: test_incorrect_answers_decrease_mastery
# ---------------------------------------------------------------------------


class TestIncorrectAnswersDecreaseMastery:
    @pytest.mark.asyncio
    async def test_incorrect_answers_decrease_mastery(self) -> None:
        """All-incorrect results from high existing mastery should lower it."""
        client = _mock_upsert_client(
            existing_data=[
                {
                    "mastery_level": 0.8,
                    "success_rate": 0.9,
                    "retrieval_count": 10,
                    "confidence_self_report": 0.7,
                }
            ]
        )
        results = [_make_result(score=0.0) for _ in range(3)]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert state.mastery_level < 0.8


# ---------------------------------------------------------------------------
# Integration: test_partial_credit_proportional
# ---------------------------------------------------------------------------


class TestPartialCreditProportional:
    @pytest.mark.asyncio
    async def test_partial_credit_proportional(self) -> None:
        """Partial-credit results should yield intermediate mastery."""
        client = _mock_upsert_client()
        results = [_make_result(score=0.5) for _ in range(5)]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert 0.2 < state.mastery_level < 0.8


# ---------------------------------------------------------------------------
# Integration: test_rolling_success_rate_last_20
# ---------------------------------------------------------------------------


class TestRollingSuccessRateLast20:
    @pytest.mark.asyncio
    async def test_rolling_success_rate_last_20(self) -> None:
        """Success rate should reflect most recent results."""
        client = _mock_upsert_client()
        # 3 correct out of 4
        results = [
            _make_result(score=1.0),
            _make_result(score=1.0),
            _make_result(score=0.0),
            _make_result(score=1.0),
        ]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert state.success_rate == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Integration: test_confidence_calibration_gap_positive_overconfident
# ---------------------------------------------------------------------------


class TestConfidenceCalibrationGapPositive:
    @pytest.mark.asyncio
    async def test_confidence_calibration_gap_positive_overconfident(self) -> None:
        """Overconfident: confidence > success_rate -> positive gap."""
        client = _mock_upsert_client()
        # High confidence, low scores
        results = [
            _make_result(score=0.0, confidence_before=5.0),
            _make_result(score=0.0, confidence_before=5.0),
        ]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        # confidence_self_report (1.0) - success_rate (0.0) = positive
        assert state.confidence_self_report is not None
        assert state.success_rate is not None
        gap = state.confidence_self_report - state.success_rate
        assert gap > 0.0


# ---------------------------------------------------------------------------
# Integration: test_confidence_calibration_gap_negative_underconfident
# ---------------------------------------------------------------------------


class TestConfidenceCalibrationGapNegative:
    @pytest.mark.asyncio
    async def test_confidence_calibration_gap_negative_underconfident(self) -> None:
        """Underconfident: confidence < success_rate -> negative gap."""
        client = _mock_upsert_client()
        # Low confidence, high scores
        results = [
            _make_result(score=1.0, confidence_before=1.0),
            _make_result(score=1.0, confidence_before=1.0),
        ]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert state.confidence_self_report is not None
        assert state.success_rate is not None
        gap = state.confidence_self_report - state.success_rate
        assert gap < 0.0


# ---------------------------------------------------------------------------
# Integration: test_retrieval_count_incremented
# ---------------------------------------------------------------------------


class TestRetrievalCountIncremented:
    @pytest.mark.asyncio
    async def test_retrieval_count_incremented(self) -> None:
        """Retrieval count should be incremented by the number of results."""
        existing_count = 5
        client = _mock_upsert_client(
            existing_data=[
                {
                    "mastery_level": 0.5,
                    "success_rate": 0.5,
                    "retrieval_count": existing_count,
                    "confidence_self_report": None,
                }
            ]
        )
        results = [_make_result(score=1.0) for _ in range(3)]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert state.retrieval_count == existing_count + len(results)


# ---------------------------------------------------------------------------
# Integration: test_next_review_recalculated
# ---------------------------------------------------------------------------


class TestNextReviewRecalculated:
    @pytest.mark.asyncio
    async def test_next_review_recalculated(self) -> None:
        """next_review_at should be set to a future datetime via scheduler."""
        client = _mock_upsert_client()
        results = [_make_result(score=1.0)]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert state.next_review_at is not None
        assert state.next_review_at >= datetime.now(UTC)


# ---------------------------------------------------------------------------
# Integration: test_upsert_atomic_on_conflict
# ---------------------------------------------------------------------------


class TestUpsertAtomicOnConflict:
    @pytest.mark.asyncio
    async def test_upsert_atomic_on_conflict(self) -> None:
        """The upsert should use on_conflict for atomic insert-or-update."""
        client = _mock_upsert_client()
        results = [_make_result(score=1.0)]

        await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        # Verify upsert was called with correct on_conflict
        table_mock = client.table.return_value
        table_mock.upsert.assert_called_once()
        call_kwargs = table_mock.upsert.call_args
        # on_conflict should be "user_id,course_id,concept"
        assert call_kwargs.kwargs.get("on_conflict") == "user_id,course_id,concept"


# ---------------------------------------------------------------------------
# Integration: test_handles_null_scores_uses_is_correct
# ---------------------------------------------------------------------------


class TestHandlesNullScoresUsesIsCorrect:
    @pytest.mark.asyncio
    async def test_handles_null_scores_uses_is_correct(self) -> None:
        """When score is None, should fall back to is_correct boolean."""
        client = _mock_upsert_client()
        results = [
            _make_result(score=None, is_correct=True),
            _make_result(score=None, is_correct=False),
            _make_result(score=None, is_correct=True),
        ]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        # 2 correct out of 3
        assert state.success_rate == pytest.approx(2 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Integration: test_last_retrieval_at_set
# ---------------------------------------------------------------------------


class TestLastRetrievalAtSet:
    @pytest.mark.asyncio
    async def test_last_retrieval_at_set(self) -> None:
        """last_retrieval_at should be set to approximately now."""
        client = _mock_upsert_client()
        results = [_make_result(score=1.0)]

        state = await update_mastery(client, USER_ID, COURSE_ID, CONCEPT, results)

        assert state.last_retrieval_at is not None
        delta = abs((state.last_retrieval_at - datetime.now(UTC)).total_seconds())
        assert delta < 60  # within a minute of now
