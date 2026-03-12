"""Heuristic classifier for Canvas assignment names.

Classifies assignments as academic assessments (test, quiz, exam, midterm,
final, assessment) based on keyword matching in the assignment name, with
exclusion patterns for false positives like "Quiz Review" or "Test Prep."
"""

from __future__ import annotations

import re

# Keywords that indicate an assessment, ordered by specificity.
# "final" alone is too ambiguous ("Final Draft", "Final Project"), so it
# is not included — it only matches when paired with exam/test/assessment
# via the main pattern below.
_ASSESSMENT_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bexam\b", re.IGNORECASE), "exam"),
    (re.compile(r"\bquiz\b", re.IGNORECASE), "quiz"),
    (re.compile(r"\btest\b", re.IGNORECASE), "test"),
    (re.compile(r"\bmidterm\b", re.IGNORECASE), "midterm"),
    (re.compile(r"\bassessment\b", re.IGNORECASE), "assessment"),
]

# Exclusion patterns — if any of these appear alongside a keyword the
# assignment is likely a review/prep activity, not an actual assessment.
_EXCLUSION_PATTERN = re.compile(
    r"\b(review|prep|practice|study\s+guide|corrections)\b",
    re.IGNORECASE,
)


def is_assessment_assignment(name: str) -> str | None:
    """Determine whether a Canvas assignment name indicates an assessment.

    Uses case-insensitive word-boundary regex to detect keywords:
    'test', 'exam', 'quiz', 'midterm', 'assessment'.  Names that also
    contain exclusion terms ('review', 'prep', 'practice', 'study guide',
    'corrections') are rejected as non-assessments.

    Args:
        name: The assignment name to classify.

    Returns:
        The matched assessment type (e.g. ``"test"``, ``"quiz"``) or
        ``None`` if the name is not an assessment.
    """
    stripped = name.strip()
    if not stripped:
        return None

    # Check exclusions first — fast path out for review/prep items.
    if _EXCLUSION_PATTERN.search(stripped):
        return None

    # Return the first matching keyword type.
    for pattern, assessment_type in _ASSESSMENT_KEYWORDS:
        if pattern.search(stripped):
            return assessment_type

    return None
