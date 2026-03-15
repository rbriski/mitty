"""SQLAlchemy Core table definitions for the Mitty database schema.

Defines 25 tables using ``sa.Table`` objects on a shared ``MetaData`` instance:

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
- **practice_items**: Generated practice questions/items (FKs -> courses).
- **practice_results**: Practice item outcomes (FKs -> study_blocks, courses).
- **ai_audit_log**: AI/LLM call audit trail (FK -> auth.users).
- **coach_messages**: Student-coach chat history (FKs -> auth.users, study_blocks).
- **escalation_log**: Detected escalation signals (FK -> auth.users).
- **flagged_responses**: Flagged coach responses for review (FKs -> coach_messages).
- **study_block_guides**: Compiled executable guides (FK -> study_blocks).
- **block_artifacts**: Student artifacts during guided study (FK -> study_blocks).
- **guide_content_cache**: Cached guide content keyed by concept + source hash.
- **homework_analyses**: Per-page homework image analysis (FKs -> assignments, courses).
- **test_prep_sessions**: Test prep session state (FKs -> courses, assessments).
- **test_prep_results**: Individual problem results within a session
  (FK -> test_prep_sessions).

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
    sa.Column("chapter", sa.Text, nullable=True),
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
        unique=True,
    ),
    sa.Column("canvas_quiz_id", sa.Integer, nullable=True, unique=True),
    sa.Column("canvas_event_id", sa.Integer, nullable=True, unique=True),
    sa.Column(
        "auto_created",
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    ),
    sa.Column("source", sa.String, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index("ix_assessments_canvas_quiz_id", assessments.c.canvas_quiz_id)
sa.Index("ix_assessments_canvas_event_id", assessments.c.canvas_event_id)
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
    sa.Column("content_text", sa.Text, nullable=True),
    sa.Column("canvas_item_id", sa.Integer, nullable=True, unique=True),
    sa.Column("module_name", sa.String, nullable=True),
    sa.Column("module_position", sa.Integer, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

sa.Index("ix_resources_canvas_item_id", resources.c.canvas_item_id)
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
# practice_items
# ---------------------------------------------------------------------------

practice_items = sa.Table(
    "practice_items",
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
    sa.Column("practice_type", sa.String, nullable=False),
    sa.Column("question_text", sa.Text, nullable=False),
    sa.Column("correct_answer", sa.Text, nullable=True),
    sa.Column("options_json", sa.JSON, nullable=True),
    sa.Column("explanation", sa.Text, nullable=True),
    sa.Column("source_chunk_ids", sa.ARRAY(sa.Integer), nullable=True),
    sa.Column("difficulty_level", sa.Float, nullable=True),
    sa.Column("generation_model", sa.String(255), nullable=True),
    sa.Column(
        "times_used",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("last_used_at", sa.DateTime, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_practice_items_user_course_concept",
    practice_items.c.user_id,
    practice_items.c.course_id,
    practice_items.c.concept,
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
    sa.Column("score", sa.Float, nullable=True),
    sa.Column("feedback", sa.Text, nullable=True),
    sa.Column("misconceptions_detected", sa.ARRAY(sa.String), nullable=True),
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
# Escalation detection: repeated-failure queries
sa.Index(
    "ix_practice_results_user_concept_correct",
    practice_results.c.user_id,
    practice_results.c.concept,
    practice_results.c.is_correct,
)

# Escalation detection: avoidance queries on study_blocks
sa.Index(
    "ix_study_blocks_plan_status",
    study_blocks.c.plan_id,
    study_blocks.c.status,
)

# ---------------------------------------------------------------------------
# ai_audit_log
# ---------------------------------------------------------------------------

ai_audit_log = sa.Table(
    "ai_audit_log",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column("call_type", sa.String, nullable=False),
    sa.Column("model", sa.String, nullable=False),
    sa.Column(
        "prompt_version", sa.String, nullable=False, server_default=sa.text("''")
    ),
    sa.Column("input_tokens", sa.Integer, nullable=False),
    sa.Column("output_tokens", sa.Integer, nullable=False),
    sa.Column("cost_usd", sa.Numeric(10, 8), nullable=False),
    sa.Column("duration_ms", sa.Integer, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("error_msg", sa.String, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_ai_audit_log_user_created",
    ai_audit_log.c.user_id,
    ai_audit_log.c.created_at.desc(),
)
sa.Index(
    "ix_ai_audit_log_call_type_created",
    ai_audit_log.c.call_type,
    ai_audit_log.c.created_at.desc(),
)

# ---------------------------------------------------------------------------
# coach_messages
# ---------------------------------------------------------------------------

coach_messages = sa.Table(
    "coach_messages",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "study_block_id",
        sa.Integer,
        sa.ForeignKey("study_blocks.id"),
        nullable=False,
    ),
    sa.Column("role", sa.String, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("sources_cited", sa.JSON, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_coach_messages_user_block_created",
    coach_messages.c.user_id,
    coach_messages.c.study_block_id,
    coach_messages.c.created_at.desc(),
)
sa.Index(
    "ix_coach_messages_block_created",
    coach_messages.c.study_block_id,
    coach_messages.c.created_at,
)

# ---------------------------------------------------------------------------
# escalation_log
# ---------------------------------------------------------------------------

escalation_log = sa.Table(
    "escalation_log",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column("signal_type", sa.String, nullable=False),
    sa.Column("concept", sa.String, nullable=True),
    sa.Column("context_data", sa.JSON, nullable=True),
    sa.Column("suggested_action", sa.String, nullable=True),
    sa.Column(
        "acknowledged",
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    ),
    sa.Column("acknowledged_at", sa.DateTime, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_escalation_log_user_created",
    escalation_log.c.user_id,
    escalation_log.c.created_at.desc(),
)
sa.Index(
    "ix_escalation_log_signal_created",
    escalation_log.c.signal_type,
    escalation_log.c.created_at.desc(),
)

# ---------------------------------------------------------------------------
# flagged_responses
# ---------------------------------------------------------------------------

flagged_responses = sa.Table(
    "flagged_responses",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "coach_message_id",
        sa.BigInteger,
        sa.ForeignKey("coach_messages.id"),
        nullable=False,
    ),
    sa.Column("reason", sa.String, nullable=False),
    sa.Column("flag_context", sa.JSON, nullable=True),
    sa.Column(
        "reviewed",
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    ),
    sa.Column("reviewed_at", sa.DateTime, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_flagged_responses_user_created",
    flagged_responses.c.user_id,
    flagged_responses.c.created_at.desc(),
)
sa.Index(
    "ix_flagged_responses_reviewed_created",
    flagged_responses.c.reviewed,
    flagged_responses.c.created_at.desc(),
)

# ---------------------------------------------------------------------------
# study_block_guides  (Phase 6 — executable block guides, DEC-005/DEC-009)
# ---------------------------------------------------------------------------

study_block_guides = sa.Table(
    "study_block_guides",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "block_id",
        sa.Integer,
        sa.ForeignKey("study_blocks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("concepts_json", sa.JSON, nullable=True),
    sa.Column("source_bundle_json", sa.JSON, nullable=True),
    sa.Column("steps_json", sa.JSON, nullable=True),
    sa.Column("warmup_items_json", sa.JSON, nullable=True),
    sa.Column("exit_items_json", sa.JSON, nullable=True),
    sa.Column("completion_criteria_json", sa.JSON, nullable=True),
    sa.Column("success_criteria_json", sa.JSON, nullable=True),
    sa.Column(
        "guide_version",
        sa.String,
        nullable=False,
        server_default=sa.text("'1.0'"),
    ),
    sa.Column("generated_at", sa.DateTime, nullable=False),
)

# ---------------------------------------------------------------------------
# block_artifacts  (Phase 6 — student artifacts during guided study, DEC-009)
# ---------------------------------------------------------------------------

block_artifacts = sa.Table(
    "block_artifacts",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "block_id",
        sa.Integer,
        sa.ForeignKey("study_blocks.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("step_number", sa.Integer, nullable=False),
    sa.Column("artifact_type", sa.String, nullable=False),
    sa.Column("content_json", sa.JSON, nullable=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index("ix_block_artifacts_block_id", block_artifacts.c.block_id)

# ---------------------------------------------------------------------------
# guide_content_cache  (Phase 6 — cached guide content, DEC-002/DEC-009)
# ---------------------------------------------------------------------------

guide_content_cache = sa.Table(
    "guide_content_cache",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("concept", sa.String, nullable=False),
    sa.Column("source_hash", sa.String, nullable=False),
    sa.Column("content_type", sa.String, nullable=False),
    sa.Column("content_json", sa.JSON, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_guide_content_cache_concept_source_hash",
    guide_content_cache.c.concept,
    guide_content_cache.c.source_hash,
    unique=True,
)

# ---------------------------------------------------------------------------
# homework_analyses
# ---------------------------------------------------------------------------

homework_analyses = sa.Table(
    "homework_analyses",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "assignment_id",
        sa.Integer,
        sa.ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=False,
    ),
    sa.Column("page_number", sa.Integer, nullable=False),
    sa.Column("analysis_json", sa.JSON, nullable=False),
    sa.Column("image_tokens", sa.Integer, nullable=True),
    sa.Column("analyzed_at", sa.DateTime, nullable=False),
    sa.UniqueConstraint("user_id", "assignment_id", "page_number"),
)

sa.Index(
    "ix_homework_analyses_user_assignment",
    homework_analyses.c.user_id,
    homework_analyses.c.assignment_id,
)

# ---------------------------------------------------------------------------
# test_prep_sessions  (DEC-006: UUID PK)
# ---------------------------------------------------------------------------

test_prep_sessions = sa.Table(
    "test_prep_sessions",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id"),
        nullable=False,
    ),
    sa.Column(
        "assessment_id",
        sa.Integer,
        sa.ForeignKey("assessments.id"),
        nullable=True,
    ),
    sa.Column("state_json", sa.JSON, nullable=False),
    sa.Column("started_at", sa.DateTime, nullable=False),
    sa.Column("completed_at", sa.DateTime, nullable=True),
    sa.Column(
        "total_problems",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "total_correct",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("duration_seconds", sa.Integer, nullable=True),
    sa.Column("phase_reached", sa.String, nullable=True),
    sa.Column(
        "session_type",
        sa.Text,
        nullable=False,
        server_default=sa.text("'full'"),
    ),
)

sa.Index(
    "ix_test_prep_sessions_user_started",
    test_prep_sessions.c.user_id,
    test_prep_sessions.c.started_at.desc(),
)
sa.Index(
    "ix_test_prep_sessions_course_started",
    test_prep_sessions.c.course_id,
    test_prep_sessions.c.started_at.desc(),
)

# ---------------------------------------------------------------------------
# test_prep_results  (DEC-008: denormalized user_id)
# ---------------------------------------------------------------------------

test_prep_results = sa.Table(
    "test_prep_results",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column(
        "session_id",
        sa.Uuid,
        sa.ForeignKey("test_prep_sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("concept", sa.String, nullable=False),
    sa.Column("problem_json", sa.JSON, nullable=False),
    sa.Column("student_answer", sa.String, nullable=True),
    sa.Column("is_correct", sa.Boolean, nullable=True),
    sa.Column("score", sa.Float, nullable=True),
    sa.Column("feedback", sa.Text, nullable=True),
    sa.Column(
        "hints_used",
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "worked_example_shown",
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
    ),
    sa.Column("time_spent_seconds", sa.Integer, nullable=True),
    sa.Column("difficulty", sa.Float, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

sa.Index(
    "ix_test_prep_results_session_created",
    test_prep_results.c.session_id,
    test_prep_results.c.created_at,
)
sa.Index(
    "ix_test_prep_results_user_concept_correct",
    test_prep_results.c.user_id,
    test_prep_results.c.concept,
    test_prep_results.c.is_correct,
)
sa.Index(
    "ix_test_prep_results_user_created",
    test_prep_results.c.user_id,
    test_prep_results.c.created_at.desc(),
)
