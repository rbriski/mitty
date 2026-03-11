"""Pydantic v2 request/response schemas for the Mitty API.

Provides Create/Update/Response triplets for all data tables,
generic ListResponse wrapper, and ErrorDetail schema.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Generic wrappers
# ---------------------------------------------------------------------------


class ListResponse[T](BaseModel):
    """Paginated list wrapper."""

    data: list[T]
    total: int
    offset: int
    limit: int


class ErrorDetail(BaseModel):
    """Structured error response."""

    code: str
    message: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------


class AppConfigResponse(BaseModel):
    """Full app_config record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    current_term_name: str | None
    privilege_thresholds: list
    privilege_names: list
    created_at: datetime
    updated_at: datetime


class AppConfigUpdate(BaseModel):
    """Partial update for app_config."""

    current_term_name: str | None = None
    privilege_thresholds: list | None = None
    privilege_names: list | None = None


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

AssessmentType = Literal["test", "quiz", "essay", "lab", "project"]


class AssessmentCreate(BaseModel):
    """Create a new assessment."""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    name: str
    assessment_type: AssessmentType
    scheduled_date: datetime | None = None
    weight: float | None = None
    unit_or_topic: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    canvas_assignment_id: int | None = None


class AssessmentUpdate(BaseModel):
    """Partial update for an assessment."""

    name: str | None = None
    assessment_type: AssessmentType | None = None
    scheduled_date: datetime | None = None
    weight: float | None = None
    unit_or_topic: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    canvas_assignment_id: int | None = None


class AssessmentResponse(BaseModel):
    """Full assessment record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    name: str
    assessment_type: AssessmentType
    scheduled_date: datetime | None
    weight: float | None
    unit_or_topic: str | None
    description: str | None
    canvas_assignment_id: int | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------

ResourceType = Literal[
    "textbook_chapter", "canvas_page", "file", "link", "notes", "video"
]


class ResourceCreate(BaseModel):
    """Create a new resource."""

    model_config = ConfigDict(from_attributes=True)

    course_id: int
    title: str
    resource_type: ResourceType
    source_url: str | None = None
    canvas_module_id: int | None = None
    sort_order: int = 0


class ResourceUpdate(BaseModel):
    """Partial update for a resource."""

    title: str | None = None
    resource_type: ResourceType | None = None
    source_url: str | None = None
    canvas_module_id: int | None = None
    sort_order: int | None = None


class ResourceResponse(BaseModel):
    """Full resource record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    resource_type: ResourceType
    source_url: str | None
    canvas_module_id: int | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# ResourceChunk
# ---------------------------------------------------------------------------


class ResourceChunkCreate(BaseModel):
    """Create a new resource chunk."""

    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    chunk_index: int
    content_text: str
    token_count: int


class ResourceChunkUpdate(BaseModel):
    """Partial update for a resource chunk."""

    content_text: str | None = None
    token_count: int | None = None


class ResourceChunkResponse(BaseModel):
    """Full resource_chunk record (embedding_vector excluded)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int
    chunk_index: int
    content_text: str
    token_count: int
    created_at: datetime


# ---------------------------------------------------------------------------
# StudentSignal
# ---------------------------------------------------------------------------


class StudentSignalCreate(BaseModel):
    """Create a new student signal (daily check-in)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    available_minutes: int
    confidence_level: int = Field(ge=1, le=5)
    energy_level: int = Field(ge=1, le=5)
    stress_level: int = Field(ge=1, le=5)
    blockers: str | None = Field(default=None, max_length=2000)
    preferences: dict | None = None
    notes: str | None = Field(default=None, max_length=2000)


class StudentSignalUpdate(BaseModel):
    """Partial update for a student signal."""

    available_minutes: int | None = None
    confidence_level: int | None = Field(default=None, ge=1, le=5)
    energy_level: int | None = Field(default=None, ge=1, le=5)
    stress_level: int | None = Field(default=None, ge=1, le=5)
    blockers: str | None = Field(default=None, max_length=2000)
    preferences: dict | None = None
    notes: str | None = Field(default=None, max_length=2000)


class StudentSignalResponse(BaseModel):
    """Full student_signal record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    recorded_at: datetime
    available_minutes: int
    confidence_level: int
    energy_level: int
    stress_level: int
    blockers: str | None
    preferences: dict | None
    notes: str | None


# ---------------------------------------------------------------------------
# StudyPlan
# ---------------------------------------------------------------------------

PlanStatus = Literal["draft", "active", "completed", "skipped"]


class StudyPlanCreate(BaseModel):
    """Create a new study plan."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    plan_date: date
    total_minutes: int
    status: PlanStatus = "draft"


class StudyPlanUpdate(BaseModel):
    """Partial update for a study plan."""

    total_minutes: int | None = None
    status: PlanStatus | None = None


class StudyPlanResponse(BaseModel):
    """Full study_plan record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    plan_date: date
    total_minutes: int
    status: PlanStatus
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# StudyBlock
# ---------------------------------------------------------------------------

BlockType = Literal[
    "plan",
    "urgent_deliverable",
    "retrieval",
    "worked_example",
    "deep_explanation",
    "reflection",
]

BlockStatus = Literal["pending", "in_progress", "completed", "skipped"]


class StudyBlockCreate(BaseModel):
    """Create a new study block."""

    model_config = ConfigDict(from_attributes=True)

    plan_id: int
    block_type: BlockType
    title: str
    description: str | None = Field(default=None, max_length=2000)
    target_minutes: int
    actual_minutes: int | None = None
    course_id: int | None = None
    assessment_id: int | None = None
    sort_order: int
    status: BlockStatus = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None


class StudyBlockUpdate(BaseModel):
    """Partial update for a study block."""

    block_type: BlockType | None = None
    title: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    target_minutes: int | None = None
    actual_minutes: int | None = None
    course_id: int | None = None
    assessment_id: int | None = None
    sort_order: int | None = None
    status: BlockStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class StudyBlockResponse(BaseModel):
    """Full study_block record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    block_type: BlockType
    title: str
    description: str | None
    target_minutes: int
    actual_minutes: int | None
    course_id: int | None
    assessment_id: int | None
    sort_order: int
    status: BlockStatus
    started_at: datetime | None
    completed_at: datetime | None


# ---------------------------------------------------------------------------
# MasteryState
# ---------------------------------------------------------------------------


class MasteryStateCreate(BaseModel):
    """Create a new mastery state."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    course_id: int
    concept: str
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_self_report: float | None = Field(default=None, ge=0.0, le=1.0)
    last_retrieval_at: datetime | None = None
    next_review_at: datetime | None = None
    retrieval_count: int = 0
    success_rate: float | None = None


class MasteryStateUpdate(BaseModel):
    """Partial update for a mastery state."""

    concept: str | None = None
    mastery_level: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_self_report: float | None = Field(default=None, ge=0.0, le=1.0)
    last_retrieval_at: datetime | None = None
    next_review_at: datetime | None = None
    retrieval_count: int | None = None
    success_rate: float | None = None


class MasteryStateResponse(BaseModel):
    """Full mastery_state record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    course_id: int
    concept: str
    mastery_level: float
    confidence_self_report: float | None
    last_retrieval_at: datetime | None
    next_review_at: datetime | None
    retrieval_count: int
    success_rate: float | None
    updated_at: datetime


# ---------------------------------------------------------------------------
# PracticeResult
# ---------------------------------------------------------------------------

PracticeType = Literal[
    "quiz", "flashcard", "worked_example", "reflection", "explanation"
]


class PracticeResultCreate(BaseModel):
    """Create a new practice result."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    study_block_id: int | None = None
    course_id: int
    concept: str | None = None
    practice_type: PracticeType
    question_text: str = Field(max_length=5000)
    student_answer: str | None = Field(default=None, max_length=5000)
    correct_answer: str | None = Field(default=None, max_length=5000)
    is_correct: bool | None = None
    confidence_before: float | None = Field(default=None, ge=1.0, le=5.0)
    time_spent_seconds: int | None = None


class PracticeResultUpdate(BaseModel):
    """Partial update for a practice result."""

    student_answer: str | None = Field(default=None, max_length=5000)
    correct_answer: str | None = Field(default=None, max_length=5000)
    is_correct: bool | None = None
    confidence_before: float | None = Field(default=None, ge=1.0, le=5.0)
    time_spent_seconds: int | None = None


class PracticeResultResponse(BaseModel):
    """Full practice_result record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    study_block_id: int | None
    course_id: int
    concept: str | None
    practice_type: PracticeType
    question_text: str
    student_answer: str | None
    correct_answer: str | None
    is_correct: bool | None
    confidence_before: float | None
    time_spent_seconds: int | None
    created_at: datetime
