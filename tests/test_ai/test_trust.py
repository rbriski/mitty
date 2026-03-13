"""Tests for source trust scoring (mitty.ai.trust)."""

from __future__ import annotations

import pytest

from mitty.ai.trust import (
    DEFAULT_TRUST_SCORE,
    TRUST_SCORES,
    get_trust_disclosure,
    get_trust_score,
    is_sufficient_trust,
)

# ---------------------------------------------------------------------------
# get_trust_score — known types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("resource_type", "expected"),
    [
        ("textbook", 1.0),
        ("canvas_page", 1.0),
        ("canvas_assignment", 0.7),
        ("canvas_quiz", 0.7),
        ("file", 0.7),
        ("discussion", 0.5),
        ("link", 0.3),
        ("student_notes", 0.3),
        ("web_link", 0.3),
    ],
)
def test_known_types_return_correct_score(resource_type: str, expected: float) -> None:
    assert get_trust_score(resource_type) == expected


# ---------------------------------------------------------------------------
# get_trust_score — unknown / edge-case types
# ---------------------------------------------------------------------------


def test_unknown_type_returns_default() -> None:
    assert get_trust_score("something_new") == DEFAULT_TRUST_SCORE


def test_empty_string_returns_default() -> None:
    assert get_trust_score("") == DEFAULT_TRUST_SCORE


# ---------------------------------------------------------------------------
# get_trust_disclosure
# ---------------------------------------------------------------------------


def test_disclosure_none_for_high_trust() -> None:
    assert get_trust_disclosure(1.0) is None
    assert get_trust_disclosure(0.7) is None
    assert get_trust_disclosure(0.5) is None


def test_disclosure_text_for_low_trust() -> None:
    text = get_trust_disclosure(0.3)
    assert text is not None
    assert isinstance(text, str)
    assert len(text) > 0


def test_disclosure_text_for_very_low_trust() -> None:
    text = get_trust_disclosure(0.1)
    assert text is not None
    assert isinstance(text, str)


def test_disclosure_boundary_at_threshold() -> None:
    # Exactly 0.5 should NOT trigger a disclosure.
    assert get_trust_disclosure(0.5) is None
    # Just below 0.5 should trigger one.
    assert get_trust_disclosure(0.49) is not None


# ---------------------------------------------------------------------------
# is_sufficient_trust
# ---------------------------------------------------------------------------


def test_sufficient_trust_default_threshold() -> None:
    assert is_sufficient_trust(1.0) is True
    assert is_sufficient_trust(0.5) is True
    assert is_sufficient_trust(0.3) is False


def test_sufficient_trust_custom_threshold() -> None:
    assert is_sufficient_trust(0.7, threshold=0.7) is True
    assert is_sufficient_trust(0.5, threshold=0.7) is False


def test_sufficient_trust_zero_threshold() -> None:
    assert is_sufficient_trust(0.0, threshold=0.0) is True


# ---------------------------------------------------------------------------
# TRUST_SCORES mapping sanity checks
# ---------------------------------------------------------------------------


def test_all_scores_between_zero_and_one() -> None:
    for resource_type, score in TRUST_SCORES.items():
        assert 0.0 <= score <= 1.0, f"{resource_type} has invalid score {score}"


def test_default_score_between_zero_and_one() -> None:
    assert 0.0 <= DEFAULT_TRUST_SCORE <= 1.0
