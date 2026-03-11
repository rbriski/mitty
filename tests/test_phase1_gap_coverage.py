"""Gap coverage tests for Phase 1 models and schemas.

Covers gaps not addressed by existing test_db.py and test_api/test_schemas.py:
- DB: FK targets, index names, unique constraints, server defaults, FK counts
- Schemas: boundary values, empty strings, all Update fields optional,
  ListResponse with multiple entity types, fixture JSON validation
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    import sqlalchemy as sa

from mitty.api.schemas import (
    AssessmentCreate,
    AssessmentResponse,
    AssessmentUpdate,
    ListResponse,
    MasteryStateCreate,
    MasteryStateResponse,
    MasteryStateUpdate,
    PracticeResultCreate,
    PracticeResultResponse,
    PracticeResultUpdate,
    ResourceChunkResponse,
    ResourceChunkUpdate,
    ResourceCreate,
    ResourceResponse,
    ResourceUpdate,
    StudentSignalCreate,
    StudentSignalResponse,
    StudentSignalUpdate,
    StudyBlockResponse,
    StudyBlockUpdate,
    StudyPlanResponse,
    StudyPlanUpdate,
)
from mitty.db import metadata

FIXTURES = Path(__file__).parent / "fixtures"


def _table(name: str) -> sa.Table:
    return metadata.tables[name]


def _index_names(table: sa.Table) -> set[str]:
    return {idx.name for idx in table.indexes}


def _unique_indexes(table: sa.Table) -> dict[str, bool]:
    """Return {index_name: is_unique} for all indexes on the table."""
    return {idx.name: idx.unique for idx in table.indexes}


# ===================================================================
# DB gap coverage: server defaults
# ===================================================================


class TestServerDefaults:
    """Verify server_default values on columns that have them."""

    def test_submissions_late_default(self) -> None:
        col = _table("submissions").c.late
        assert col.server_default is not None
        assert "false" in str(col.server_default.arg)

    def test_submissions_missing_default(self) -> None:
        col = _table("submissions").c.missing
        assert col.server_default is not None
        assert "false" in str(col.server_default.arg)

    def test_resources_sort_order_default(self) -> None:
        col = _table("resources").c.sort_order
        assert col.server_default is not None
        assert "0" in str(col.server_default.arg)

    def test_study_plans_status_default(self) -> None:
        col = _table("study_plans").c.status
        assert col.server_default is not None
        assert "draft" in str(col.server_default.arg)

    def test_study_blocks_status_default(self) -> None:
        col = _table("study_blocks").c.status
        assert col.server_default is not None
        assert "pending" in str(col.server_default.arg)

    def test_mastery_states_mastery_level_default(self) -> None:
        col = _table("mastery_states").c.mastery_level
        assert col.server_default is not None
        assert "0.0" in str(col.server_default.arg)

    def test_mastery_states_retrieval_count_default(self) -> None:
        col = _table("mastery_states").c.retrieval_count
        assert col.server_default is not None
        assert "0" in str(col.server_default.arg)


# ===================================================================
# DB gap coverage: FK counts per table
# ===================================================================


class TestForeignKeyCounts:
    """Verify the exact number of FKs per table."""

    def test_courses_fk_count(self) -> None:
        assert len(_table("courses").foreign_keys) == 0

    def test_assignments_fk_count(self) -> None:
        assert len(_table("assignments").foreign_keys) == 1

    def test_submissions_fk_count(self) -> None:
        assert len(_table("submissions").foreign_keys) == 1

    def test_enrollments_fk_count(self) -> None:
        assert len(_table("enrollments").foreign_keys) == 1

    def test_grade_snapshots_fk_count(self) -> None:
        assert len(_table("grade_snapshots").foreign_keys) == 2

    def test_app_config_fk_count(self) -> None:
        assert len(_table("app_config").foreign_keys) == 0

    def test_assessments_fk_count(self) -> None:
        # course_id -> courses.id, canvas_assignment_id -> assignments.id
        assert len(_table("assessments").foreign_keys) == 2

    def test_resources_fk_count(self) -> None:
        assert len(_table("resources").foreign_keys) == 1

    def test_resource_chunks_fk_count(self) -> None:
        assert len(_table("resource_chunks").foreign_keys) == 1

    def test_student_signals_fk_count(self) -> None:
        assert len(_table("student_signals").foreign_keys) == 0

    def test_study_plans_fk_count(self) -> None:
        assert len(_table("study_plans").foreign_keys) == 0

    def test_study_blocks_fk_count(self) -> None:
        # plan_id -> study_plans.id, course_id -> courses.id,
        # assessment_id -> assessments.id
        assert len(_table("study_blocks").foreign_keys) == 3

    def test_mastery_states_fk_count(self) -> None:
        assert len(_table("mastery_states").foreign_keys) == 1

    def test_practice_results_fk_count(self) -> None:
        # study_block_id -> study_blocks.id, course_id -> courses.id
        assert len(_table("practice_results").foreign_keys) == 2


# ===================================================================
# DB gap coverage: index names
# ===================================================================


class TestIndexNames:
    """Verify that expected index names exist."""

    def test_assignments_course_id_index_name(self) -> None:
        assert "ix_assignments_course_id" in _index_names(_table("assignments"))

    def test_enrollments_course_id_index_name(self) -> None:
        assert "ix_enrollments_course_id" in _index_names(_table("enrollments"))

    def test_grade_snapshots_composite_index_name(self) -> None:
        assert "ix_grade_snapshots_course_enrollment" in _index_names(
            _table("grade_snapshots")
        )

    def test_grade_snapshots_scraped_at_index_name(self) -> None:
        assert "ix_grade_snapshots_scraped_at" in _index_names(
            _table("grade_snapshots")
        )

    def test_assessments_course_scheduled_index_name(self) -> None:
        assert "ix_assessments_course_scheduled" in _index_names(_table("assessments"))

    def test_assessments_scheduled_date_index_name(self) -> None:
        assert "ix_assessments_scheduled_date" in _index_names(_table("assessments"))

    def test_resources_course_type_index_name(self) -> None:
        assert "ix_resources_course_type" in _index_names(_table("resources"))

    def test_resource_chunks_unique_index_name(self) -> None:
        assert "ix_resource_chunks_resource_chunk" in _index_names(
            _table("resource_chunks")
        )

    def test_student_signals_user_recorded_index_name(self) -> None:
        assert "ix_student_signals_user_recorded" in _index_names(
            _table("student_signals")
        )

    def test_study_plans_user_date_index_name(self) -> None:
        assert "ix_study_plans_user_date" in _index_names(_table("study_plans"))

    def test_study_blocks_plan_sort_index_name(self) -> None:
        assert "ix_study_blocks_plan_sort" in _index_names(_table("study_blocks"))

    def test_mastery_states_user_course_index_name(self) -> None:
        assert "ix_mastery_states_user_course" in _index_names(_table("mastery_states"))

    def test_mastery_states_user_review_index_name(self) -> None:
        assert "ix_mastery_states_user_review" in _index_names(_table("mastery_states"))

    def test_mastery_states_unique_index_name(self) -> None:
        assert "ix_mastery_states_user_course_concept" in _index_names(
            _table("mastery_states")
        )

    def test_practice_results_user_course_index_name(self) -> None:
        assert "ix_practice_results_user_course" in _index_names(
            _table("practice_results")
        )

    def test_practice_results_user_created_index_name(self) -> None:
        assert "ix_practice_results_user_created" in _index_names(
            _table("practice_results")
        )


# ===================================================================
# DB gap coverage: unique index flags
# ===================================================================


class TestUniqueIndexes:
    """Verify unique constraints on indexes that should be unique."""

    def test_resource_chunks_index_is_unique(self) -> None:
        uniq = _unique_indexes(_table("resource_chunks"))
        assert uniq["ix_resource_chunks_resource_chunk"] is True

    def test_mastery_states_user_course_concept_is_unique(self) -> None:
        uniq = _unique_indexes(_table("mastery_states"))
        assert uniq["ix_mastery_states_user_course_concept"] is True

    def test_mastery_states_user_course_is_not_unique(self) -> None:
        uniq = _unique_indexes(_table("mastery_states"))
        assert uniq["ix_mastery_states_user_course"] is False

    def test_mastery_states_user_review_is_not_unique(self) -> None:
        uniq = _unique_indexes(_table("mastery_states"))
        assert uniq["ix_mastery_states_user_review"] is False


# ===================================================================
# Schema gap coverage: boundary values
# ===================================================================


class TestStudentSignalBoundaryValues:
    """Test exact boundary values for StudentSignal level fields."""

    def _base_data(self) -> dict:
        return {
            "user_id": str(uuid4()),
            "available_minutes": 60,
            "confidence_level": 3,
            "energy_level": 3,
            "stress_level": 3,
        }

    def test_confidence_at_min(self) -> None:
        data = self._base_data()
        data["confidence_level"] = 1
        obj = StudentSignalCreate.model_validate(data)
        assert obj.confidence_level == 1

    def test_confidence_at_max(self) -> None:
        data = self._base_data()
        data["confidence_level"] = 5
        obj = StudentSignalCreate.model_validate(data)
        assert obj.confidence_level == 5

    def test_energy_at_min(self) -> None:
        data = self._base_data()
        data["energy_level"] = 1
        obj = StudentSignalCreate.model_validate(data)
        assert obj.energy_level == 1

    def test_energy_at_max(self) -> None:
        data = self._base_data()
        data["energy_level"] = 5
        obj = StudentSignalCreate.model_validate(data)
        assert obj.energy_level == 5

    def test_stress_at_min(self) -> None:
        data = self._base_data()
        data["stress_level"] = 1
        obj = StudentSignalCreate.model_validate(data)
        assert obj.stress_level == 1

    def test_stress_at_max(self) -> None:
        data = self._base_data()
        data["stress_level"] = 5
        obj = StudentSignalCreate.model_validate(data)
        assert obj.stress_level == 5


class TestMasteryStateBoundaryValues:
    """Test exact 0.0 and 1.0 boundaries for mastery/confidence fields."""

    def test_mastery_level_exactly_zero(self) -> None:
        obj = MasteryStateCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "concept": "X",
                "mastery_level": 0.0,
            }
        )
        assert obj.mastery_level == 0.0

    def test_mastery_level_exactly_one(self) -> None:
        obj = MasteryStateCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "concept": "X",
                "mastery_level": 1.0,
            }
        )
        assert obj.mastery_level == 1.0

    def test_confidence_self_report_exactly_zero(self) -> None:
        obj = MasteryStateCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "concept": "X",
                "confidence_self_report": 0.0,
            }
        )
        assert obj.confidence_self_report == 0.0

    def test_confidence_self_report_exactly_one(self) -> None:
        obj = MasteryStateCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "concept": "X",
                "confidence_self_report": 1.0,
            }
        )
        assert obj.confidence_self_report == 1.0

    def test_confidence_self_report_too_low(self) -> None:
        with pytest.raises(ValueError):
            MasteryStateCreate.model_validate(
                {
                    "user_id": str(uuid4()),
                    "course_id": 1,
                    "concept": "X",
                    "confidence_self_report": -0.1,
                }
            )


class TestPracticeResultBoundaryValues:
    """Test exact boundaries for confidence_before (1.0 to 5.0)."""

    def test_confidence_before_exactly_one(self) -> None:
        obj = PracticeResultCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "practice_type": "quiz",
                "question_text": "Q?",
                "confidence_before": 1.0,
            }
        )
        assert obj.confidence_before == 1.0

    def test_confidence_before_exactly_five(self) -> None:
        obj = PracticeResultCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "practice_type": "quiz",
                "question_text": "Q?",
                "confidence_before": 5.0,
            }
        )
        assert obj.confidence_before == 5.0

    def test_question_text_at_limit(self) -> None:
        obj = PracticeResultCreate.model_validate(
            {
                "user_id": str(uuid4()),
                "course_id": 1,
                "practice_type": "quiz",
                "question_text": "x" * 5000,
            }
        )
        assert len(obj.question_text) == 5000


# ===================================================================
# Schema gap coverage: all Update fields truly optional
# ===================================================================


class TestAllUpdateFieldsOptional:
    """Verify every Update schema accepts an empty dict (all fields optional)."""

    def test_assessment_update_empty(self) -> None:
        obj = AssessmentUpdate.model_validate({})
        for field_name in AssessmentUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_resource_update_empty(self) -> None:
        obj = ResourceUpdate.model_validate({})
        for field_name in ResourceUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_resource_chunk_update_empty(self) -> None:
        obj = ResourceChunkUpdate.model_validate({})
        for field_name in ResourceChunkUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_student_signal_update_empty(self) -> None:
        obj = StudentSignalUpdate.model_validate({})
        for field_name in StudentSignalUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_study_plan_update_empty(self) -> None:
        obj = StudyPlanUpdate.model_validate({})
        for field_name in StudyPlanUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_study_block_update_empty(self) -> None:
        obj = StudyBlockUpdate.model_validate({})
        for field_name in StudyBlockUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_mastery_state_update_empty(self) -> None:
        obj = MasteryStateUpdate.model_validate({})
        for field_name in MasteryStateUpdate.model_fields:
            assert getattr(obj, field_name) is None

    def test_practice_result_update_empty(self) -> None:
        obj = PracticeResultUpdate.model_validate({})
        for field_name in PracticeResultUpdate.model_fields:
            assert getattr(obj, field_name) is None


# ===================================================================
# Schema gap coverage: empty string edge cases
# ===================================================================


class TestEmptyStringEdgeCases:
    """Verify that empty strings are accepted where strings are allowed."""

    def test_assessment_create_empty_name(self) -> None:
        obj = AssessmentCreate.model_validate(
            {"course_id": 1, "name": "", "assessment_type": "test"}
        )
        assert obj.name == ""

    def test_assessment_create_empty_description(self) -> None:
        obj = AssessmentCreate.model_validate(
            {
                "course_id": 1,
                "name": "X",
                "assessment_type": "test",
                "description": "",
            }
        )
        assert obj.description == ""

    def test_resource_create_empty_title(self) -> None:
        obj = ResourceCreate.model_validate(
            {"course_id": 1, "title": "", "resource_type": "file"}
        )
        assert obj.title == ""

    def test_mastery_state_create_empty_concept(self) -> None:
        obj = MasteryStateCreate.model_validate(
            {"user_id": str(uuid4()), "course_id": 1, "concept": ""}
        )
        assert obj.concept == ""

    def test_student_signal_create_empty_blockers(self) -> None:
        data = {
            "user_id": str(uuid4()),
            "available_minutes": 60,
            "confidence_level": 3,
            "energy_level": 3,
            "stress_level": 3,
            "blockers": "",
        }
        obj = StudentSignalCreate.model_validate(data)
        assert obj.blockers == ""


# ===================================================================
# Schema gap coverage: ListResponse with multiple entity types
# ===================================================================


class TestListResponseMultipleTypes:
    """Verify ListResponse generic wrapper works with various entity types."""

    def test_list_response_with_resource_response(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        item = ResourceResponse.model_validate(
            {
                "id": 1,
                "course_id": 1,
                "title": "Ch1",
                "resource_type": "textbook_chapter",
                "source_url": None,
                "canvas_module_id": None,
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        resp = ListResponse[ResourceResponse](data=[item], total=1, offset=0, limit=20)
        assert resp.total == 1
        assert resp.data[0].title == "Ch1"

    def test_list_response_with_study_plan_response(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        item = StudyPlanResponse.model_validate(
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
        resp = ListResponse[StudyPlanResponse](data=[item], total=1, offset=0, limit=20)
        assert resp.data[0].status == "draft"

    def test_list_response_with_mastery_state_response(self) -> None:
        uid = uuid4()
        now = datetime(2026, 3, 1, tzinfo=UTC)
        item = MasteryStateResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uid),
                "course_id": 1,
                "concept": "X",
                "mastery_level": 0.5,
                "confidence_self_report": None,
                "last_retrieval_at": None,
                "next_review_at": None,
                "retrieval_count": 0,
                "success_rate": None,
                "updated_at": now,
            }
        )
        resp = ListResponse[MasteryStateResponse](
            data=[item], total=1, offset=0, limit=10
        )
        assert resp.data[0].mastery_level == 0.5


# ===================================================================
# Fixture JSON files: validate against Pydantic Response schemas
# ===================================================================


class TestFixtureFiles:
    """Validate that fixture JSON files match their Response schemas."""

    def test_assessments_fixture(self) -> None:
        data = json.loads((FIXTURES / "assessments.json").read_text())
        assert len(data) >= 1
        for item in data:
            AssessmentResponse.model_validate(item)

    def test_resources_fixture(self) -> None:
        data = json.loads((FIXTURES / "resources.json").read_text())
        assert len(data) >= 1
        for item in data:
            ResourceResponse.model_validate(item)

    def test_student_signals_fixture(self) -> None:
        data = json.loads((FIXTURES / "student_signals.json").read_text())
        assert len(data) >= 1
        for item in data:
            StudentSignalResponse.model_validate(item)

    def test_study_plans_fixture(self) -> None:
        data = json.loads((FIXTURES / "study_plans.json").read_text())
        assert len(data) >= 1
        for item in data:
            StudyPlanResponse.model_validate(item)

    def test_study_blocks_fixture(self) -> None:
        data = json.loads((FIXTURES / "study_blocks.json").read_text())
        assert len(data) >= 1
        for item in data:
            StudyBlockResponse.model_validate(item)

    def test_mastery_states_fixture(self) -> None:
        data = json.loads((FIXTURES / "mastery_states.json").read_text())
        assert len(data) >= 1
        for item in data:
            MasteryStateResponse.model_validate(item)

    def test_practice_results_fixture(self) -> None:
        data = json.loads((FIXTURES / "practice_results.json").read_text())
        assert len(data) >= 1
        for item in data:
            PracticeResultResponse.model_validate(item)


# ===================================================================
# Schema gap coverage: Response schemas accept all-null optional fields
# ===================================================================


class TestResponseSchemasWithNulls:
    """Verify Response schemas accept records where all optional fields are null."""

    def test_assessment_response_all_nulls(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = AssessmentResponse.model_validate(
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
        assert obj.scheduled_date is None
        assert obj.weight is None

    def test_resource_chunk_response_minimal(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = ResourceChunkResponse.model_validate(
            {
                "id": 1,
                "resource_id": 1,
                "chunk_index": 0,
                "content_text": "Text",
                "token_count": 10,
                "created_at": now,
            }
        )
        assert obj.chunk_index == 0

    def test_study_block_response_all_nulls(self) -> None:
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
        assert obj.description is None
        assert obj.actual_minutes is None
        assert obj.course_id is None

    def test_practice_result_response_all_nulls(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = PracticeResultResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uuid4()),
                "study_block_id": None,
                "course_id": 1,
                "concept": None,
                "practice_type": "reflection",
                "question_text": "What did you learn?",
                "student_answer": None,
                "correct_answer": None,
                "is_correct": None,
                "confidence_before": None,
                "time_spent_seconds": None,
                "created_at": now,
            }
        )
        assert obj.study_block_id is None
        assert obj.is_correct is None

    def test_mastery_state_response_all_nulls(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        obj = MasteryStateResponse.model_validate(
            {
                "id": 1,
                "user_id": str(uuid4()),
                "course_id": 1,
                "concept": "X",
                "mastery_level": 0.0,
                "confidence_self_report": None,
                "last_retrieval_at": None,
                "next_review_at": None,
                "retrieval_count": 0,
                "success_rate": None,
                "updated_at": now,
            }
        )
        assert obj.confidence_self_report is None
        assert obj.success_rate is None
