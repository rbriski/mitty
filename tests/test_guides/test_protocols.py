"""Tests for mitty.guides.protocols — block-type protocol templates."""

from __future__ import annotations

import pytest

from mitty.guides.protocols import (
    VALID_ARTIFACT_TYPES,
    VALID_STEP_TYPES,
    CompletionCriteria,
    Protocol,
    ProtocolStep,
    get_protocol,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_BLOCK_TYPES: set[str] = {
    "plan",
    "retrieval",
    "worked_example",
    "deep_explanation",
    "urgent_deliverable",
    "reflection",
}


# ---------------------------------------------------------------------------
# Parametrized: all 6 block types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block_type", sorted(ALL_BLOCK_TYPES))
class TestGetProtocolAllTypes:
    def test_get_protocol_returns_for_all_6_types(self, block_type: str) -> None:
        """get_protocol returns a Protocol for every valid block type."""
        protocol = get_protocol(block_type)
        assert isinstance(protocol, Protocol)
        assert protocol.block_type == block_type

    def test_protocol_step_count_within_bounds(self, block_type: str) -> None:
        """Each protocol has between 4 and 6 steps."""
        protocol = get_protocol(block_type)
        step_count = len(protocol.steps)
        assert (
            4 <= step_count <= 6
        ), f"{block_type}: expected 4-6 steps, got {step_count}"

    def test_protocol_step_types_are_valid(self, block_type: str) -> None:
        """Every step_type value belongs to VALID_STEP_TYPES."""
        protocol = get_protocol(block_type)
        for step in protocol.steps:
            assert step.step_type in VALID_STEP_TYPES, (
                f"{block_type} step {step.step_number}: "
                f"invalid step_type {step.step_type!r}"
            )

    def test_protocol_artifact_types_are_valid(self, block_type: str) -> None:
        """Every non-None artifact_type belongs to VALID_ARTIFACT_TYPES."""
        protocol = get_protocol(block_type)
        for step in protocol.steps:
            if step.artifact_type is not None:
                assert step.artifact_type in VALID_ARTIFACT_TYPES, (
                    f"{block_type} step {step.step_number}: "
                    f"invalid artifact_type {step.artifact_type!r}"
                )

    def test_completion_criteria_required_steps_exist(self, block_type: str) -> None:
        """All required_steps in completion_criteria reference real steps."""
        protocol = get_protocol(block_type)
        step_numbers = {s.step_number for s in protocol.steps}
        for required in protocol.completion_criteria.required_steps:
            assert required in step_numbers, (
                f"{block_type}: required step {required} not found "
                f"in actual steps {sorted(step_numbers)}"
            )


# ---------------------------------------------------------------------------
# Plan protocol specifics
# ---------------------------------------------------------------------------


class TestPlanProtocol:
    def test_plan_protocol_has_warmup_and_goal_commit(self) -> None:
        """Plan protocol contains a practice_item (warm-up) and a
        goal_commit step."""
        protocol = get_protocol("plan")
        step_types = {s.step_type for s in protocol.steps}
        assert (
            "practice_item" in step_types
        ), "Plan protocol must have a warm-up (practice_item) step"
        assert "goal_commit" in step_types, "Plan protocol must have a goal_commit step"

    def test_plan_warmup_is_first_step(self) -> None:
        """The warm-up practice_item should be step 1."""
        protocol = get_protocol("plan")
        assert protocol.steps[0].step_type == "practice_item"
        assert protocol.steps[0].step_number == 1

    def test_plan_has_confidence_check(self) -> None:
        """Plan protocol includes a confidence check."""
        protocol = get_protocol("plan")
        step_types = [s.step_type for s in protocol.steps]
        assert "confidence_check" in step_types


# ---------------------------------------------------------------------------
# Reflection protocol specifics
# ---------------------------------------------------------------------------


class TestReflectionProtocol:
    def test_reflection_protocol_has_exit_ticket_and_teachback(
        self,
    ) -> None:
        """Reflection protocol contains a practice_item (exit ticket) and
        a teach_back step."""
        protocol = get_protocol("reflection")
        step_types = {s.step_type for s in protocol.steps}
        assert (
            "practice_item" in step_types
        ), "Reflection protocol must have an exit ticket (practice_item)"
        assert (
            "teach_back" in step_types
        ), "Reflection protocol must have a teach_back step"

    def test_reflection_has_misconception_log(self) -> None:
        """Reflection protocol includes a misconception_log step."""
        protocol = get_protocol("reflection")
        step_types = [s.step_type for s in protocol.steps]
        assert "misconception_log" in step_types

    def test_reflection_has_confidence_rerate(self) -> None:
        """Reflection protocol includes a confidence re-rate."""
        protocol = get_protocol("reflection")
        step_types = [s.step_type for s in protocol.steps]
        assert "confidence_check" in step_types


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_unknown_block_type_raises_value_error(self) -> None:
        """get_protocol raises ValueError for unknown block types."""
        with pytest.raises(ValueError, match="Unknown block type"):
            get_protocol("nonexistent_type")

    def test_error_message_includes_block_type(self) -> None:
        """The error message includes the invalid block type name."""
        with pytest.raises(ValueError, match="bogus_type"):
            get_protocol("bogus_type")

    def test_error_message_lists_valid_types(self) -> None:
        """The error message mentions valid types."""
        with pytest.raises(ValueError, match="Valid types"):
            get_protocol("unknown")


# ---------------------------------------------------------------------------
# Dataclass invariants
# ---------------------------------------------------------------------------


class TestDataclassInvariants:
    def test_protocol_step_is_frozen(self) -> None:
        step = ProtocolStep(
            step_number=1,
            instruction_template="test",
            step_type="instruction",
            requires_artifact=False,
        )
        with pytest.raises(AttributeError):
            step.step_number = 2  # type: ignore[misc]

    def test_completion_criteria_is_frozen(self) -> None:
        criteria = CompletionCriteria(required_steps=[1, 2], min_artifacts=1)
        with pytest.raises(AttributeError):
            criteria.min_artifacts = 5  # type: ignore[misc]

    def test_protocol_is_frozen(self) -> None:
        protocol = get_protocol("plan")
        with pytest.raises(AttributeError):
            protocol.block_type = "retrieval"  # type: ignore[misc]

    def test_step_numbers_are_sequential(self) -> None:
        """Step numbers within each protocol are 1-based and sequential."""
        for block_type in ALL_BLOCK_TYPES:
            protocol = get_protocol(block_type)
            numbers = [s.step_number for s in protocol.steps]
            expected = list(range(1, len(protocol.steps) + 1))
            assert (
                numbers == expected
            ), f"{block_type}: step numbers {numbers} != {expected}"

    def test_artifact_required_implies_artifact_type(self) -> None:
        """Steps with requires_artifact=True must have a non-None
        artifact_type."""
        for block_type in ALL_BLOCK_TYPES:
            protocol = get_protocol(block_type)
            for step in protocol.steps:
                if step.requires_artifact:
                    assert step.artifact_type is not None, (
                        f"{block_type} step {step.step_number}: "
                        "requires_artifact=True but artifact_type is None"
                    )
