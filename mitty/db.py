"""SQLAlchemy Core table definitions for the Mitty database schema.

Defines 14 tables using ``sa.Table`` objects on a shared ``MetaData`` instance:

- **courses**: Canvas LMS courses with optional term info.
- **assignments**: Assignments belonging to a course (FK -> courses).
- **submissions**: 1:1 with assignment (PK = assignment_id, FK -> assignments).
- **enrollments**: Student enrollments in courses (FK -> courses).
- **grade_snapshots**: Time-series grade snapshots (FKs -> courses, enrollments).
- **app_config**: Application configuration (term, privilege thresholds).
- **assessments**: Tests, quizzes, essays, etc. (FK -> courses, assignments).
- **resources**: Study materials (FK -> courses).
- **resource_chunks**: Chunked content for retrieval (FK -> resources).
- **student_signals**: Daily student check-in data.
- **study_plans**: Daily study plans.
- **study_blocks**: Individual blocks within a study plan.
- **mastery_states**: Per-concept mastery tracking (FK -> courses).
- **practice_results**: Practice item outcomes (FKs -> study_blocks, courses).

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
    sa.Column("workflow_state", sa.String, nullable=True),
    sa.Column("term_id", sa.Integer, nullable=True),
    sa.Column("term_name", sa.String, nullable=True),
    sa.Column("updated_at", sa.DateTime, nullable=False),
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
    sa.Column("html_url", sa.String, nullable=True),
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
    sa.Column("late", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("missing", sa.Boolean, nullable=False, server_default=sa.text("false")),
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

# ---------------------------------------------------------------------------
# app_config
# ---------------------------------------------------------------------------

app_config = sa.Table(
    "app_config",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("current_term_name", sa.String, nullable=True),
    sa.Column("privilege_thresholds", sa.JSON, nullable=False),
    sa.Column("privilege_names", sa.JSON, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

# ---------------------------------------------------------------------------
# assessments
# ---------------------------------------------------------------------------

assessments = sa.Table(
    "assessments",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=False,
    ),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("assessment_type", sa.String, nullable=False),
    sa.Column("scheduled_date", sa.DateTime, nullable=True),
    sa.Column("weight", sa.Float, nullable=True),
    sa.Column("unit_or_topic", sa.String, nullable=True),
    sa.Column("description", sa.String, nullable=True),
    sa.Column(
        "canvas_assignment_id",
        sa.Integer,
        sa.ForeignKey("assignments.id"),
        nullable=True,
    ),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_assessments_course_scheduled",
    assessments.c.course_id,
    assessments.c.scheduled_date,
)
sa.Index("ix_assessments_scheduled_date", assessments.c.scheduled_date)

# ---------------------------------------------------------------------------
# resources
# ---------------------------------------------------------------------------

resources = sa.Table(
    "resources",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=False,
    ),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("resource_type", sa.String, nullable=False),
    sa.Column("source_url", sa.String, nullable=True),
    sa.Column("canvas_module_id", sa.Integer, nullable=True),
    sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_resources_course_type",
    resources.c.course_id,
    resources.c.resource_type,
)

# ---------------------------------------------------------------------------
# resource_chunks
# ---------------------------------------------------------------------------

resource_chunks = sa.Table(
    "resource_chunks",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "resource_id",
        sa.Integer,
        sa.ForeignKey("resources.id"),
        nullable=False,
    ),
    sa.Column("chunk_index", sa.Integer, nullable=False),
    sa.Column("content_text", sa.String, nullable=False),
    # In Supabase this is vector(1536) via pgvector; using LargeBinary as
    # a placeholder since pgvector types aren't available in SA Core.
    sa.Column("embedding_vector", sa.LargeBinary, nullable=True),
    sa.Column("token_count", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_resource_chunks_resource_chunk",
    resource_chunks.c.resource_id,
    resource_chunks.c.chunk_index,
    unique=True,
)

# ---------------------------------------------------------------------------
# student_signals
# ---------------------------------------------------------------------------

student_signals = sa.Table(
    "student_signals",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column("recorded_at", sa.DateTime, nullable=False),
    sa.Column("available_minutes", sa.Integer, nullable=False),
    sa.Column("confidence_level", sa.Integer, nullable=False),
    sa.Column("energy_level", sa.Integer, nullable=False),
    sa.Column("stress_level", sa.Integer, nullable=False),
    sa.Column("blockers", sa.String, nullable=True),
    sa.Column("preferences", sa.JSON, nullable=True),
    sa.Column("notes", sa.String, nullable=True),
)

sa.Index(
    "ix_student_signals_user_recorded",
    student_signals.c.user_id,
    student_signals.c.recorded_at.desc(),
)

# ---------------------------------------------------------------------------
# study_plans
# ---------------------------------------------------------------------------

study_plans = sa.Table(
    "study_plans",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column("plan_date", sa.Date, nullable=False),
    sa.Column("total_minutes", sa.Integer, nullable=False),
    sa.Column(
        "status",
        sa.String,
        nullable=False,
        server_default=sa.text("'draft'"),
    ),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_study_plans_user_date",
    study_plans.c.user_id,
    study_plans.c.plan_date.desc(),
)

# ---------------------------------------------------------------------------
# study_blocks
# ---------------------------------------------------------------------------

study_blocks = sa.Table(
    "study_blocks",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "plan_id",
        sa.Integer,
        sa.ForeignKey("study_plans.id"),
        nullable=False,
    ),
    sa.Column("block_type", sa.String, nullable=False),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("description", sa.String, nullable=True),
    sa.Column("target_minutes", sa.Integer, nullable=False),
    sa.Column("actual_minutes", sa.Integer, nullable=True),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=True,
    ),
    sa.Column(
        "assessment_id",
        sa.Integer,
        sa.ForeignKey("assessments.id"),
        nullable=True,
    ),
    sa.Column("sort_order", sa.Integer, nullable=False),
    sa.Column(
        "status",
        sa.String,
        nullable=False,
        server_default=sa.text("'pending'"),
    ),
    sa.Column("started_at", sa.DateTime, nullable=True),
    sa.Column("completed_at", sa.DateTime, nullable=True),
)

sa.Index(
    "ix_study_blocks_plan_sort",
    study_blocks.c.plan_id,
    study_blocks.c.sort_order,
)

# ---------------------------------------------------------------------------
# mastery_states
# ---------------------------------------------------------------------------

mastery_states = sa.Table(
    "mastery_states",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=False,
    ),
    sa.Column("concept", sa.String, nullable=False),
    sa.Column(
        "mastery_level",
        sa.Float,
        nullable=False,
        server_default=sa.text("0.0"),
    ),
    sa.Column("confidence_self_report", sa.Float, nullable=True),
    sa.Column("last_retrieval_at", sa.DateTime, nullable=True),
    sa.Column("next_review_at", sa.DateTime, nullable=True),
    sa.Column(
        "retrieval_count",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("success_rate", sa.Float, nullable=True),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_mastery_states_user_course",
    mastery_states.c.user_id,
    mastery_states.c.course_id,
)
sa.Index(
    "ix_mastery_states_user_review",
    mastery_states.c.user_id,
    mastery_states.c.next_review_at,
)
sa.Index(
    "ix_mastery_states_user_course_concept",
    mastery_states.c.user_id,
    mastery_states.c.course_id,
    mastery_states.c.concept,
    unique=True,
)

# ---------------------------------------------------------------------------
# practice_results
# ---------------------------------------------------------------------------

practice_results = sa.Table(
    "practice_results",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "study_block_id",
        sa.Integer,
        sa.ForeignKey("study_blocks.id"),
        nullable=True,
    ),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=False,
    ),
    sa.Column("concept", sa.String, nullable=True),
    sa.Column("practice_type", sa.String, nullable=False),
    sa.Column("question_text", sa.String, nullable=False),
    sa.Column("student_answer", sa.String, nullable=True),
    sa.Column("correct_answer", sa.String, nullable=True),
    sa.Column("is_correct", sa.Boolean, nullable=True),
    sa.Column("confidence_before", sa.Float, nullable=True),
    sa.Column("time_spent_seconds", sa.Integer, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_practice_results_user_course",
    practice_results.c.user_id,
    practice_results.c.course_id,
)
sa.Index(
    "ix_practice_results_user_created",
    practice_results.c.user_id,
    practice_results.c.created_at.desc(),
)
