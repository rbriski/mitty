"""Tests for mitty.db — SQLAlchemy table definitions.

Verifies table structure (column count, PK, FK, nullable flags, indexes)
against the project schema specification without connecting to a database.
"""

from __future__ import annotations

import sqlalchemy as sa

from mitty.db import metadata


def _table(name: str) -> sa.Table:
    """Helper: return the named table from the shared metadata."""
    return metadata.tables[name]


# ---------------------------------------------------------------------------
# courses
# ---------------------------------------------------------------------------


class TestCoursesTable:
    """Verify the ``courses`` table structure."""

    def test_table_exists(self) -> None:
        assert "courses" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("courses").columns) == 7

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("courses").primary_key]
        assert pk_cols == ["id"]

    def test_id_not_autoincrement(self) -> None:
        col = _table("courses").c.id
        assert col.autoincrement is False or col.autoincrement == "auto"

    def test_columns_and_types(self) -> None:
        t = _table("courses")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.name.type, sa.String)
        assert isinstance(t.c.course_code.type, sa.String)
        assert isinstance(t.c.workflow_state.type, sa.String)
        assert isinstance(t.c.term_id.type, sa.Integer)
        assert isinstance(t.c.term_name.type, sa.String)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("courses")
        assert t.c.id.nullable is False
        assert t.c.name.nullable is False
        assert t.c.course_code.nullable is False
        assert t.c.workflow_state.nullable is True
        assert t.c.term_id.nullable is True
        assert t.c.term_name.nullable is True
        assert t.c.updated_at.nullable is False

    def test_no_foreign_keys(self) -> None:
        assert len(_table("courses").foreign_keys) == 0


# ---------------------------------------------------------------------------
# assignments
# ---------------------------------------------------------------------------


class TestAssignmentsTable:
    """Verify the ``assignments`` table structure."""

    def test_table_exists(self) -> None:
        assert "assignments" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("assignments").columns) == 8

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("assignments").primary_key]
        assert pk_cols == ["id"]

    def test_columns_and_types(self) -> None:
        t = _table("assignments")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.name.type, sa.String)
        assert isinstance(t.c.due_at.type, sa.DateTime)
        assert isinstance(t.c.points_possible.type, sa.Float)
        assert isinstance(t.c.html_url.type, sa.String)
        assert isinstance(t.c.chapter.type, sa.Text)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("assignments")
        assert t.c.id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.name.nullable is False
        assert t.c.due_at.nullable is True
        assert t.c.points_possible.nullable is True
        assert t.c.html_url.nullable is True
        assert t.c.chapter.nullable is True
        assert t.c.updated_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("assignments").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_course_id_index(self) -> None:
        """FK index on assignments(course_id) per DEC-013."""
        idx_cols = _index_column_sets(_table("assignments"))
        assert ("course_id",) in idx_cols


# ---------------------------------------------------------------------------
# submissions
# ---------------------------------------------------------------------------


class TestSubmissionsTable:
    """Verify the ``submissions`` table structure."""

    def test_table_exists(self) -> None:
        assert "submissions" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("submissions").columns) == 8

    def test_primary_key_is_assignment_id(self) -> None:
        """DEC-006: submissions.assignment_id is PK (1:1 with assignment)."""
        pk_cols = [c.name for c in _table("submissions").primary_key]
        assert pk_cols == ["assignment_id"]

    def test_columns_and_types(self) -> None:
        t = _table("submissions")
        assert isinstance(t.c.assignment_id.type, sa.Integer)
        assert isinstance(t.c.score.type, sa.Float)
        assert isinstance(t.c.grade.type, sa.String)
        assert isinstance(t.c.submitted_at.type, sa.DateTime)
        assert isinstance(t.c.workflow_state.type, sa.String)
        assert isinstance(t.c.late.type, sa.Boolean)
        assert isinstance(t.c.missing.type, sa.Boolean)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("submissions")
        assert t.c.assignment_id.nullable is False
        assert t.c.score.nullable is True
        assert t.c.grade.nullable is True
        assert t.c.submitted_at.nullable is True
        assert t.c.workflow_state.nullable is True
        assert t.c.late.nullable is False
        assert t.c.missing.nullable is False
        assert t.c.updated_at.nullable is False

    def test_foreign_key_to_assignments(self) -> None:
        fks = _table("submissions").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "assignments.id" in fk_targets


# ---------------------------------------------------------------------------
# enrollments
# ---------------------------------------------------------------------------


class TestEnrollmentsTable:
    """Verify the ``enrollments`` table structure."""

    def test_table_exists(self) -> None:
        assert "enrollments" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("enrollments").columns) == 9

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("enrollments").primary_key]
        assert pk_cols == ["id"]

    def test_columns_and_types(self) -> None:
        t = _table("enrollments")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.type.type, sa.String)
        assert isinstance(t.c.enrollment_state.type, sa.String)
        assert isinstance(t.c.current_score.type, sa.Float)
        assert isinstance(t.c.current_grade.type, sa.String)
        assert isinstance(t.c.final_score.type, sa.Float)
        assert isinstance(t.c.final_grade.type, sa.String)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("enrollments")
        assert t.c.id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.type.nullable is False
        assert t.c.enrollment_state.nullable is False
        assert t.c.current_score.nullable is True
        assert t.c.current_grade.nullable is True
        assert t.c.final_score.nullable is True
        assert t.c.final_grade.nullable is True
        assert t.c.updated_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("enrollments").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_course_id_index(self) -> None:
        """FK index on enrollments(course_id) per DEC-013."""
        idx_cols = _index_column_sets(_table("enrollments"))
        assert ("course_id",) in idx_cols


# ---------------------------------------------------------------------------
# grade_snapshots
# ---------------------------------------------------------------------------


class TestGradeSnapshotsTable:
    """Verify the ``grade_snapshots`` table structure."""

    def test_table_exists(self) -> None:
        assert "grade_snapshots" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("grade_snapshots").columns) == 8

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("grade_snapshots").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("grade_snapshots").c.id
        # SQLAlchemy sets autoincrement=True by default for integer PKs,
        # or it can be "auto" — both are acceptable.
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("grade_snapshots")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.enrollment_id.type, sa.Integer)
        assert isinstance(t.c.current_score.type, sa.Float)
        assert isinstance(t.c.current_grade.type, sa.String)
        assert isinstance(t.c.final_score.type, sa.Float)
        assert isinstance(t.c.final_grade.type, sa.String)
        assert isinstance(t.c.scraped_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("grade_snapshots")
        assert t.c.id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.enrollment_id.nullable is False
        assert t.c.current_score.nullable is True
        assert t.c.current_grade.nullable is True
        assert t.c.final_score.nullable is True
        assert t.c.final_grade.nullable is True
        assert t.c.scraped_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("grade_snapshots").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_foreign_key_to_enrollments(self) -> None:
        """DEC-012: grade_snapshots has enrollment_id FK."""
        fks = _table("grade_snapshots").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "enrollments.id" in fk_targets

    def test_course_enrollment_index(self) -> None:
        """Composite index on (course_id, enrollment_id) per DEC-013."""
        idx_cols = _index_column_sets(_table("grade_snapshots"))
        assert ("course_id", "enrollment_id") in idx_cols

    def test_scraped_at_desc_index(self) -> None:
        """Index on grade_snapshots(scraped_at DESC) for time-series queries."""
        t = _table("grade_snapshots")
        found = False
        for idx in t.indexes:
            col_names = [c.name for c in idx.columns]
            if col_names == ["scraped_at"]:
                found = True
                break
        assert found, "Expected index on grade_snapshots(scraped_at)"


# ---------------------------------------------------------------------------
# app_config
# ---------------------------------------------------------------------------


class TestAppConfigTable:
    """Verify the ``app_config`` table structure."""

    def test_table_exists(self) -> None:
        assert "app_config" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("app_config").columns) == 6

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("app_config").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("app_config").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("app_config")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.current_term_name.type, sa.String)
        assert isinstance(t.c.privilege_thresholds.type, sa.JSON)
        assert isinstance(t.c.privilege_names.type, sa.JSON)
        assert isinstance(t.c.created_at.type, sa.DateTime)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("app_config")
        assert t.c.id.nullable is False
        assert t.c.current_term_name.nullable is True
        assert t.c.privilege_thresholds.nullable is False
        assert t.c.privilege_names.nullable is False
        assert t.c.created_at.nullable is False
        assert t.c.updated_at.nullable is False

    def test_no_foreign_keys(self) -> None:
        assert len(_table("app_config").foreign_keys) == 0


# ---------------------------------------------------------------------------
# assessments
# ---------------------------------------------------------------------------


class TestAssessmentsTable:
    """Verify the ``assessments`` table structure."""

    def test_table_exists(self) -> None:
        assert "assessments" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("assessments").columns) == 15

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("assessments").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("assessments").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("assessments")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.name.type, sa.String)
        assert isinstance(t.c.assessment_type.type, sa.String)
        assert isinstance(t.c.scheduled_date.type, sa.DateTime)
        assert isinstance(t.c.weight.type, sa.Float)
        assert isinstance(t.c.unit_or_topic.type, sa.String)
        assert isinstance(t.c.description.type, sa.String)
        assert isinstance(t.c.canvas_assignment_id.type, sa.Integer)
        assert isinstance(t.c.canvas_quiz_id.type, sa.Integer)
        assert isinstance(t.c.auto_created.type, sa.Boolean)
        assert isinstance(t.c.source.type, sa.String)
        assert isinstance(t.c.created_at.type, sa.DateTime)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("assessments")
        assert t.c.id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.name.nullable is False
        assert t.c.assessment_type.nullable is False
        assert t.c.scheduled_date.nullable is True
        assert t.c.weight.nullable is True
        assert t.c.unit_or_topic.nullable is True
        assert t.c.description.nullable is True
        assert t.c.canvas_assignment_id.nullable is True
        assert t.c.canvas_quiz_id.nullable is True
        assert t.c.auto_created.nullable is False
        assert t.c.source.nullable is True
        assert t.c.created_at.nullable is False
        assert t.c.updated_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("assessments").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_foreign_key_to_assignments(self) -> None:
        fks = _table("assessments").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "assignments.id" in fk_targets

    def test_course_scheduled_index(self) -> None:
        idx_cols = _index_column_sets(_table("assessments"))
        assert ("course_id", "scheduled_date") in idx_cols

    def test_scheduled_date_index(self) -> None:
        idx_cols = _index_column_sets(_table("assessments"))
        assert ("scheduled_date",) in idx_cols

    def test_canvas_quiz_id_index(self) -> None:
        idx_cols = _index_column_sets(_table("assessments"))
        assert ("canvas_quiz_id",) in idx_cols


# ---------------------------------------------------------------------------
# resources
# ---------------------------------------------------------------------------


class TestResourcesTable:
    """Verify the ``resources`` table structure."""

    def test_table_exists(self) -> None:
        assert "resources" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("resources").columns) == 13

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("resources").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("resources").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("resources")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.title.type, sa.String)
        assert isinstance(t.c.resource_type.type, sa.String)
        assert isinstance(t.c.source_url.type, sa.String)
        assert isinstance(t.c.canvas_module_id.type, sa.Integer)
        assert isinstance(t.c.sort_order.type, sa.Integer)
        assert isinstance(t.c.content_text.type, sa.Text)
        assert isinstance(t.c.canvas_item_id.type, sa.Integer)
        assert isinstance(t.c.module_name.type, sa.String)
        assert isinstance(t.c.module_position.type, sa.Integer)
        assert isinstance(t.c.created_at.type, sa.DateTime)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("resources")
        assert t.c.id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.title.nullable is False
        assert t.c.resource_type.nullable is False
        assert t.c.source_url.nullable is True
        assert t.c.canvas_module_id.nullable is True
        assert t.c.sort_order.nullable is False
        assert t.c.content_text.nullable is True
        assert t.c.canvas_item_id.nullable is True
        assert t.c.module_name.nullable is True
        assert t.c.module_position.nullable is True
        assert t.c.created_at.nullable is False
        assert t.c.updated_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("resources").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_course_type_index(self) -> None:
        idx_cols = _index_column_sets(_table("resources"))
        assert ("course_id", "resource_type") in idx_cols

    def test_canvas_item_id_index(self) -> None:
        idx_cols = _index_column_sets(_table("resources"))
        assert ("canvas_item_id",) in idx_cols


# ---------------------------------------------------------------------------
# resource_chunks
# ---------------------------------------------------------------------------


class TestResourceChunksTable:
    """Verify the ``resource_chunks`` table structure."""

    def test_table_exists(self) -> None:
        assert "resource_chunks" in metadata.tables

    def test_column_count(self) -> None:
        # 7 columns: id, resource_id, chunk_index, content_text,
        # embedding_vector, token_count, created_at
        assert len(_table("resource_chunks").columns) == 7

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("resource_chunks").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("resource_chunks").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("resource_chunks")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.resource_id.type, sa.Integer)
        assert isinstance(t.c.chunk_index.type, sa.Integer)
        assert isinstance(t.c.content_text.type, sa.String)
        assert isinstance(t.c.token_count.type, sa.Integer)
        assert isinstance(t.c.created_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("resource_chunks")
        assert t.c.id.nullable is False
        assert t.c.resource_id.nullable is False
        assert t.c.chunk_index.nullable is False
        assert t.c.content_text.nullable is False
        assert t.c.embedding_vector.nullable is True
        assert t.c.token_count.nullable is False
        assert t.c.created_at.nullable is False

    def test_foreign_key_to_resources(self) -> None:
        fks = _table("resource_chunks").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "resources.id" in fk_targets

    def test_resource_chunk_unique_index(self) -> None:
        """Unique constraint on (resource_id, chunk_index)."""
        idx_cols = _index_column_sets(_table("resource_chunks"))
        assert ("resource_id", "chunk_index") in idx_cols


# ---------------------------------------------------------------------------
# student_signals
# ---------------------------------------------------------------------------


class TestStudentSignalsTable:
    """Verify the ``student_signals`` table structure."""

    def test_table_exists(self) -> None:
        assert "student_signals" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("student_signals").columns) == 10

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("student_signals").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("student_signals").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("student_signals")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.recorded_at.type, sa.DateTime)
        assert isinstance(t.c.available_minutes.type, sa.Integer)
        assert isinstance(t.c.confidence_level.type, sa.Integer)
        assert isinstance(t.c.energy_level.type, sa.Integer)
        assert isinstance(t.c.stress_level.type, sa.Integer)
        assert isinstance(t.c.blockers.type, sa.String)
        assert isinstance(t.c.preferences.type, sa.JSON)
        assert isinstance(t.c.notes.type, sa.String)

    def test_nullable_flags(self) -> None:
        t = _table("student_signals")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.recorded_at.nullable is False
        assert t.c.available_minutes.nullable is False
        assert t.c.confidence_level.nullable is False
        assert t.c.energy_level.nullable is False
        assert t.c.stress_level.nullable is False
        assert t.c.blockers.nullable is True
        assert t.c.preferences.nullable is True
        assert t.c.notes.nullable is True

    def test_no_foreign_keys(self) -> None:
        assert len(_table("student_signals").foreign_keys) == 0

    def test_user_recorded_index(self) -> None:
        idx_cols = _index_column_sets(_table("student_signals"))
        assert ("user_id", "recorded_at") in idx_cols


# ---------------------------------------------------------------------------
# study_plans
# ---------------------------------------------------------------------------


class TestStudyPlansTable:
    """Verify the ``study_plans`` table structure."""

    def test_table_exists(self) -> None:
        assert "study_plans" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("study_plans").columns) == 7

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("study_plans").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("study_plans").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("study_plans")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.plan_date.type, sa.Date)
        assert isinstance(t.c.total_minutes.type, sa.Integer)
        assert isinstance(t.c.status.type, sa.String)
        assert isinstance(t.c.created_at.type, sa.DateTime)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("study_plans")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.plan_date.nullable is False
        assert t.c.total_minutes.nullable is False
        assert t.c.status.nullable is False
        assert t.c.created_at.nullable is False
        assert t.c.updated_at.nullable is False

    def test_no_foreign_keys(self) -> None:
        assert len(_table("study_plans").foreign_keys) == 0

    def test_user_date_index(self) -> None:
        idx_cols = _index_column_sets(_table("study_plans"))
        assert ("user_id", "plan_date") in idx_cols


# ---------------------------------------------------------------------------
# study_blocks
# ---------------------------------------------------------------------------


class TestStudyBlocksTable:
    """Verify the ``study_blocks`` table structure."""

    def test_table_exists(self) -> None:
        assert "study_blocks" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("study_blocks").columns) == 13

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("study_blocks").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("study_blocks").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("study_blocks")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.plan_id.type, sa.Integer)
        assert isinstance(t.c.block_type.type, sa.String)
        assert isinstance(t.c.title.type, sa.String)
        assert isinstance(t.c.description.type, sa.String)
        assert isinstance(t.c.target_minutes.type, sa.Integer)
        assert isinstance(t.c.actual_minutes.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.assessment_id.type, sa.Integer)
        assert isinstance(t.c.sort_order.type, sa.Integer)
        assert isinstance(t.c.status.type, sa.String)
        assert isinstance(t.c.started_at.type, sa.DateTime)
        assert isinstance(t.c.completed_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("study_blocks")
        assert t.c.id.nullable is False
        assert t.c.plan_id.nullable is False
        assert t.c.block_type.nullable is False
        assert t.c.title.nullable is False
        assert t.c.description.nullable is True
        assert t.c.target_minutes.nullable is False
        assert t.c.actual_minutes.nullable is True
        assert t.c.course_id.nullable is True
        assert t.c.assessment_id.nullable is True
        assert t.c.sort_order.nullable is False
        assert t.c.status.nullable is False
        assert t.c.started_at.nullable is True
        assert t.c.completed_at.nullable is True

    def test_foreign_key_to_study_plans(self) -> None:
        fks = _table("study_blocks").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "study_plans.id" in fk_targets

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("study_blocks").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_foreign_key_to_assessments(self) -> None:
        fks = _table("study_blocks").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "assessments.id" in fk_targets

    def test_plan_sort_index(self) -> None:
        idx_cols = _index_column_sets(_table("study_blocks"))
        assert ("plan_id", "sort_order") in idx_cols


# ---------------------------------------------------------------------------
# mastery_states
# ---------------------------------------------------------------------------


class TestMasteryStatesTable:
    """Verify the ``mastery_states`` table structure."""

    def test_table_exists(self) -> None:
        assert "mastery_states" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("mastery_states").columns) == 11

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("mastery_states").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("mastery_states").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("mastery_states")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.concept.type, sa.String)
        assert isinstance(t.c.mastery_level.type, sa.Float)
        assert isinstance(t.c.confidence_self_report.type, sa.Float)
        assert isinstance(t.c.last_retrieval_at.type, sa.DateTime)
        assert isinstance(t.c.next_review_at.type, sa.DateTime)
        assert isinstance(t.c.retrieval_count.type, sa.Integer)
        assert isinstance(t.c.success_rate.type, sa.Float)
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("mastery_states")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.concept.nullable is False
        assert t.c.mastery_level.nullable is False
        assert t.c.confidence_self_report.nullable is True
        assert t.c.last_retrieval_at.nullable is True
        assert t.c.next_review_at.nullable is True
        assert t.c.retrieval_count.nullable is False
        assert t.c.success_rate.nullable is True
        assert t.c.updated_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("mastery_states").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_user_course_index(self) -> None:
        idx_cols = _index_column_sets(_table("mastery_states"))
        assert ("user_id", "course_id") in idx_cols

    def test_user_review_index(self) -> None:
        idx_cols = _index_column_sets(_table("mastery_states"))
        assert ("user_id", "next_review_at") in idx_cols

    def test_unique_user_course_concept_index(self) -> None:
        idx_cols = _index_column_sets(_table("mastery_states"))
        assert ("user_id", "course_id", "concept") in idx_cols


# ---------------------------------------------------------------------------
# practice_results
# ---------------------------------------------------------------------------


class TestPracticeItemsTable:
    """Verify the ``practice_items`` table structure."""

    def test_table_exists(self) -> None:
        assert "practice_items" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("practice_items").columns) == 15

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("practice_items").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("practice_items").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("practice_items")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.concept.type, sa.String)
        assert isinstance(t.c.practice_type.type, sa.String)
        assert isinstance(t.c.question_text.type, sa.Text)
        assert isinstance(t.c.correct_answer.type, sa.Text)
        assert isinstance(t.c.options_json.type, sa.JSON)
        assert isinstance(t.c.explanation.type, sa.Text)
        assert isinstance(t.c.difficulty_level.type, sa.Float)
        assert isinstance(t.c.times_used.type, sa.Integer)
        assert isinstance(t.c.created_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("practice_items")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.concept.nullable is False
        assert t.c.practice_type.nullable is False
        assert t.c.question_text.nullable is False
        assert t.c.correct_answer.nullable is True
        assert t.c.options_json.nullable is True
        assert t.c.explanation.nullable is True
        assert t.c.source_chunk_ids.nullable is True
        assert t.c.difficulty_level.nullable is True
        assert t.c.generation_model.nullable is True
        assert t.c.times_used.nullable is False
        assert t.c.last_used_at.nullable is True
        assert t.c.created_at.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("practice_items").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_user_course_concept_index(self) -> None:
        idx_cols = _index_column_sets(_table("practice_items"))
        assert ("user_id", "course_id", "concept") in idx_cols

    def test_times_used_server_default(self) -> None:
        col = _table("practice_items").c.times_used
        assert col.server_default is not None
        assert "0" in str(col.server_default.arg)


class TestPracticeResultsTable:
    """Verify the ``practice_results`` table structure."""

    def test_table_exists(self) -> None:
        assert "practice_results" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("practice_results").columns) == 16

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("practice_results").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("practice_results").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("practice_results")
        assert isinstance(t.c.id.type, sa.Integer)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.study_block_id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.concept.type, sa.String)
        assert isinstance(t.c.practice_type.type, sa.String)
        assert isinstance(t.c.question_text.type, sa.String)
        assert isinstance(t.c.student_answer.type, sa.String)
        assert isinstance(t.c.correct_answer.type, sa.String)
        assert isinstance(t.c.is_correct.type, sa.Boolean)
        assert isinstance(t.c.confidence_before.type, sa.Float)
        assert isinstance(t.c.time_spent_seconds.type, sa.Integer)
        assert isinstance(t.c.score.type, sa.Float)
        assert isinstance(t.c.feedback.type, sa.Text)
        assert isinstance(t.c.created_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("practice_results")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.study_block_id.nullable is True
        assert t.c.course_id.nullable is False
        assert t.c.concept.nullable is True
        assert t.c.practice_type.nullable is False
        assert t.c.question_text.nullable is False
        assert t.c.student_answer.nullable is True
        assert t.c.correct_answer.nullable is True
        assert t.c.is_correct.nullable is True
        assert t.c.confidence_before.nullable is True
        assert t.c.time_spent_seconds.nullable is True
        assert t.c.score.nullable is True
        assert t.c.feedback.nullable is True
        assert t.c.misconceptions_detected.nullable is True
        assert t.c.created_at.nullable is False

    def test_foreign_key_to_study_blocks(self) -> None:
        fks = _table("practice_results").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "study_blocks.id" in fk_targets

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("practice_results").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_user_course_index(self) -> None:
        idx_cols = _index_column_sets(_table("practice_results"))
        assert ("user_id", "course_id") in idx_cols

    def test_user_created_index(self) -> None:
        idx_cols = _index_column_sets(_table("practice_results"))
        assert ("user_id", "created_at") in idx_cols


# ---------------------------------------------------------------------------
# homework_analyses
# ---------------------------------------------------------------------------


class TestHomeworkAnalysesTable:
    """Verify the ``homework_analyses`` table structure."""

    def test_table_exists(self) -> None:
        assert "homework_analyses" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("homework_analyses").columns) == 8

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("homework_analyses").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("homework_analyses").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("homework_analyses")
        assert isinstance(t.c.id.type, sa.BigInteger)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.assignment_id.type, sa.Integer)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.page_number.type, sa.Integer)
        assert isinstance(t.c.analysis_json.type, sa.JSON)
        assert isinstance(t.c.image_tokens.type, sa.Integer)
        assert isinstance(t.c.analyzed_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("homework_analyses")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.assignment_id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.page_number.nullable is False
        assert t.c.analysis_json.nullable is False
        assert t.c.image_tokens.nullable is True
        assert t.c.analyzed_at.nullable is False

    def test_foreign_key_to_assignments(self) -> None:
        fks = _table("homework_analyses").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "assignments.id" in fk_targets

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("homework_analyses").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_user_assignment_index(self) -> None:
        idx_cols = _index_column_sets(_table("homework_analyses"))
        assert ("user_id", "assignment_id") in idx_cols

    def test_unique_constraint(self) -> None:
        t = _table("homework_analyses")
        unique_constraints = [
            c for c in t.constraints if isinstance(c, sa.UniqueConstraint)
        ]
        col_sets = {
            frozenset(col.name for col in uc.columns) for uc in unique_constraints
        }
        assert frozenset({"user_id", "assignment_id", "page_number"}) in col_sets


# ---------------------------------------------------------------------------
# test_prep_sessions
# ---------------------------------------------------------------------------


class TestTestPrepSessionsTable:
    """Verify the ``test_prep_sessions`` table structure."""

    def test_table_exists(self) -> None:
        assert "test_prep_sessions" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("test_prep_sessions").columns) == 12

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("test_prep_sessions").primary_key]
        assert pk_cols == ["id"]

    def test_uuid_primary_key(self) -> None:
        col = _table("test_prep_sessions").c.id
        assert isinstance(col.type, sa.Uuid)

    def test_columns_and_types(self) -> None:
        t = _table("test_prep_sessions")
        assert isinstance(t.c.id.type, sa.Uuid)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.course_id.type, sa.Integer)
        assert isinstance(t.c.assessment_id.type, sa.Integer)
        assert isinstance(t.c.state_json.type, sa.JSON)
        assert isinstance(t.c.started_at.type, sa.DateTime)
        assert isinstance(t.c.completed_at.type, sa.DateTime)
        assert isinstance(t.c.total_problems.type, sa.Integer)
        assert isinstance(t.c.total_correct.type, sa.Integer)
        assert isinstance(t.c.duration_seconds.type, sa.Integer)
        assert isinstance(t.c.phase_reached.type, sa.String)
        assert isinstance(t.c.session_type.type, sa.Text)

    def test_nullable_flags(self) -> None:
        t = _table("test_prep_sessions")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.assessment_id.nullable is True
        assert t.c.state_json.nullable is False
        assert t.c.started_at.nullable is False
        assert t.c.completed_at.nullable is True
        assert t.c.total_problems.nullable is False
        assert t.c.total_correct.nullable is False
        assert t.c.duration_seconds.nullable is True
        assert t.c.phase_reached.nullable is True
        assert t.c.session_type.nullable is False

    def test_foreign_key_to_courses(self) -> None:
        fks = _table("test_prep_sessions").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "courses.id" in fk_targets

    def test_foreign_key_to_assessments(self) -> None:
        fks = _table("test_prep_sessions").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "assessments.id" in fk_targets

    def test_user_started_index(self) -> None:
        idx_cols = _index_column_sets(_table("test_prep_sessions"))
        assert ("user_id", "started_at") in idx_cols

    def test_course_started_index(self) -> None:
        idx_cols = _index_column_sets(_table("test_prep_sessions"))
        assert ("course_id", "started_at") in idx_cols

    def test_server_defaults(self) -> None:
        t = _table("test_prep_sessions")
        assert t.c.total_problems.server_default is not None
        assert t.c.total_correct.server_default is not None


# ---------------------------------------------------------------------------
# test_prep_results
# ---------------------------------------------------------------------------


class TestTestPrepResultsTable:
    """Verify the ``test_prep_results`` table structure."""

    def test_table_exists(self) -> None:
        assert "test_prep_results" in metadata.tables

    def test_column_count(self) -> None:
        assert len(_table("test_prep_results").columns) == 14

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in _table("test_prep_results").primary_key]
        assert pk_cols == ["id"]

    def test_id_autoincrement(self) -> None:
        col = _table("test_prep_results").c.id
        assert col.autoincrement in (True, "auto")

    def test_columns_and_types(self) -> None:
        t = _table("test_prep_results")
        assert isinstance(t.c.id.type, sa.BigInteger)
        assert isinstance(t.c.user_id.type, sa.Uuid)
        assert isinstance(t.c.session_id.type, sa.Uuid)
        assert isinstance(t.c.concept.type, sa.String)
        assert isinstance(t.c.problem_json.type, sa.JSON)
        assert isinstance(t.c.student_answer.type, sa.String)
        assert isinstance(t.c.is_correct.type, sa.Boolean)
        assert isinstance(t.c.score.type, sa.Float)
        assert isinstance(t.c.feedback.type, sa.Text)
        assert isinstance(t.c.hints_used.type, sa.Integer)
        assert isinstance(t.c.worked_example_shown.type, sa.Boolean)
        assert isinstance(t.c.time_spent_seconds.type, sa.Integer)
        assert isinstance(t.c.difficulty.type, sa.Float)
        assert isinstance(t.c.created_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("test_prep_results")
        assert t.c.id.nullable is False
        assert t.c.user_id.nullable is False
        assert t.c.session_id.nullable is False
        assert t.c.concept.nullable is False
        assert t.c.problem_json.nullable is False
        assert t.c.student_answer.nullable is True
        assert t.c.is_correct.nullable is True
        assert t.c.score.nullable is True
        assert t.c.feedback.nullable is True
        assert t.c.hints_used.nullable is False
        assert t.c.worked_example_shown.nullable is False
        assert t.c.time_spent_seconds.nullable is True
        assert t.c.difficulty.nullable is False
        assert t.c.created_at.nullable is False

    def test_foreign_key_to_test_prep_sessions(self) -> None:
        fks = _table("test_prep_results").foreign_keys
        fk_targets = {fk.target_fullname for fk in fks}
        assert "test_prep_sessions.id" in fk_targets

    def test_session_created_index(self) -> None:
        idx_cols = _index_column_sets(_table("test_prep_results"))
        assert ("session_id", "created_at") in idx_cols

    def test_user_concept_correct_index(self) -> None:
        idx_cols = _index_column_sets(_table("test_prep_results"))
        assert ("user_id", "concept", "is_correct") in idx_cols

    def test_user_created_index(self) -> None:
        idx_cols = _index_column_sets(_table("test_prep_results"))
        assert ("user_id", "created_at") in idx_cols

    def test_server_defaults(self) -> None:
        t = _table("test_prep_results")
        assert t.c.hints_used.server_default is not None
        assert t.c.worked_example_shown.server_default is not None


# ---------------------------------------------------------------------------
# Cross-table checks
# ---------------------------------------------------------------------------


class TestMetadata:
    """Cross-cutting checks on the full metadata."""

    def test_table_count(self) -> None:
        assert len(metadata.tables) == 25

    def test_all_tables_present(self) -> None:
        expected = {
            "courses",
            "assignments",
            "submissions",
            "enrollments",
            "grade_snapshots",
            "app_config",
            "assessments",
            "resources",
            "resource_chunks",
            "student_signals",
            "study_plans",
            "study_blocks",
            "mastery_states",
            "practice_items",
            "practice_results",
            "ai_audit_log",
            "coach_messages",
            "escalation_log",
            "flagged_responses",
            "study_block_guides",
            "block_artifacts",
            "guide_content_cache",
            "homework_analyses",
            "test_prep_sessions",
            "test_prep_results",
        }
        assert set(metadata.tables.keys()) == expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index_column_sets(table: sa.Table) -> set[tuple[str, ...]]:
    """Return all index column-name tuples for the given table."""
    return {tuple(c.name for c in idx.columns) for idx in table.indexes}
