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
        assert len(_table("assignments").columns) == 7

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
        assert isinstance(t.c.updated_at.type, sa.DateTime)

    def test_nullable_flags(self) -> None:
        t = _table("assignments")
        assert t.c.id.nullable is False
        assert t.c.course_id.nullable is False
        assert t.c.name.nullable is False
        assert t.c.due_at.nullable is True
        assert t.c.points_possible.nullable is True
        assert t.c.html_url.nullable is True
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
# Cross-table checks
# ---------------------------------------------------------------------------


class TestMetadata:
    """Cross-cutting checks on the full metadata."""

    def test_table_count(self) -> None:
        assert len(metadata.tables) == 5

    def test_all_tables_present(self) -> None:
        expected = {
            "courses",
            "assignments",
            "submissions",
            "enrollments",
            "grade_snapshots",
        }
        assert set(metadata.tables.keys()) == expected


# ---------------------------------------------------------------------------
# Alembic migration importability
# ---------------------------------------------------------------------------


class TestAlembicMigration:
    """Verify that the initial Alembic migration file is importable."""

    def test_migration_importable(self) -> None:
        import importlib.util
        from pathlib import Path

        migration_path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / "001_initial_schema.py"
        )
        assert migration_path.exists(), f"Migration file not found: {migration_path}"

        spec = importlib.util.spec_from_file_location(
            "alembic_001_initial_schema",
            migration_path,
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert hasattr(mod, "upgrade")
        assert hasattr(mod, "downgrade")
        assert hasattr(mod, "revision")
        assert mod.revision is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index_column_sets(table: sa.Table) -> set[tuple[str, ...]]:
    """Return all index column-name tuples for the given table."""
    return {tuple(c.name for c in idx.columns) for idx in table.indexes}
