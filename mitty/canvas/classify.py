"""Heuristic classifier for Canvas calendar events.

Classifies calendar events as academic assessments based on keyword
matching in the event title. Events whose title contains keywords like
'test', 'exam', 'quiz', 'midterm', or 'final' are classified as
assessment-worthy.
"""

from __future__ import annotations

import re

# Case-insensitive pattern matching assessment-related keywords.
_ASSESSMENT_PATTERN = re.compile(
    r"\b(test|exam|quiz|midterm|final)\b",
    re.IGNORECASE,
)


def is_assessment_event(title: str) -> bool:
    """Return True if the event title matches assessment keywords.

    Uses a case-insensitive word-boundary regex to detect keywords:
    'test', 'exam', 'quiz', 'midterm', 'final'.

    Args:
        title: The calendar event title to classify.

    Returns:
        True if the title contains at least one assessment keyword.
    """
    return bool(_ASSESSMENT_PATTERN.search(title))
