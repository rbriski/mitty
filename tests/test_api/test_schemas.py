"""Tests for mitty.api.schemas — Pydantic v2 request/response schemas.

Validates Create/Update/Response triplets for all data tables,
field validators (enums, ranges, string lengths), and generic wrappers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from mitty.api.schemas import (
    AppConfigResponse,
    AppConfigUpdate,
    AssessmentCreate,
    AssessmentResponse,
    AssessmentUpdate,
    ErrorDetail,
    ListResponse,
    MasteryStateCreate,
    MasteryStateResponse,
    MasteryStateUpdate,
    PracticeItemCreate,
    PracticeItemResponse,
    PracticeItemUpdate,
    PracticeResultCreate,
    PracticeResultResponse,
    PracticeResultUpdate,
    ResourceChunkCreate,
    ResourceChunkResponse,
    ResourceChunkUpdate,
    ResourceCreate,
    ResourceResponse,
    ResourceUpdate,
    StudentSignalCreate,
    StudentSignalResponse,
    StudentSignalUpdate,
    StudyBlockCreate,
    StudyBlockResponse,
    StudyBlockUpdate,
    StudyPlanCreate,
    StudyPlanResponse,
    StudyPlanUpdate,
)

# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------


class TestAppConfigResponse:
    def test_valid(self) -> None:
        data = {
            "id": 1,
            "current_term_name": "2025-2026 Second Semester",
            "privilege_thresholds": [8, 10, 11, 12],
            "privilege_names": ["Bronze", "Silver", "Gold", "Platinum"],
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        obj = AppConfigResponse.model_validate(data)
        assert obj.id == 1
        assert obj.current_term_name == "2025-2026 Second Semester"

    def test_null_term_name(self) -> None:
        data = {
            "id": 1,
            "current_term_name": None,
            "privilege_thresholds": [8],
            "privilege_names": ["Bronze"],
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        obj = AppConfigResponse.model_validate(data)
        assert obj.current_term_name is None


class TestAppConfigUpdate:
    def test_all_none(self) -> None:
        obj = AppConfigUpdate.model_validate({})
        assert obj.current_term_name is None
        assert obj.privilege_thresholds is None
        assert obj.privilege_names is None

    def test_partial_update(self) -> None:
        obj = AppConfigUpdate.model_validate({"current_term_name": "New Term"})
        assert obj.current_term_name == "New Term"
        assert obj.privilege_thresholds is None


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


class TestAssessmentCreate:
    def test_valid(self) -> None:
        data = {
            "course_id": 123,
            "name": "Chapter 5 Test",
            "assessment_type": "test",
        }
        obj = AssessmentCreate.model_validate(data)
        assert obj.course_id == 123
        assert obj.assessment_type == "test"

    def test_all_assessment_types(self) -> None:
        for t in ("test", "quiz", "essay", "lab", "project"):
            obj = AssessmentCreate.model_validate(
                {"course_id": 1, "name": "X", "assessment_type": t}
            )
            assert obj.assessment_type == t

    def test_invalid_assessment_type(self) -> None:
        with pytest.raises(ValueError):
            AssessmentCreate.model_validate(
                {"course_id": 1, "name": "X", "assessment_type": "invalid"}
            )

    def test_description_too_long(self) -> None:
        with pytest.raises(ValueError):
            AssessmentCreate.model_validate(
                {
                    "course_id": 1,
                    "name": "X",
                    "assessment_type": "test",
                    "description": "a" * 2001,
                }
            )

    def test_description_at_limit(self) -> None:
        obj = AssessmentCreate.model_validate(
            {
                "course_id": 1,
                "name": "X",
                "assessment_type": "test",
                "description": "a" * 2000,
            }
        )
        assert len(obj.description) == 2000


class TestAssessmentUpdate:
    def test_all_none(self) -> None:
        obj = AssessmentUpdate.model_validate({})
        assert obj.name is None
        assert obj.assessment_type is None

    def test_invalid_type_on_update(self) -> None:
        with pytest.raises(ValueError):
            AssessmentUpdate.model_validate({"assessment_type": "invalid"})


class TestAssessmentResponse:
    def test_valid(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        data = {
            "id": 1,
            "course_id": 123,
            "name": "Chapter 5 Test",
            "assessment_type": "test",
            "scheduled_date": now,
            "weight": 0.25,
            "unit_or_topic": "Chapter 5",
            "description": "Full chapter test",
            "canvas_assignment_id": 456,
            "created_at": now,
            "updated_at": now,
        }
        obj = AssessmentResponse.model_validate(data)
        assert obj.id == 1
        assert obj.weight == 0.25


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


class TestResourceCreate:
    def test_valid(self) -> None:
        obj = ResourceCreate.model_validate(
            {
                "course_id": 1,
                "title": "Chapter 1 Notes",
                "resource_type": "textbook_chapter",
            }
        )
        assert obj.resource_type == "textbook_chapter"

    def test_all_resource_types(self) -> None:
        for t in (
            "textbook_chapter",
            "canvas_page",
            "file",
            "link",
            "notes",
            "video",
            "discussion",
        ):
            obj = ResourceCreate.model_validate(
                {"course_id": 1, "title": "X", "resource_type": t}
            )
            assert obj.resource_type == t

    def test_invalid_resource_type(self) -> None:
        with pytest.raises(ValueError):
            ResourceCreate.model_validate(
                {"course_id": 1, "title": "X", "resource_type": "podcast"}
            )

    def test_sort_order_default(self) -> None:
        obj = ResourceCreate.model_validate(
            {"course_id": 1, "title": "X", "resource_type": "file"}
        )
        assert obj.sort_order == 0


class TestResourceUpdate:
    def test_all_none(self) -> None:
        obj = ResourceUpdate.model_validate({})
        assert obj.title is None


class TestResourceResponse:
    def test_valid(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = ResourceResponse.model_validate(
            {
                "id": 1,
                "course_id": 1,
                "title": "Chapter 1",
                "resource_type": "textbook_chapter",
                "source_url": None,
                "canvas_module_id": None,
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        assert obj.id == 1


# ---------------------------------------------------------------------------
# ResourceChunk
# ---------------------------------------------------------------------------


class TestResourceChunkCreate:
    def test_valid(self) -> None:
        obj = ResourceChunkCreate.model_validate(
            {
                "resource_id": 1,
                "chunk_index": 0,
                "content_text": "Some content",
                "token_count": 42,
            }
        )
        assert obj.chunk_index == 0
        assert obj.token_count == 42


class TestResourceChunkUpdate:
    def test_all_none(self) -> None:
        obj = ResourceChunkUpdate.model_validate({})
        assert obj.content_text is None


class TestResourceChunkResponse:
    def test_valid(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = ResourceChunkResponse.model_validate(
            {
                "id": 1,
                "resource_id": 1,
                "chunk_index": 0,
                "content_text": "Some content",
                "token_count": 42,
                "created_at": now,
            }
        )
        assert obj.id == 1


# ---------------------------------------------------------------------------
# StudentSignal
# ---------------------------------------------------------------------------


class TestStudentSignalCreate:
    def test_valid(self) -> None:
        uid = uuid4()
        obj = StudentSignalCreate.model_validate(
            {
                "user_id": str(uid),
                "available_minutes": 60,
                "confidence_level": 3,
                "energy_level": 4,
                "stress_level": 2,
            }
        )
        assert obj.available_minutes == 60

    def test_confidence_out_of_range_low(self) -> None:
        with pytest.raises(ValueError):
            StudentSignalCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "available_minutes": 60,
                    "confidence_level": 0,
                    "energy_level": 3,
                    "stress_level": 3,
                }
            )

    def test_confidence_out_of_range_high(self) -> None:
        with pytest.raises(ValueError):
            StudentSignalCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "available_minutes": 60,
                    "confidence_level": 6,
                    "energy_level": 3,
                    "stress_level": 3,
                }
            )

    def test_energy_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            StudentSignalCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "available_minutes": 60,
                    "confidence_level": 3,
                    "energy_level": 0,
                    "stress_level": 3,
                }
            )

    def test_stress_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            StudentSignalCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "available_minutes": 60,
                    "confidence_level": 3,
                    "energy_level": 3,
                    "stress_level": 6,
                }
            )

    def test_blockers_too_long(self) -> None:
        with pytest.raises(ValueError):
            StudentSignalCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "available_minutes": 60,
                    "confidence_level": 3,
                    "energy_level": 3,
                    "stress_level": 3,
                    "blockers": "x" * 2001,
                }
            )

    def test_notes_too_long(self) -> None:
        with pytest.raises(ValueError):
            StudentSignalCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "available_minutes": 60,
                    "confidence_level": 3,
                    "energy_level": 3,
                    "stress_level": 3,
                    "notes": "x" * 2001,
                }
            )


class TestStudentSignalUpdate:
    def test_all_none(self) -> None:
        obj = StudentSignalUpdate.model_validate({})
        assert obj.available_minutes is None


class TestStudentSignalResponse:
    def test_valid(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = StudentSignalResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "recorded_at": now,
                "available_minutes": 60,
                "confidence_level": 3,
                "energy_level": 4,
                "stress_level": 2,
                "blockers": None,
                "preferences": None,
                "notes": None,
            }
        )
        assert obj.id == 1


# ---------------------------------------------------------------------------
# StudyPlan
# ---------------------------------------------------------------------------


class TestStudyPlanCreate:
    def test_valid(self) -> None:
        uid = uuid4()
        obj = StudyPlanCreate.model_validate(
            {
                "user_id": str(uid),
                "plan_date": "2026-03-11",
                "total_minutes": 90,
            }
        )
        assert obj.plan_date == date(2026, 3, 11)

    def test_status_default(self) -> None:
        uid = uuid4()
        obj = StudyPlanCreate.model_validate(
            {
                "user_id": str(uid),
                "plan_date": "2026-03-11",
                "total_minutes": 90,
            }
        )
        assert obj.status == "draft"

    def test_all_statuses(self) -> None:
        uid = uuid4()
        for s in ("draft", "active", "completed", "skipped"):
            obj = StudyPlanCreate.model_validate(
                {
                    "user_id": str(uid),
                    "plan_date": "2026-03-11",
                    "total_minutes": 90,
                    "status": s,
                }
            )
            assert obj.status == s

    def test_invalid_status(self) -> None:
        with pytest.raises(ValueError):
            StudyPlanCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "plan_date": "2026-03-11",
                    "total_minutes": 90,
                    "status": "cancelled",
                }
            )


class TestStudyPlanUpdate:
    def test_all_none(self) -> None:
        obj = StudyPlanUpdate.model_validate({})
        assert obj.total_minutes is None
        assert obj.status is None


class TestStudyPlanResponse:
    def test_valid(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = StudyPlanResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "plan_date": "2026-03-11",
                "total_minutes": 90,
                "status": "draft",
                "created_at": now,
                "updated_at": now,
            }
        )
        assert obj.id == 1


# ---------------------------------------------------------------------------
# StudyBlock
# ---------------------------------------------------------------------------


class TestStudyBlockCreate:
    def test_valid(self) -> None:
        obj = StudyBlockCreate.model_validate(
            {
                "plan_id": 1,
                "block_type": "retrieval",
                "title": "Review Ch5",
                "target_minutes": 25,
                "sort_order": 0,
            }
        )
        assert obj.block_type == "retrieval"

    def test_all_block_types(self) -> None:
        for bt in (
            "plan",
            "urgent_deliverable",
            "retrieval",
            "worked_example",
            "deep_explanation",
            "reflection",
        ):
            obj = StudyBlockCreate.model_validate(
                {
                    "plan_id": 1,
                    "block_type": bt,
                    "title": "X",
                    "target_minutes": 10,
                    "sort_order": 0,
                }
            )
            assert obj.block_type == bt

    def test_invalid_block_type(self) -> None:
        with pytest.raises(ValueError):
            StudyBlockCreate.model_validate(
                {
                    "plan_id": 1,
                    "block_type": "nap",
                    "title": "X",
                    "target_minutes": 10,
                    "sort_order": 0,
                }
            )

    def test_status_default(self) -> None:
        obj = StudyBlockCreate.model_validate(
            {
                "plan_id": 1,
                "block_type": "retrieval",
                "title": "X",
                "target_minutes": 10,
                "sort_order": 0,
            }
        )
        assert obj.status == "pending"

    def test_all_block_statuses(self) -> None:
        for s in ("pending", "in_progress", "completed", "skipped"):
            obj = StudyBlockCreate.model_validate(
                {
                    "plan_id": 1,
                    "block_type": "retrieval",
                    "title": "X",
                    "target_minutes": 10,
                    "sort_order": 0,
                    "status": s,
                }
            )
            assert obj.status == s

    def test_invalid_block_status(self) -> None:
        with pytest.raises(ValueError):
            StudyBlockCreate.model_validate(
                {
                    "plan_id": 1,
                    "block_type": "retrieval",
                    "title": "X",
                    "target_minutes": 10,
                    "sort_order": 0,
                    "status": "cancelled",
                }
            )

    def test_description_too_long(self) -> None:
        with pytest.raises(ValueError):
            StudyBlockCreate.model_validate(
                {
                    "plan_id": 1,
                    "block_type": "retrieval",
                    "title": "X",
                    "target_minutes": 10,
                    "sort_order": 0,
                    "description": "a" * 2001,
                }
            )


class TestStudyBlockUpdate:
    def test_all_none(self) -> None:
        obj = StudyBlockUpdate.model_validate({})
        assert obj.block_type is None
        assert obj.status is None


class TestStudyBlockResponse:
    def test_valid(self) -> None:
        obj = StudyBlockResponse.model_validate(
            {
                "id": 1,
                "plan_id": 1,
                "block_type": "retrieval",
                "title": "Review",
                "description": None,
                "target_minutes": 25,
                "actual_minutes": None,
                "course_id": None,
                "assessment_id": None,
                "sort_order": 0,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
            }
        )
        assert obj.id == 1


# ---------------------------------------------------------------------------
# MasteryState
# ---------------------------------------------------------------------------


class TestMasteryStateCreate:
    def test_valid(self) -> None:
        uid = uuid4()
        obj = MasteryStateCreate.model_validate(
            {
                "user_id": str(uid),
                "course_id": 123,
                "concept": "Photosynthesis",
            }
        )
        assert obj.mastery_level == 0.0

    def test_mastery_level_range(self) -> None:
        uid = uuid4()
        # Valid at boundaries
        for val in (0.0, 0.5, 1.0):
            obj = MasteryStateCreate.model_validate(
                {
                    "user_id": str(uid),
                    "course_id": 1,
                    "concept": "X",
                    "mastery_level": val,
                }
            )
            assert obj.mastery_level == val

    def test_mastery_level_too_high(self) -> None:
        with pytest.raises(ValueError):
            MasteryStateCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "mastery_level": 1.1,
                }
            )

    def test_mastery_level_too_low(self) -> None:
        with pytest.raises(ValueError):
            MasteryStateCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "mastery_level": -0.1,
                }
            )

    def test_confidence_self_report_range(self) -> None:
        uid = uuid4()
        for val in (0.0, 0.5, 1.0):
            obj = MasteryStateCreate.model_validate(
                {
                    "user_id": str(uid),
                    "course_id": 1,
                    "concept": "X",
                    "confidence_self_report": val,
                }
            )
            assert obj.confidence_self_report == val

    def test_confidence_self_report_too_high(self) -> None:
        with pytest.raises(ValueError):
            MasteryStateCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "confidence_self_report": 1.1,
                }
            )


class TestMasteryStateUpdate:
    def test_all_none(self) -> None:
        obj = MasteryStateUpdate.model_validate({})
        assert obj.mastery_level is None
        assert obj.concept is None


class TestMasteryStateResponse:
    def test_valid(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = MasteryStateResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "course_id": 1,
                "concept": "Photosynthesis",
                "mastery_level": 0.75,
                "confidence_self_report": 0.8,
                "last_retrieval_at": now,
                "next_review_at": now,
                "retrieval_count": 5,
                "success_rate": 0.9,
                "updated_at": now,
            }
        )
        assert obj.id == 1
        assert obj.mastery_level == 0.75


# ---------------------------------------------------------------------------
# PracticeResult
# ---------------------------------------------------------------------------


class TestPracticeItemCreate:
    def test_valid(self) -> None:
        uid = uuid4()
        obj = PracticeItemCreate.model_validate(
            {
                "user_id": str(uid),
                "course_id": 1,
                "concept": "Photosynthesis",
                "practice_type": "multiple_choice",
                "question_text": "What is photosynthesis?",
            }
        )
        assert obj.practice_type == "multiple_choice"
        assert obj.concept == "Photosynthesis"

    def test_all_practice_types(self) -> None:
        uid = uuid4()
        for pt in (
            "multiple_choice",
            "fill_in_blank",
            "short_answer",
            "flashcard",
            "worked_example",
            "explanation",
        ):
            obj = PracticeItemCreate.model_validate(
                {
                    "user_id": str(uid),
                    "course_id": 1,
                    "concept": "X",
                    "practice_type": pt,
                    "question_text": "Q?",
                }
            )
            assert obj.practice_type == pt

    def test_invalid_practice_type(self) -> None:
        with pytest.raises(ValueError):
            PracticeItemCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "practice_type": "meditation",
                    "question_text": "Q?",
                }
            )

    def test_difficulty_level_range(self) -> None:
        uid = uuid4()
        for val in (0.0, 0.5, 1.0):
            obj = PracticeItemCreate.model_validate(
                {
                    "user_id": str(uid),
                    "course_id": 1,
                    "concept": "X",
                    "practice_type": "flashcard",
                    "question_text": "Q?",
                    "difficulty_level": val,
                }
            )
            assert obj.difficulty_level == val

    def test_difficulty_level_too_high(self) -> None:
        with pytest.raises(ValueError):
            PracticeItemCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "practice_type": "flashcard",
                    "question_text": "Q?",
                    "difficulty_level": 1.1,
                }
            )

    def test_difficulty_level_too_low(self) -> None:
        with pytest.raises(ValueError):
            PracticeItemCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "practice_type": "flashcard",
                    "question_text": "Q?",
                    "difficulty_level": -0.1,
                }
            )

    def test_with_options_json(self) -> None:
        uid = uuid4()
        obj = PracticeItemCreate.model_validate(
            {
                "user_id": str(uid),
                "course_id": 1,
                "concept": "X",
                "practice_type": "multiple_choice",
                "question_text": "Q?",
                "options_json": {"A": "Option A", "B": "Option B"},
            }
        )
        assert obj.options_json == {"A": "Option A", "B": "Option B"}

    def test_with_source_chunk_ids(self) -> None:
        uid = uuid4()
        obj = PracticeItemCreate.model_validate(
            {
                "user_id": str(uid),
                "course_id": 1,
                "concept": "X",
                "practice_type": "flashcard",
                "question_text": "Q?",
                "source_chunk_ids": [1, 2, 3],
            }
        )
        assert obj.source_chunk_ids == [1, 2, 3]


class TestPracticeItemUpdate:
    def test_all_none(self) -> None:
        obj = PracticeItemUpdate.model_validate({})
        for field_name in PracticeItemUpdate.model_fields:
            assert getattr(obj, field_name) is None


class TestPracticeItemResponse:
    def test_valid(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = PracticeItemResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "course_id": 1,
                "concept": "Photosynthesis",
                "practice_type": "multiple_choice",
                "question_text": "What is it?",
                "correct_answer": "A process of...",
                "options_json": ["A", "B", "C"],
                "explanation": "Plants use sunlight...",
                "source_chunk_ids": [1, 2],
                "difficulty_level": 0.5,
                "generation_model": "gpt-4o-mini",
                "times_used": 3,
                "last_used_at": now,
                "created_at": now,
            }
        )
        assert obj.id == 1
        assert obj.times_used == 3


class TestPracticeResultCreate:
    def test_valid(self) -> None:
        uid = uuid4()
        obj = PracticeResultCreate.model_validate(
            {
                "user_id": str(uid),
                "course_id": 1,
                "practice_type": "multiple_choice",
                "question_text": "What is photosynthesis?",
            }
        )
        assert obj.practice_type == "multiple_choice"

    def test_all_practice_types(self) -> None:
        uid = uuid4()
        for pt in (
            "multiple_choice",
            "fill_in_blank",
            "short_answer",
            "flashcard",
            "worked_example",
            "explanation",
        ):
            obj = PracticeResultCreate.model_validate(
                {
                    "user_id": str(uid),
                    "course_id": 1,
                    "practice_type": pt,
                    "question_text": "Q?",
                }
            )
            assert obj.practice_type == pt

    def test_invalid_practice_type(self) -> None:
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "meditation",
                    "question_text": "Q?",
                }
            )

    def test_old_practice_type_quiz_rejected(self) -> None:
        """The old 'quiz' type is no longer valid."""
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "quiz",
                    "question_text": "Q?",
                }
            )

    def test_confidence_before_range(self) -> None:
        uid = uuid4()
        for val in (1, 3, 5):
            obj = PracticeResultCreate.model_validate(
                {
                    "user_id": str(uid),
                    "course_id": 1,
                    "practice_type": "multiple_choice",
                    "question_text": "Q?",
                    "confidence_before": float(val),
                }
            )
            assert obj.confidence_before == float(val)

    def test_confidence_before_too_low(self) -> None:
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "multiple_choice",
                    "question_text": "Q?",
                    "confidence_before": 0.5,
                }
            )

    def test_confidence_before_too_high(self) -> None:
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "multiple_choice",
                    "question_text": "Q?",
                    "confidence_before": 5.1,
                }
            )

    def test_question_text_too_long(self) -> None:
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "multiple_choice",
                    "question_text": "x" * 5001,
                }
            )

    def test_student_answer_too_long(self) -> None:
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "multiple_choice",
                    "question_text": "Q?",
                    "student_answer": "x" * 5001,
                }
            )

    def test_correct_answer_too_long(self) -> None:
        with pytest.raises(ValueError):
            PracticeResultCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "practice_type": "multiple_choice",
                    "question_text": "Q?",
                    "correct_answer": "x" * 5001,
                }
            )

    def test_score_and_feedback(self) -> None:
        uid = uuid4()
        obj = PracticeResultCreate.model_validate(
            {
                "user_id": str(uid),
                "course_id": 1,
                "practice_type": "short_answer",
                "question_text": "Q?",
                "score": 0.85,
                "feedback": "Good job!",
                "misconceptions_detected": ["confuses X with Y"],
            }
        )
        assert obj.score == 0.85
        assert obj.feedback == "Good job!"
        assert obj.misconceptions_detected == ["confuses X with Y"]


class TestPracticeResultUpdate:
    def test_all_none(self) -> None:
        obj = PracticeResultUpdate.model_validate({})
        assert obj.student_answer is None
        assert obj.is_correct is None
        assert obj.score is None
        assert obj.feedback is None
        assert obj.misconceptions_detected is None


class TestPracticeResultResponse:
    def test_valid(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = PracticeResultResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "study_block_id": None,
                "course_id": 1,
                "concept": "Photosynthesis",
                "practice_type": "multiple_choice",
                "question_text": "What is it?",
                "student_answer": "A process",
                "correct_answer": "A process of...",
                "is_correct": True,
                "confidence_before": 3.0,
                "time_spent_seconds": 45,
                "score": 1.0,
                "feedback": "Correct!",
                "misconceptions_detected": None,
                "created_at": now,
            }
        )
        assert obj.id == 1
        assert obj.is_correct is True
        assert obj.score == 1.0
        assert obj.feedback == "Correct!"


# ---------------------------------------------------------------------------
# ListResponse
# ---------------------------------------------------------------------------


class TestListResponse:
    def test_valid(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        item = AssessmentResponse.model_validate(
            {
                "id": 1,
                "course_id": 1,
                "name": "Test",
                "assessment_type": "test",
                "scheduled_date": None,
                "weight": None,
                "unit_or_topic": None,
                "description": None,
                "canvas_assignment_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        resp = ListResponse[AssessmentResponse](
            data=[item], total=1, offset=0, limit=20
        )
        assert resp.total == 1
        assert len(resp.data) == 1

    def test_empty_list(self) -> None:
        resp = ListResponse[AssessmentResponse](data=[], total=0, offset=0, limit=20)
        assert resp.data == []
        assert resp.total == 0


# ---------------------------------------------------------------------------
# ErrorDetail
# ---------------------------------------------------------------------------


class TestErrorDetail:
    def test_valid(self) -> None:
        err = ErrorDetail.model_validate(
            {"code": "NOT_FOUND", "message": "Resource not found"}
        )
        assert err.code == "NOT_FOUND"
        assert err.detail is None

    def test_with_detail(self) -> None:
        err = ErrorDetail.model_validate(
            {
                "code": "VALIDATION",
                "message": "Invalid input",
                "detail": "Field X is required",
            }
        )
        assert err.detail == "Field X is required"
