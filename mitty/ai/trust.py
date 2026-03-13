"""Deterministic trust scoring for resource types.

Each resource type is mapped to a trust score between 0.0 and 1.0 that
reflects the reliability of content from that source.  The scores are
used to decide whether a disclosure should be shown to the user and
whether a source meets a minimum quality bar.
"""

from __future__ import annotations

# -- Trust score lookup ---------------------------------------------------- #

TRUST_SCORES: dict[str, float] = {
    # Verified / authoritative content
    "textbook": 1.0,
    "canvas_page": 1.0,
    # Instructor-authored Canvas items
    "canvas_assignment": 0.7,
    "canvas_quiz": 0.7,
    "file": 0.7,
    # Moderate trust — could be instructor or peer content
    "discussion": 0.5,
    # Low trust — external or student-authored
    "link": 0.3,
    "student_notes": 0.3,
    "web_link": 0.3,
}

DEFAULT_TRUST_SCORE: float = 0.5


def get_trust_score(resource_type: str) -> float:
    """Return the trust score for *resource_type*.

    Unknown types receive :data:`DEFAULT_TRUST_SCORE`.
    """
    return TRUST_SCORES.get(resource_type, DEFAULT_TRUST_SCORE)


def get_trust_disclosure(trust_score: float) -> str | None:
    """Return a human-readable disclosure for low-trust sources.

    Returns ``None`` when the score is at or above 0.5, meaning no
    disclosure is necessary.
    """
    if trust_score >= 0.5:
        return None
    return (
        "Based on a lower-confidence source which may be incomplete "
        "or contain errors. Verify important details independently."
    )


def is_sufficient_trust(trust_score: float, *, threshold: float = 0.5) -> bool:
    """Return whether *trust_score* meets the minimum *threshold*."""
    return trust_score >= threshold
