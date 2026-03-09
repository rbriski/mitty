"""SQLAlchemy Core table definitions for the Mitty database schema.

Defines 5 tables using ``sa.Table`` objects on a shared ``MetaData`` instance:

- **courses**: Canvas LMS courses with optional term info.
- **assignments**: Assignments belonging to a course (FK -> courses).
- **submissions**: 1:1 with assignment (PK = assignment_id, FK -> assignments).
- **enrollments**: Student enrollments in courses (FK -> courses).
- **grade_snapshots**: Time-series grade snapshots (FKs -> courses, enrollments).

All nullable columns are explicitly marked per the project schema specification.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

# ---------------------------------------------------------------------------
# courses
# ---------------------------------------------------------------------------

courses = sa.Table(
    "courses",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("course_code", sa.String, nullable=False),
    sa.Column("term_id", sa.Integer, nullable=True),
    sa.Column("term_name", sa.String, nullable=True),
)

# ---------------------------------------------------------------------------
# assignments
# ---------------------------------------------------------------------------

assignments = sa.Table(
    "assignments",
    metadata,
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
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index("ix_assignments_course_id", assignments.c.course_id)

# ---------------------------------------------------------------------------
# submissions  (1:1 with assignment — PK is assignment_id, DEC-006)
# ---------------------------------------------------------------------------

submissions = sa.Table(
    "submissions",
    metadata,
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
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

# ---------------------------------------------------------------------------
# enrollments
# ---------------------------------------------------------------------------

enrollments = sa.Table(
    "enrollments",
    metadata,
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

sa.Index("ix_enrollments_course_id", enrollments.c.course_id)

# ---------------------------------------------------------------------------
# grade_snapshots  (time-series, FKs to courses + enrollments, DEC-012)
# ---------------------------------------------------------------------------

grade_snapshots = sa.Table(
    "grade_snapshots",
    metadata,
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

# DEC-013: composite FK index on (course_id, enrollment_id)
sa.Index(
    "ix_grade_snapshots_course_enrollment",
    grade_snapshots.c.course_id,
    grade_snapshots.c.enrollment_id,
)

# Time-series query index on scraped_at DESC
sa.Index(
    "ix_grade_snapshots_scraped_at",
    grade_snapshots.c.scraped_at.desc(),
)
