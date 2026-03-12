"""Tests for assignment assessment classifier."""

from __future__ import annotations

import pytest

from mitty.planner.classify import is_assessment_assignment

# ── Positive cases: should return the matched assessment type ──


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # test
        ("Chapter 4 Test", "test"),
        ("Unit 3 Test", "test"),
        ("test - Chapter 12", "test"),
        ("Biology Test - Cells", "test"),
        ("TEST 2: Ecosystems", "test"),
        ("Unit 8 Test (Retake)", "test"),
        ("Pre-Test: Vocabulary", "test"),
        # quiz
        ("Quiz - Unit 7", "quiz"),
        ("Chapter 5 Quiz", "quiz"),
        ("QUIZ 3", "quiz"),
        ("Pop Quiz - Fractions", "quiz"),
        ("Reading Quiz: Chapter 9", "quiz"),
        ("Quiz 12 - Geometry", "quiz"),
        ("Vocabulary Quiz", "quiz"),
        # exam
        ("Spring Final Exam", "test"),
        ("Exam 2 - World History", "test"),
        ("Midterm Exam", "test"),
        ("Final Exam - Biology", "test"),
        ("EXAM: Unit 5", "test"),
        ("Cumulative Exam", "test"),
        ("Semester Exam", "test"),
        # midterm
        ("Midterm", "test"),
        ("midterm - English 10", "test"),
        ("Fall Midterm", "test"),
        # final
        ("Final Exam", "test"),
        ("Final Test", "test"),
        ("Final Assessment", "test"),
        ("Spring Final Exam", "test"),
        # assessment
        ("Unit 3 Assessment", "test"),
        ("Chapter Assessment - Photosynthesis", "test"),
        ("Formative Assessment 4", "test"),
        ("Summative Assessment", "test"),
        ("ASSESSMENT: DNA Replication", "test"),
        # mixed case
        ("cHaPtEr 4 TeSt", "test"),
        ("QUIZ - UNIT 7", "quiz"),
        ("spring FINAL exam", "test"),
        # multiple keywords — first match wins
        ("Midterm Exam", "test"),
        ("Quiz and Test", "quiz"),
    ],
    ids=lambda val: val if isinstance(val, str) else "",
)
def test_positive_matches(name: str, expected: str) -> None:
    """Assignment names containing assessment keywords return the type."""
    result = is_assessment_assignment(name)
    assert result == expected, f"{name!r} → expected {expected!r}, got {result!r}"


# ── Negative cases: should return None ──


@pytest.mark.parametrize(
    "name",
    [
        # homework / classwork
        "Homework 14.3",
        "HW - Chapter 6",
        "Classwork: Graphing",
        "Lab Report - Density",
        "Worksheet 7.2",
        "Reading Response 3",
        "Discussion Post - Week 4",
        "Project: Solar System Model",
        "Presentation - Civil War",
        "Essay: The Great Gatsby",
        # review / prep (exclusions)
        "Quiz Review - Unit 6",
        "Unit 5 Test Review",
        "Test Prep - Chapter 3",
        "Exam Prep Worksheet",
        "Assessment Review Sheet",
        "Midterm Review Guide",
        "Quiz Prep Activity",
        "Final Exam Review Session",
        "Test Review Game",
        "Exam Review Notes",
        "Midterm Review Packet",
        "Semester Exam Review Copy",
        "Midterm Exam Review",
        "Quiz and Test Prep",
        # practice
        "Practice Quiz",
        "Practice Test - Unit 2",
        "Practice Exam",
        "Practice Assessment",
        # study guide
        "Study Guide - Midterm",
        "Test Study Guide",
        "Exam Study Guide",
        # corrections / retake prep
        "Test Corrections",
        "Quiz Corrections - Unit 3",
        "Exam Corrections",
        # edge cases
        "",
        "   ",
        "12345",
        "Chapter 7 Notes",
        "Final Draft - Research Paper",
        "Final Project Submission",
        "Contest Entry",
        "Protest Essay",
        "Attestation Form",
    ],
    ids=lambda val: val or "empty",
)
def test_negative_matches(name: str) -> None:
    """Non-assessment names or exclusion patterns return None."""
    assert is_assessment_assignment(name) is None, f"{name!r} should be None"


# ── Edge-case tests ──


def test_empty_string() -> None:
    assert is_assessment_assignment("") is None


def test_whitespace_only() -> None:
    assert is_assessment_assignment("   ") is None


def test_returns_string_or_none() -> None:
    """Return type is always str | None."""
    result = is_assessment_assignment("Chapter 4 Test")
    assert isinstance(result, str)

    result = is_assessment_assignment("Homework 14.3")
    assert result is None
