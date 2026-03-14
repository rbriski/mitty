"""Tests for mitty.api.schemas — Pydantic v2 request/response schemas.

Validates Create/Update/Response triplets for all data tables,
field validators (enums, ranges, string lengths), and generic wrappers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from mitty.api.schemas import (
    AnalysisProgressEvent,
    AppConfigResponse,
    AppConfigUpdate,
    AssessmentCreate,
    AssessmentResponse,
    AssessmentUpdate,
    ErrorDetail,
    HomeworkAnalysisResponse,
    HomeworkAnalysisTrigger,
    HomeworkProblemDetail,
    ListResponse,
    MasteryStateCreate,
    MasteryStateResponse,
    MasteryStateUpdate,
    PhaseScore,
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
    TestPrepAnswerResult,
    TestPrepAnswerSubmit,
    TestPrepMasteryProfile,
    TestPrepProblem,
    TestPrepSessionCreate,
    TestPrepSessionResponse,
    TestPrepSessionSummary,
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


# ---------------------------------------------------------------------------
# HomeworkProblemDetail
# ---------------------------------------------------------------------------


class TestHomeworkProblemDetail:
    def test_valid(self) -> None:
        obj = HomeworkProblemDetail.model_validate(
            {
                "problem_number": 1,
                "correctness": 0.8,
                "error_type": "conceptual",
                "concept": "Quadratic equations",
            }
        )
        assert obj.problem_number == 1
        assert obj.correctness == 0.8
        assert obj.error_type == "conceptual"

    def test_minimal(self) -> None:
        obj = HomeworkProblemDetail.model_validate(
            {"problem_number": 1, "correctness": 1.0}
        )
        assert obj.error_type is None
        assert obj.concept is None

    def test_all_error_types(self) -> None:
        for et in ("conceptual", "procedural", "careless", "incomplete", "unknown"):
            obj = HomeworkProblemDetail.model_validate(
                {"problem_number": 1, "correctness": 0.5, "error_type": et}
            )
            assert obj.error_type == et

    def test_invalid_error_type(self) -> None:
        with pytest.raises(ValueError):
            HomeworkProblemDetail.model_validate(
                {"problem_number": 1, "correctness": 0.5, "error_type": "magic"}
            )

    def test_problem_number_zero(self) -> None:
        with pytest.raises(ValueError):
            HomeworkProblemDetail.model_validate(
                {"problem_number": 0, "correctness": 0.5}
            )

    def test_correctness_out_of_range_high(self) -> None:
        with pytest.raises(ValueError):
            HomeworkProblemDetail.model_validate(
                {"problem_number": 1, "correctness": 1.1}
            )

    def test_correctness_out_of_range_low(self) -> None:
        with pytest.raises(ValueError):
            HomeworkProblemDetail.model_validate(
                {"problem_number": 1, "correctness": -0.1}
            )


# ---------------------------------------------------------------------------
# HomeworkAnalysisTrigger
# ---------------------------------------------------------------------------


class TestHomeworkAnalysisTrigger:
    def test_valid(self) -> None:
        obj = HomeworkAnalysisTrigger.model_validate(
            {"assignment_id": 42, "course_id": 7}
        )
        assert obj.assignment_id == 42
        assert obj.course_id == 7

    def test_missing_assignment_id(self) -> None:
        with pytest.raises(ValueError):
            HomeworkAnalysisTrigger.model_validate({"course_id": 7})

    def test_missing_course_id(self) -> None:
        with pytest.raises(ValueError):
            HomeworkAnalysisTrigger.model_validate({"assignment_id": 42})


# ---------------------------------------------------------------------------
# HomeworkAnalysisResponse
# ---------------------------------------------------------------------------


class TestHomeworkAnalysisResponse:
    def test_valid(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        obj = HomeworkAnalysisResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "assignment_id": 42,
                "course_id": 7,
                "page_number": 1,
                "analysis_json": {"problems": []},
                "image_tokens": 500,
                "analyzed_at": now,
                "per_problem_json": [
                    {"problem_number": 1, "correctness": 1.0},
                    {
                        "problem_number": 2,
                        "correctness": 0.5,
                        "error_type": "careless",
                        "concept": "fractions",
                    },
                ],
            }
        )
        assert obj.id == 1
        assert obj.page_number == 1
        assert len(obj.per_problem_json) == 2
        assert obj.per_problem_json[1].error_type == "careless"

    def test_nullable_fields(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        obj = HomeworkAnalysisResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "assignment_id": 42,
                "course_id": 7,
                "page_number": 1,
                "analysis_json": {},
                "analyzed_at": now,
            }
        )
        assert obj.image_tokens is None
        assert obj.per_problem_json is None


# ---------------------------------------------------------------------------
# AnalysisProgressEvent (SSE)
# ---------------------------------------------------------------------------


class TestAnalysisProgressEvent:
    def test_valid_started(self) -> None:
        obj = AnalysisProgressEvent.model_validate(
            {"status": "started", "message": "Beginning analysis"}
        )
        assert obj.status == "started"
        assert obj.page_number is None

    def test_valid_page_complete(self) -> None:
        obj = AnalysisProgressEvent.model_validate(
            {
                "status": "page_complete",
                "page_number": 2,
                "total_pages": 5,
                "message": "Page 2 of 5 done",
            }
        )
        assert obj.page_number == 2
        assert obj.total_pages == 5

    def test_all_statuses(self) -> None:
        for s in ("started", "page_complete", "analyzing", "complete", "error"):
            obj = AnalysisProgressEvent.model_validate({"status": s})
            assert obj.status == s

    def test_invalid_status(self) -> None:
        with pytest.raises(ValueError):
            AnalysisProgressEvent.model_validate({"status": "paused"})

    def test_minimal(self) -> None:
        obj = AnalysisProgressEvent.model_validate({"status": "complete"})
        assert obj.page_number is None
        assert obj.total_pages is None
        assert obj.message is None


# ---------------------------------------------------------------------------
# TestPrepSessionCreate
# ---------------------------------------------------------------------------


class TestTestPrepSessionCreate:
    def test_valid(self) -> None:
        obj = TestPrepSessionCreate.model_validate(
            {
                "course_id": 7,
                "concepts": ["Quadratic equations", "Factoring"],
            }
        )
        assert obj.course_id == 7
        assert len(obj.concepts) == 2
        assert obj.assessment_id is None

    def test_with_assessment_id(self) -> None:
        obj = TestPrepSessionCreate.model_validate(
            {
                "course_id": 7,
                "assessment_id": 99,
                "concepts": ["Derivatives"],
            }
        )
        assert obj.assessment_id == 99

    def test_empty_concepts_rejected(self) -> None:
        with pytest.raises(ValueError):
            TestPrepSessionCreate.model_validate({"course_id": 7, "concepts": []})

    def test_too_many_concepts_rejected(self) -> None:
        with pytest.raises(ValueError):
            TestPrepSessionCreate.model_validate(
                {"course_id": 7, "concepts": [f"concept_{i}" for i in range(51)]}
            )


# ---------------------------------------------------------------------------
# TestPrepSessionResponse
# ---------------------------------------------------------------------------


class TestTestPrepSessionResponse:
    def test_valid(self) -> None:
        sid = uuid4()
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        obj = TestPrepSessionResponse.model_validate(
            {
                "id": str(sid),
                "user_id": str(uid),
                "course_id": 7,
                "state_json": {"phase": "diagnostic", "problem_index": 0},
                "started_at": now,
                "total_problems": 10,
                "total_correct": 7,
                "phase_reached": "focused_practice",
            }
        )
        assert obj.id == sid
        assert obj.total_problems == 10
        assert obj.phase_reached == "focused_practice"

    def test_uuid_primary_key(self) -> None:
        """DEC-006: session IDs are UUIDs, not integers."""
        sid = uuid4()
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        obj = TestPrepSessionResponse.model_validate(
            {
                "id": str(sid),
                "user_id": str(uid),
                "course_id": 1,
                "state_json": {},
                "started_at": now,
            }
        )
        assert isinstance(obj.id, UUID)

    def test_all_session_phases(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        for phase in (
            "diagnostic",
            "focused_practice",
            "error_analysis",
            "mixed_test",
            "calibration",
        ):
            obj = TestPrepSessionResponse.model_validate(
                {
                    "id": str(uuid4()),
                    "user_id": str(uid),
                    "course_id": 1,
                    "state_json": {},
                    "started_at": now,
                    "phase_reached": phase,
                }
            )
            assert obj.phase_reached == phase

    def test_invalid_phase(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        with pytest.raises(ValueError):
            TestPrepSessionResponse.model_validate(
                {
                    "id": str(uuid4()),
                    "user_id": str(uid),
                    "course_id": 1,
                    "state_json": {},
                    "started_at": now,
                    "phase_reached": "warmup",
                }
            )

    def test_defaults(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 14, tzinfo=UTC)
        obj = TestPrepSessionResponse.model_validate(
            {
                "id": str(uuid4()),
                "user_id": str(uid),
                "course_id": 1,
                "state_json": {},
                "started_at": now,
            }
        )
        assert obj.total_problems == 0
        assert obj.total_correct == 0
        assert obj.completed_at is None
        assert obj.duration_seconds is None
        assert obj.phase_reached is None
        assert obj.assessment_id is None


# ---------------------------------------------------------------------------
# TestPrepProblem
# ---------------------------------------------------------------------------


class TestTestPrepProblem:
    def test_valid_multiple_choice(self) -> None:
        obj = TestPrepProblem.model_validate(
            {
                "id": "prob-001",
                "problem_type": "multiple_choice",
                "concept": "Quadratics",
                "difficulty": 0.5,
                "prompt": "Solve x^2 - 4 = 0",
                "choices": ["x = 2", "x = -2", "x = +/-2", "x = 4"],
                "correct_answer": "x = +/-2",
            }
        )
        assert obj.problem_type == "multiple_choice"
        assert len(obj.choices) == 4

    def test_valid_free_response(self) -> None:
        obj = TestPrepProblem.model_validate(
            {
                "id": "prob-002",
                "problem_type": "free_response",
                "concept": "Integration",
                "difficulty": 0.7,
                "prompt": "Find the integral of x^2 dx",
            }
        )
        assert obj.choices is None
        assert obj.correct_answer is None

    def test_all_problem_types(self) -> None:
        for pt in (
            "multiple_choice",
            "free_response",
            "worked_example",
            "error_analysis",
            "mixed",
            "calibration",
        ):
            obj = TestPrepProblem.model_validate(
                {
                    "id": "p1",
                    "problem_type": pt,
                    "concept": "X",
                    "difficulty": 0.5,
                    "prompt": "Q?",
                }
            )
            assert obj.problem_type == pt

    def test_invalid_problem_type(self) -> None:
        with pytest.raises(ValueError):
            TestPrepProblem.model_validate(
                {
                    "id": "p1",
                    "problem_type": "essay",
                    "concept": "X",
                    "difficulty": 0.5,
                    "prompt": "Q?",
                }
            )

    def test_difficulty_boundaries(self) -> None:
        for d in (0.0, 0.5, 1.0):
            obj = TestPrepProblem.model_validate(
                {
                    "id": "p1",
                    "problem_type": "free_response",
                    "concept": "X",
                    "difficulty": d,
                    "prompt": "Q?",
                }
            )
            assert obj.difficulty == d

    def test_difficulty_too_high(self) -> None:
        with pytest.raises(ValueError):
            TestPrepProblem.model_validate(
                {
                    "id": "p1",
                    "problem_type": "free_response",
                    "concept": "X",
                    "difficulty": 1.1,
                    "prompt": "Q?",
                }
            )

    def test_difficulty_too_low(self) -> None:
        with pytest.raises(ValueError):
            TestPrepProblem.model_validate(
                {
                    "id": "p1",
                    "problem_type": "free_response",
                    "concept": "X",
                    "difficulty": -0.1,
                    "prompt": "Q?",
                }
            )

    def test_prompt_too_long(self) -> None:
        with pytest.raises(ValueError):
            TestPrepProblem.model_validate(
                {
                    "id": "p1",
                    "problem_type": "free_response",
                    "concept": "X",
                    "difficulty": 0.5,
                    "prompt": "x" * 10001,
                }
            )


# ---------------------------------------------------------------------------
# TestPrepAnswerSubmit
# ---------------------------------------------------------------------------


class TestTestPrepAnswerSubmit:
    def test_valid(self) -> None:
        sid = uuid4()
        obj = TestPrepAnswerSubmit.model_validate(
            {
                "session_id": str(sid),
                "problem_id": "prob-001",
                "student_answer": "x = +/-2",
                "time_spent_seconds": 45,
            }
        )
        assert obj.session_id == sid
        assert obj.time_spent_seconds == 45

    def test_minimal(self) -> None:
        sid = uuid4()
        obj = TestPrepAnswerSubmit.model_validate(
            {
                "session_id": str(sid),
                "problem_id": "p1",
                "student_answer": "42",
            }
        )
        assert obj.time_spent_seconds is None

    def test_student_answer_too_long(self) -> None:
        with pytest.raises(ValueError):
            TestPrepAnswerSubmit.model_validate(
                {
                    "session_id": str(uuid4()),
                    "problem_id": "p1",
                    "student_answer": "x" * 5001,
                }
            )

    def test_negative_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            TestPrepAnswerSubmit.model_validate(
                {
                    "session_id": str(uuid4()),
                    "problem_id": "p1",
                    "student_answer": "42",
                    "time_spent_seconds": -1,
                }
            )


# ---------------------------------------------------------------------------
# TestPrepAnswerResult
# ---------------------------------------------------------------------------


class TestTestPrepAnswerResult:
    def test_valid_with_next_problem(self) -> None:
        obj = TestPrepAnswerResult.model_validate(
            {
                "is_correct": True,
                "score": 1.0,
                "explanation": "Well done!",
                "next_problem": {
                    "id": "prob-002",
                    "problem_type": "free_response",
                    "concept": "Derivatives",
                    "difficulty": 0.6,
                    "prompt": "Find dy/dx of y = x^3",
                },
            }
        )
        assert obj.is_correct is True
        assert obj.next_problem is not None
        assert obj.next_problem.concept == "Derivatives"

    def test_valid_no_next_problem(self) -> None:
        obj = TestPrepAnswerResult.model_validate(
            {
                "is_correct": False,
                "score": 0.0,
                "explanation": "Session complete.",
            }
        )
        assert obj.next_problem is None

    def test_score_boundaries(self) -> None:
        for s in (0.0, 0.5, 1.0):
            obj = TestPrepAnswerResult.model_validate(
                {"is_correct": True, "score": s, "explanation": "ok"}
            )
            assert obj.score == s

    def test_score_too_high(self) -> None:
        with pytest.raises(ValueError):
            TestPrepAnswerResult.model_validate(
                {"is_correct": True, "score": 1.1, "explanation": "ok"}
            )

    def test_score_too_low(self) -> None:
        with pytest.raises(ValueError):
            TestPrepAnswerResult.model_validate(
                {"is_correct": True, "score": -0.1, "explanation": "ok"}
            )


# ---------------------------------------------------------------------------
# TestPrepMasteryProfile
# ---------------------------------------------------------------------------


class TestTestPrepMasteryProfile:
    def test_valid(self) -> None:
        obj = TestPrepMasteryProfile.model_validate(
            {
                "concept": "Quadratics",
                "mastery_level": 0.85,
                "problems_attempted": 10,
                "problems_correct": 8,
                "avg_time_seconds": 32.5,
                "error_types": ["careless", "procedural"],
            }
        )
        assert obj.concept == "Quadratics"
        assert obj.problems_correct == 8
        assert len(obj.error_types) == 2

    def test_defaults(self) -> None:
        obj = TestPrepMasteryProfile.model_validate(
            {
                "concept": "X",
                "mastery_level": 0.5,
                "problems_attempted": 5,
                "problems_correct": 3,
            }
        )
        assert obj.avg_time_seconds is None
        assert obj.error_types == []

    def test_mastery_level_boundaries(self) -> None:
        for val in (0.0, 0.5, 1.0):
            obj = TestPrepMasteryProfile.model_validate(
                {
                    "concept": "X",
                    "mastery_level": val,
                    "problems_attempted": 1,
                    "problems_correct": 1,
                }
            )
            assert obj.mastery_level == val

    def test_mastery_level_too_high(self) -> None:
        with pytest.raises(ValueError):
            TestPrepMasteryProfile.model_validate(
                {
                    "concept": "X",
                    "mastery_level": 1.1,
                    "problems_attempted": 1,
                    "problems_correct": 1,
                }
            )

    def test_negative_problems_rejected(self) -> None:
        with pytest.raises(ValueError):
            TestPrepMasteryProfile.model_validate(
                {
                    "concept": "X",
                    "mastery_level": 0.5,
                    "problems_attempted": -1,
                    "problems_correct": 0,
                }
            )


# ---------------------------------------------------------------------------
# PhaseScore
# ---------------------------------------------------------------------------


class TestPhaseScore:
    def test_valid(self) -> None:
        obj = PhaseScore.model_validate(
            {"phase": "diagnostic", "total": 10, "correct": 7, "accuracy": 0.7}
        )
        assert obj.phase == "diagnostic"
        assert obj.accuracy == 0.7

    def test_all_phases(self) -> None:
        for p in (
            "diagnostic",
            "focused_practice",
            "error_analysis",
            "mixed_test",
            "calibration",
        ):
            obj = PhaseScore.model_validate(
                {"phase": p, "total": 5, "correct": 3, "accuracy": 0.6}
            )
            assert obj.phase == p

    def test_invalid_phase(self) -> None:
        with pytest.raises(ValueError):
            PhaseScore.model_validate(
                {"phase": "warmup", "total": 5, "correct": 3, "accuracy": 0.6}
            )

    def test_accuracy_boundaries(self) -> None:
        for a in (0.0, 0.5, 1.0):
            obj = PhaseScore.model_validate(
                {"phase": "diagnostic", "total": 10, "correct": 5, "accuracy": a}
            )
            assert obj.accuracy == a

    def test_accuracy_too_high(self) -> None:
        with pytest.raises(ValueError):
            PhaseScore.model_validate(
                {"phase": "diagnostic", "total": 10, "correct": 5, "accuracy": 1.1}
            )


# ---------------------------------------------------------------------------
# TestPrepSessionSummary
# ---------------------------------------------------------------------------


class TestTestPrepSessionSummary:
    def test_valid(self) -> None:
        sid = uuid4()
        obj = TestPrepSessionSummary.model_validate(
            {
                "session_id": str(sid),
                "phase_scores": [
                    {
                        "phase": "diagnostic",
                        "total": 5,
                        "correct": 4,
                        "accuracy": 0.8,
                    },
                    {
                        "phase": "focused_practice",
                        "total": 10,
                        "correct": 7,
                        "accuracy": 0.7,
                    },
                ],
                "total_correct": 11,
                "total_problems": 15,
                "duration_seconds": 1200,
                "mastery_profile": [
                    {
                        "concept": "Quadratics",
                        "mastery_level": 0.8,
                        "problems_attempted": 8,
                        "problems_correct": 6,
                    },
                ],
                "recommendations": [
                    "Review factoring techniques",
                    "Practice word problems",
                ],
            }
        )
        assert obj.session_id == sid
        assert obj.total_correct == 11
        assert len(obj.phase_scores) == 2
        assert len(obj.mastery_profile) == 1
        assert len(obj.recommendations) == 2

    def test_defaults(self) -> None:
        sid = uuid4()
        obj = TestPrepSessionSummary.model_validate(
            {
                "session_id": str(sid),
                "phase_scores": [],
                "total_correct": 0,
                "total_problems": 0,
            }
        )
        assert obj.duration_seconds is None
        assert obj.mastery_profile == []
        assert obj.recommendations == []

    def test_negative_total_rejected(self) -> None:
        with pytest.raises(ValueError):
            TestPrepSessionSummary.model_validate(
                {
                    "session_id": str(uuid4()),
                    "phase_scores": [],
                    "total_correct": -1,
                    "total_problems": 0,
                }
            )
