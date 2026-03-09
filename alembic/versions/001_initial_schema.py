"""Initial schema — 5 tables for Canvas LMS data.

Revision ID: 001
Revises: (none)
Create Date: 2026-03-09

Tables:
    courses, assignments, submissions, enrollments, grade_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Alembic revision identifiers.
revision: str = "001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create all 5 tables and their indexes."""

    # --- courses ---
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("course_code", sa.String, nullable=False),
        sa.Column("workflow_state", sa.String, nullable=True),
        sa.Column("term_id", sa.Integer, nullable=True),
        sa.Column("term_name", sa.String, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- assignments ---
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("due_at", sa.DateTime, nullable=True),
        sa.Column("points_possible", sa.Float, nullable=True),
        sa.Column("html_url", sa.String, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_assignments_course_id",
        "assignments",
        ["course_id"],
    )

    # --- submissions (1:1 with assignment, PK = assignment_id) ---
    op.create_table(
        "submissions",
        sa.Column(
            "assignment_id",
            sa.Integer,
            sa.ForeignKey("assignments.id"),
            primary_key=True,
        ),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("grade", sa.String, nullable=True),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
        sa.Column("workflow_state", sa.String, nullable=True),
        sa.Column("late", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "missing", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- enrollments ---
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("enrollment_state", sa.String, nullable=False),
        sa.Column("current_score", sa.Float, nullable=True),
        sa.Column("current_grade", sa.String, nullable=True),
        sa.Column("final_score", sa.Float, nullable=True),
        sa.Column("final_grade", sa.String, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_enrollments_course_id",
        "enrollments",
        ["course_id"],
    )

    # --- grade_snapshots ---
    op.create_table(
        "grade_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.Integer,
            sa.ForeignKey("enrollments.id"),
            nullable=False,
        ),
        sa.Column("current_score", sa.Float, nullable=True),
        sa.Column("current_grade", sa.String, nullable=True),
        sa.Column("final_score", sa.Float, nullable=True),
        sa.Column("final_grade", sa.String, nullable=True),
        sa.Column("scraped_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_grade_snapshots_course_enrollment",
        "grade_snapshots",
        ["course_id", "enrollment_id"],
    )
    op.create_index(
        "ix_grade_snapshots_scraped_at",
        "grade_snapshots",
        [sa.text("scraped_at DESC")],
    )


def downgrade() -> None:
    """Drop all 5 tables in reverse dependency order."""
    op.drop_table("grade_snapshots")
    op.drop_table("submissions")
    op.drop_table("enrollments")
    op.drop_table("assignments")
    op.drop_table("courses")
