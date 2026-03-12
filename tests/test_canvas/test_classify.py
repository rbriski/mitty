"""Tests for mitty.canvas.classify — heuristic event classifier."""

from __future__ import annotations

import pytest

from mitty.canvas.classify import is_assessment_event


class TestClassifyEventMatchesTestKeywords:
    """is_assessment_event returns True for assessment-like titles."""

    @pytest.mark.parametrize(
        "title",
        [
            "Chapter 5 Quiz",
            "Midterm Exam: AP English",
            "Final Exam Review",
            "Unit 3 Test",
            "QUIZ on vocabulary",
            "midterm review session",
            "Final Project Exam",
            "Math test tomorrow",
        ],
    )
    def test_matches_assessment_keywords(self, title: str) -> None:
        assert is_assessment_event(title) is True


class TestClassifyEventIgnoresNonAcademic:
    """is_assessment_event returns False for non-assessment titles."""

    @pytest.mark.parametrize(
        "title",
        [
            "Spring Break — No School",
            "Study Group Session",
            "Parent-Teacher Conference",
            "Field Trip to Museum",
            "Homecoming Dance",
            "testing framework setup",  # 'testing' != 'test' (word boundary)
            "",
        ],
    )
    def test_rejects_non_assessment_titles(self, title: str) -> None:
        assert is_assessment_event(title) is False
