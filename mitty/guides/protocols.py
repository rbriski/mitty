"""Block-type protocol templates for all 6 study block types.

Defines step-by-step protocol templates that drive executable study guides.
Each block type has 4–6 steps with instruction templates, artifact
requirements, and completion criteria.  Pure data — no I/O, no LLM calls.

Public API:
    get_protocol(block_type) -> Protocol

Traces: DEC-004
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Valid value sets
# ---------------------------------------------------------------------------

VALID_STEP_TYPES: set[str] = {
    "instruction",
    "recall_prompt",
    "confidence_check",
    "practice_item",
    "teach_back",
    "misconception_log",
    "goal_commit",
    "review_source",
    "attempt_problem",
}

VALID_ARTIFACT_TYPES: set[str] = {
    "text_response",
    "confidence_rating",
    "practice_answer",
    "explanation",
    "misconception_entry",
    "goal_selection",
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolStep:
    """A single step within a block protocol."""

    step_number: int
    instruction_template: str
    step_type: str
    requires_artifact: bool
    artifact_type: str | None = None
    time_limit_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class CompletionCriteria:
    """Criteria that must be met to mark a block as complete."""

    required_steps: list[int] = field(default_factory=list)
    min_artifacts: int = 0


@dataclass(frozen=True, slots=True)
class Protocol:
    """Full protocol template for a block type."""

    block_type: str
    steps: list[ProtocolStep] = field(default_factory=list)
    completion_criteria: CompletionCriteria = field(default_factory=CompletionCriteria)


# ---------------------------------------------------------------------------
# Protocol definitions
# ---------------------------------------------------------------------------

_PLAN_PROTOCOL = Protocol(
    block_type="plan",
    steps=[
        ProtocolStep(
            step_number=1,
            instruction_template=(
                "Warm-up: Answer 3 closed-book questions on {concept}."
            ),
            step_type="practice_item",
            requires_artifact=True,
            artifact_type="practice_answer",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=2,
            instruction_template=(
                "Rate your confidence (1–5) for each concept you will " "study today."
            ),
            step_type="confidence_check",
            requires_artifact=True,
            artifact_type="confidence_rating",
            time_limit_minutes=1,
        ),
        ProtocolStep(
            step_number=3,
            instruction_template=(
                "Calibration: Compare your confidence ratings to your "
                "warm-up results."
            ),
            step_type="instruction",
            requires_artifact=False,
            time_limit_minutes=1,
        ),
        ProtocolStep(
            step_number=4,
            instruction_template=(
                "Choose 2 success criteria you will commit to for this " "session."
            ),
            step_type="goal_commit",
            requires_artifact=True,
            artifact_type="goal_selection",
            time_limit_minutes=2,
        ),
        ProtocolStep(
            step_number=5,
            instruction_template=(
                "Materials check: List what you need to have open for " "this session."
            ),
            step_type="instruction",
            requires_artifact=False,
            time_limit_minutes=1,
        ),
    ],
    completion_criteria=CompletionCriteria(
        required_steps=[1, 2, 4],
        min_artifacts=3,
    ),
)

_RETRIEVAL_PROTOCOL = Protocol(
    block_type="retrieval",
    steps=[
        ProtocolStep(
            step_number=1,
            instruction_template="Close your notes and all reference materials.",
            step_type="instruction",
            requires_artifact=False,
            time_limit_minutes=0,
        ),
        ProtocolStep(
            step_number=2,
            instruction_template=(
                "Free recall: Write down everything you remember about " "{concept}."
            ),
            step_type="recall_prompt",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=5,
        ),
        ProtocolStep(
            step_number=3,
            instruction_template=(
                "Self-check: Reopen {resource_title} and compare your "
                "recall to the source."
            ),
            step_type="review_source",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=4,
            instruction_template=(
                "Targeted practice: Complete 3–5 practice items on " "{concept}."
            ),
            step_type="practice_item",
            requires_artifact=True,
            artifact_type="practice_answer",
            time_limit_minutes=10,
        ),
        ProtocolStep(
            step_number=5,
            instruction_template=(
                "Summary: Write 2 things you understand better now about " "{concept}."
            ),
            step_type="instruction",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=2,
        ),
    ],
    completion_criteria=CompletionCriteria(
        required_steps=[2, 3, 4],
        min_artifacts=3,
    ),
)

_WORKED_EXAMPLE_PROTOCOL = Protocol(
    block_type="worked_example",
    steps=[
        ProtocolStep(
            step_number=1,
            instruction_template=("Review the worked example from {resource_title}."),
            step_type="review_source",
            requires_artifact=False,
            time_limit_minutes=5,
        ),
        ProtocolStep(
            step_number=2,
            instruction_template=(
                "Identify the pattern or strategy used in the example."
            ),
            step_type="instruction",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=3,
            instruction_template=(
                "Attempt a similar problem to {concept} on your own."
            ),
            step_type="attempt_problem",
            requires_artifact=True,
            artifact_type="practice_answer",
            time_limit_minutes=10,
        ),
        ProtocolStep(
            step_number=4,
            instruction_template=(
                "Check your work against the example in {resource_title}."
            ),
            step_type="review_source",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=5,
            instruction_template=("Practice one more variation of the problem."),
            step_type="attempt_problem",
            requires_artifact=True,
            artifact_type="practice_answer",
            time_limit_minutes=7,
        ),
    ],
    completion_criteria=CompletionCriteria(
        required_steps=[3, 5],
        min_artifacts=3,
    ),
)

_DEEP_EXPLANATION_PROTOCOL = Protocol(
    block_type="deep_explanation",
    steps=[
        ProtocolStep(
            step_number=1,
            instruction_template=(
                "Read the source material on {concept} from " "{resource_title}."
            ),
            step_type="review_source",
            requires_artifact=False,
            time_limit_minutes=7,
        ),
        ProtocolStep(
            step_number=2,
            instruction_template=(
                "Close your notes and summarize {concept} in your own " "words."
            ),
            step_type="recall_prompt",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=5,
        ),
        ProtocolStep(
            step_number=3,
            instruction_template=("Explain why {concept} works the way it does."),
            step_type="instruction",
            requires_artifact=True,
            artifact_type="explanation",
            time_limit_minutes=5,
        ),
        ProtocolStep(
            step_number=4,
            instruction_template=(
                "Compare and contrast {concept} with a related concept."
            ),
            step_type="instruction",
            requires_artifact=True,
            artifact_type="explanation",
            time_limit_minutes=5,
        ),
        ProtocolStep(
            step_number=5,
            instruction_template=(
                "Comprehension check: Answer a question on {concept}."
            ),
            step_type="practice_item",
            requires_artifact=True,
            artifact_type="practice_answer",
            time_limit_minutes=3,
        ),
    ],
    completion_criteria=CompletionCriteria(
        required_steps=[2, 3, 5],
        min_artifacts=3,
    ),
)

_URGENT_DELIVERABLE_PROTOCOL = Protocol(
    block_type="urgent_deliverable",
    steps=[
        ProtocolStep(
            step_number=1,
            instruction_template="Open the assignment link for {concept}.",
            step_type="instruction",
            requires_artifact=False,
            time_limit_minutes=1,
        ),
        ProtocolStep(
            step_number=2,
            instruction_template=(
                "Review the requirements in {resource_title} and note "
                "what is needed."
            ),
            step_type="review_source",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=3,
            instruction_template="Work on the assignment.",
            step_type="attempt_problem",
            requires_artifact=False,
            time_limit_minutes=30,
        ),
        ProtocolStep(
            step_number=4,
            instruction_template=(
                "Self-check: Review your work against the requirements."
            ),
            step_type="instruction",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=5,
            instruction_template="Submit the assignment.",
            step_type="instruction",
            requires_artifact=False,
            time_limit_minutes=1,
        ),
    ],
    completion_criteria=CompletionCriteria(
        required_steps=[2, 3, 4],
        min_artifacts=2,
    ),
)

_REFLECTION_PROTOCOL = Protocol(
    block_type="reflection",
    steps=[
        ProtocolStep(
            step_number=1,
            instruction_template=(
                "Exit ticket: Answer one unassisted question on " "{concept}."
            ),
            step_type="practice_item",
            requires_artifact=True,
            artifact_type="practice_answer",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=2,
            instruction_template=(
                "Teach-back: Explain {concept} as if teaching a friend."
            ),
            step_type="teach_back",
            requires_artifact=True,
            artifact_type="explanation",
            time_limit_minutes=3,
        ),
        ProtocolStep(
            step_number=3,
            instruction_template=(
                "Misconception log: Note any misunderstandings you " "discovered today."
            ),
            step_type="misconception_log",
            requires_artifact=True,
            artifact_type="misconception_entry",
            time_limit_minutes=2,
        ),
        ProtocolStep(
            step_number=4,
            instruction_template=(
                "Rate your confidence (1–5) for each concept you studied."
            ),
            step_type="confidence_check",
            requires_artifact=True,
            artifact_type="confidence_rating",
            time_limit_minutes=1,
        ),
        ProtocolStep(
            step_number=5,
            instruction_template=(
                "Set a review target for tomorrow based on today's " "session."
            ),
            step_type="instruction",
            requires_artifact=True,
            artifact_type="text_response",
            time_limit_minutes=1,
        ),
    ],
    completion_criteria=CompletionCriteria(
        required_steps=[1, 2, 4],
        min_artifacts=4,
    ),
)

# ---------------------------------------------------------------------------
# Dispatch registry
# ---------------------------------------------------------------------------

_PROTOCOL_REGISTRY: dict[str, Protocol] = {
    "plan": _PLAN_PROTOCOL,
    "retrieval": _RETRIEVAL_PROTOCOL,
    "worked_example": _WORKED_EXAMPLE_PROTOCOL,
    "deep_explanation": _DEEP_EXPLANATION_PROTOCOL,
    "urgent_deliverable": _URGENT_DELIVERABLE_PROTOCOL,
    "reflection": _REFLECTION_PROTOCOL,
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_protocol(block_type: str) -> Protocol:
    """Return the protocol template for the given block type.

    Args:
        block_type: One of the 6 supported block types (plan, retrieval,
            worked_example, deep_explanation, urgent_deliverable,
            reflection).

    Returns:
        The :class:`Protocol` for that block type.

    Raises:
        ValueError: If *block_type* is not recognised.
    """
    try:
        return _PROTOCOL_REGISTRY[block_type]
    except KeyError:
        raise ValueError(
            f"Unknown block type {block_type!r}. "
            f"Valid types: {sorted(_PROTOCOL_REGISTRY)}"
        ) from None
