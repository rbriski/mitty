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
        ("Spring Final Exam", "exam"),
        ("Exam 2 - World History", "exam"),
        ("Midterm Exam", "exam"),
        ("Final Exam - Biology", "exam"),
        ("EXAM: Unit 5", "exam"),
        ("Cumulative Exam", "exam"),
        ("Semester Exam", "exam"),
        # midterm
        ("Midterm", "midterm"),
        ("midterm - English 10", "midterm"),
        ("Fall Midterm", "midterm"),
        # final
        ("Final Exam", "exam"),
        ("Final Test", "test"),
        ("Final Assessment", "assessment"),
        ("Spring Final Exam", "exam"),
        # assessment
        ("Unit 3 Assessment", "assessment"),
        ("Chapter Assessment - Photosynthesis", "assessment"),
        ("Formative Assessment 4", "assessment"),
        ("Summative Assessment", "assessment"),
        ("ASSESSMENT: DNA Replication", "assessment"),
        # mixed case
        ("cHaPtEr 4 TeSt", "test"),
        ("QUIZ - UNIT 7", "quiz"),
        ("spring FINAL exam", "exam"),
        # multiple keywords — first match wins
        ("Midterm Exam", "exam"),
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
