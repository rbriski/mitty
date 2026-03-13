"""Tests for mitty.mastery.scheduler — SM-2 variant spaced repetition scheduler.

Parametrized tests verifying that calculate_next_review() produces correct
review intervals based on mastery level, success rate, and retrieval count.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mitty.mastery.scheduler import calculate_next_review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test: new concept reviews today
# ---------------------------------------------------------------------------


class TestNewConceptReviewsToday:
    def test_new_concept_reviews_today(self) -> None:
        """A concept with retrieval_count=0 should schedule review for today."""
        result = calculate_next_review(
            mastery_level=0.0,
            success_rate=0.0,
            retrieval_count=0,
            last_retrieval_at=None,
        )
        # Should be very close to now — within the same day
        assert result.tzinfo is not None  # must be timezone-aware
        delta = result - datetime.now(UTC)
        # Review should be scheduled essentially now (within a few seconds)
        assert delta.total_seconds() < 60
        assert delta.total_seconds() >= -60


# ---------------------------------------------------------------------------
# Test: first correct reviews in 1 day
# ---------------------------------------------------------------------------


class TestFirstCorrectReviewsIn1Day:
    def test_first_correct_reviews_in_1_day(self) -> None:
        """After 1st correct retrieval, next review should be ~1 day later."""
        result = calculate_next_review(
            mastery_level=0.5,
            success_rate=1.0,
            retrieval_count=1,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 60


# ---------------------------------------------------------------------------
# Test: second correct reviews in 3 days
# ---------------------------------------------------------------------------


class TestSecondCorrectReviewsIn3Days:
    def test_second_correct_reviews_in_3_days(self) -> None:
        """After 2nd correct retrieval, next review should be ~3 days later."""
        result = calculate_next_review(
            mastery_level=0.6,
            success_rate=1.0,
            retrieval_count=2,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=3)
        assert abs((result - expected).total_seconds()) < 60


# ---------------------------------------------------------------------------
# Test: third correct reviews in 7 days
# ---------------------------------------------------------------------------


class TestThirdCorrectReviewsIn7Days:
    def test_third_correct_reviews_in_7_days(self) -> None:
        """After 3rd correct retrieval, next review should be ~7 days later."""
        result = calculate_next_review(
            mastery_level=0.7,
            success_rate=1.0,
            retrieval_count=3,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 60


# ---------------------------------------------------------------------------
# Test: incorrect answer resets to 1 day
# ---------------------------------------------------------------------------


class TestIncorrectResetsTo1Day:
    def test_incorrect_resets_to_1_day(self) -> None:
        """If success_rate indicates incorrect (< 0.5), interval resets to 1 day."""
        result = calculate_next_review(
            mastery_level=0.6,
            success_rate=0.3,
            retrieval_count=5,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 60

    def test_zero_success_rate_resets_to_1_day(self) -> None:
        """Zero success rate should also reset to 1 day."""
        result = calculate_next_review(
            mastery_level=0.8,
            success_rate=0.0,
            retrieval_count=10,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 60


# ---------------------------------------------------------------------------
# Test: low mastery always daily
# ---------------------------------------------------------------------------


class TestLowMasteryAlwaysDaily:
    def test_low_mastery_always_daily(self) -> None:
        """Mastery < 0.3 should always schedule daily, regardless of count."""
        result = calculate_next_review(
            mastery_level=0.2,
            success_rate=1.0,
            retrieval_count=10,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 60

    def test_mastery_at_boundary_daily(self) -> None:
        """Mastery exactly at 0.29 should still be daily."""
        result = calculate_next_review(
            mastery_level=0.29,
            success_rate=1.0,
            retrieval_count=8,
            last_retrieval_at=NOW,
        )
        expected = NOW + timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 60

    def test_mastery_at_threshold_not_forced_daily(self) -> None:
        """Mastery at exactly 0.3 should NOT be forced to daily."""
        result = calculate_next_review(
            mastery_level=0.3,
            success_rate=1.0,
            retrieval_count=5,
            last_retrieval_at=NOW,
        )
        # With retrieval_count=5 and mastery=0.3, interval should be > 1 day
        delta_days = (result - NOW).total_seconds() / 86400
        assert delta_days > 1.5


# ---------------------------------------------------------------------------
# Test: high mastery + high success -> long interval
# ---------------------------------------------------------------------------


class TestHighMasteryHighSuccessLongInterval:
    def test_high_mastery_high_success_long_interval(self) -> None:
        """High mastery + high success + many retrievals -> interval > 7 days."""
        result = calculate_next_review(
            mastery_level=0.95,
            success_rate=0.95,
            retrieval_count=10,
            last_retrieval_at=NOW,
        )
        delta_days = (result - NOW).total_seconds() / 86400
        assert delta_days > 7

    def test_interval_grows_with_retrieval_count(self) -> None:
        """More retrievals should produce longer intervals (exponential growth)."""
        intervals = []
        for count in [4, 6, 8]:
            result = calculate_next_review(
                mastery_level=0.9,
                success_rate=0.9,
                retrieval_count=count,
                last_retrieval_at=NOW,
            )
            delta_days = (result - NOW).total_seconds() / 86400
            intervals.append(delta_days)
        # Each should be strictly increasing
        assert intervals[0] < intervals[1] < intervals[2]


# ---------------------------------------------------------------------------
# Test: uses UTC dates
# ---------------------------------------------------------------------------


class TestUsesUtcDates:
    def test_uses_utc_dates(self) -> None:
        """Returned datetime should have UTC timezone."""
        result = calculate_next_review(
            mastery_level=0.5,
            success_rate=1.0,
            retrieval_count=1,
            last_retrieval_at=NOW,
        )
        assert result.tzinfo is not None
        assert result.tzinfo == UTC

    def test_new_concept_uses_utc(self) -> None:
        """Even the 'review today' case should return UTC."""
        result = calculate_next_review(
            mastery_level=0.0,
            success_rate=0.0,
            retrieval_count=0,
            last_retrieval_at=None,
        )
        assert result.tzinfo is not None
        assert result.tzinfo == UTC


# ---------------------------------------------------------------------------
# Parametrized: interval progression across mastery levels and counts
# ---------------------------------------------------------------------------


class TestParametrizedIntervalProgression:
    @pytest.mark.parametrize(
        ("mastery_level", "success_rate", "retrieval_count", "min_days", "max_days"),
        [
            # First correct -> 1 day
            (0.5, 1.0, 1, 0.9, 1.1),
            # Second correct -> 3 days
            (0.6, 1.0, 2, 2.9, 3.1),
            # Third correct -> 7 days
            (0.7, 1.0, 3, 6.9, 7.1),
            # Low mastery override -> 1 day
            (0.1, 1.0, 5, 0.9, 1.1),
            # Incorrect -> 1 day
            (0.8, 0.2, 8, 0.9, 1.1),
            # High mastery, many retrievals -> long interval (capped at 180)
            (0.95, 0.95, 10, 7, 180),
        ],
        ids=[
            "first_correct",
            "second_correct",
            "third_correct",
            "low_mastery_override",
            "incorrect_reset",
            "high_mastery_long",
        ],
    )
    def test_interval_within_bounds(
        self,
        mastery_level: float,
        success_rate: float,
        retrieval_count: int,
        min_days: float,
        max_days: float,
    ) -> None:
        result = calculate_next_review(
            mastery_level=mastery_level,
            success_rate=success_rate,
            retrieval_count=retrieval_count,
            last_retrieval_at=NOW,
        )
        delta_days = (result - NOW).total_seconds() / 86400
        assert min_days <= delta_days <= max_days, (
            f"Expected {min_days}-{max_days} days, got {delta_days:.2f}"
        )
