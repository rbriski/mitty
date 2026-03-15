"""Pydantic v2 request/response schemas for the Mitty API.

Provides Create/Update/Response triplets for all data tables,
generic ListResponse wrapper, ErrorDetail schema, and test-prep
request/response models (US-002).
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Calibration status type
# ---------------------------------------------------------------------------

CalibrationStatus = Literal[
    "well_calibrated", "over_confident", "under_confident", "unknown"
]

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

AssessmentType = Literal["test", "quiz", "essay", "lab", "project", "calendar_event"]


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
    canvas_quiz_id: int | None = None
    auto_created: bool = False
    source: str | None = None


class AssessmentUpdate(BaseModel):
    """Partial update for an assessment."""

    name: str | None = None
    assessment_type: AssessmentType | None = None
    scheduled_date: datetime | None = None
    weight: float | None = None
    unit_or_topic: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    canvas_assignment_id: int | None = None
    canvas_quiz_id: int | None = None
    auto_created: bool | None = None
    source: str | None = None


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
    canvas_quiz_id: int | None = None
    auto_created: bool = False
    source: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------

ResourceType = Literal[
    "textbook_chapter",
    "canvas_page",
    "file",
    "link",
    "notes",
    "video",
    "discussion",
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
    content_text: str | None = None
    canvas_item_id: int | None = None
    module_name: str | None = None
    module_position: int | None = None


class ResourceUpdate(BaseModel):
    """Partial update for a resource."""

    title: str | None = None
    resource_type: ResourceType | None = None
    source_url: str | None = None
    canvas_module_id: int | None = None
    sort_order: int | None = None
    content_text: str | None = None
    canvas_item_id: int | None = None
    module_name: str | None = None
    module_position: int | None = None


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
    content_text: str | None = None
    canvas_item_id: int | None = None
    module_name: str | None = None
    module_position: int | None = None
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

# Note: StudyPlanWithBlocksResponse is defined after StudyBlockResponse below.

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


class StudyPlanWithBlocksResponse(StudyPlanResponse):
    """Study plan with nested study blocks."""

    blocks: list[StudyBlockResponse] = []


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
    "multiple_choice",
    "fill_in_blank",
    "short_answer",
    "flashcard",
    "worked_example",
    "explanation",
]


# ---------------------------------------------------------------------------
# PracticeItem
# ---------------------------------------------------------------------------


class PracticeItemCreate(BaseModel):
    """Create a new practice item."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    course_id: int
    concept: str
    practice_type: PracticeType
    question_text: str = Field(max_length=10000)
    correct_answer: str | None = Field(default=None, max_length=10000)
    options_json: dict | list | None = None
    explanation: str | None = Field(default=None, max_length=10000)
    source_chunk_ids: list[int] | None = None
    difficulty_level: float | None = Field(default=None, ge=0.0, le=1.0)
    generation_model: str | None = Field(default=None, max_length=255)


class PracticeItemUpdate(BaseModel):
    """Partial update for a practice item."""

    concept: str | None = None
    practice_type: PracticeType | None = None
    question_text: str | None = Field(default=None, max_length=10000)
    correct_answer: str | None = Field(default=None, max_length=10000)
    options_json: dict | list | None = None
    explanation: str | None = Field(default=None, max_length=10000)
    source_chunk_ids: list[int] | None = None
    difficulty_level: float | None = Field(default=None, ge=0.0, le=1.0)
    generation_model: str | None = Field(default=None, max_length=255)
    times_used: int | None = None
    last_used_at: datetime | None = None


class PracticeItemResponse(BaseModel):
    """Full practice_item record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    course_id: int
    concept: str
    practice_type: PracticeType
    question_text: str
    correct_answer: str | None
    options_json: dict | list | None
    explanation: str | None
    source_chunk_ids: list[int] | None
    difficulty_level: float | None
    generation_model: str | None
    times_used: int
    last_used_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# PracticeResult
# ---------------------------------------------------------------------------


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
    score: float | None = None
    feedback: str | None = Field(default=None, max_length=10000)
    misconceptions_detected: list[str] | None = None


class PracticeResultUpdate(BaseModel):
    """Partial update for a practice result."""

    student_answer: str | None = Field(default=None, max_length=5000)
    correct_answer: str | None = Field(default=None, max_length=5000)
    is_correct: bool | None = None
    confidence_before: float | None = Field(default=None, ge=1.0, le=5.0)
    time_spent_seconds: int | None = None
    score: float | None = None
    feedback: str | None = Field(default=None, max_length=10000)
    misconceptions_detected: list[str] | None = None


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
    score: float | None
    feedback: str | None
    misconceptions_detected: list[str] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Practice Session orchestration schemas
# ---------------------------------------------------------------------------


class PracticeGenerateResponse(BaseModel):
    """Response from practice item generation."""

    concept: str
    course_id: int
    items: list[PracticeItemResponse]
    cached: bool = False
    needs_resources: bool = False


class EvaluateRequest(BaseModel):
    """Request to evaluate a student answer."""

    practice_item_id: int
    student_answer: str = Field(max_length=5000)
    confidence_before: float | None = Field(default=None, ge=1.0, le=5.0)
    study_block_id: int | None = None
    time_spent_seconds: int | None = None


class EvaluateResponse(BaseModel):
    """Response from answer evaluation."""

    practice_result_id: int
    is_correct: bool
    score: float
    feedback: str
    misconceptions_detected: list[str]


class MasteryUpdateRequest(BaseModel):
    """Request to batch-update mastery after a practice session."""

    study_block_id: int


class MasteryStateResult(BaseModel):
    """A single mastery state in the update response."""

    model_config = ConfigDict(from_attributes=True)

    concept: str
    course_id: int
    mastery_level: float
    success_rate: float | None
    confidence_self_report: float | None
    retrieval_count: int
    last_retrieval_at: datetime | None
    next_review_at: datetime | None


class MasteryUpdateResponse(BaseModel):
    """Response from mastery batch-update."""

    study_block_id: int
    mastery_states: list[MasteryStateResult]


# ---------------------------------------------------------------------------
# MasteryDashboard (read-only aggregate)
# ---------------------------------------------------------------------------


class MasteryConceptRow(BaseModel):
    """Aggregated mastery data for a single concept."""

    concept: str
    mastery_level: float
    confidence_self_report: float | None
    calibration_gap: float | None
    calibration_status: CalibrationStatus
    next_review_at: datetime | None
    last_retrieval_at: datetime | None
    retrieval_count: int
    success_rate: float | None
    has_resources: bool


class MasteryDashboardResponse(BaseModel):
    """Mastery dashboard for a single course."""

    course_id: int
    concepts: list[MasteryConceptRow]


class SessionHistoryEntry(BaseModel):
    """A single completed test prep session in the history list."""

    session_id: str
    started_at: datetime
    total_problems: int
    total_correct: int
    accuracy: float
    duration_seconds: int | None
    phase_reached: str | None
    session_type: str


class SessionHistoryResponse(BaseModel):
    """Response for the session history endpoint."""

    sessions: list[SessionHistoryEntry]
    trend_text: str | None = None


# ---------------------------------------------------------------------------
# AI Usage / Cost Summary
# ---------------------------------------------------------------------------


class CallTypeBreakdown(BaseModel):
    """Aggregated usage for a single call_type."""

    call_type: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AICostSummaryResponse(BaseModel):
    """Aggregated AI usage cost summary for a user."""

    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    breakdown: list[CallTypeBreakdown]


# ---------------------------------------------------------------------------
# Escalation + Flag
# ---------------------------------------------------------------------------


class EscalationResponse(BaseModel):
    """Full escalation_log record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_type: str
    concept: str | None
    context_data: dict | None
    suggested_action: str | None
    acknowledged: bool
    acknowledged_at: datetime | None
    created_at: datetime


class FlagCreate(BaseModel):
    """Request to flag a coach response."""

    reason: str = Field(max_length=500)


class FlaggedResponseResponse(BaseModel):
    """Full flagged_responses record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    coach_message_id: int
    reason: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Coach Chat
# ---------------------------------------------------------------------------


class ChatMessageCreate(BaseModel):
    """Request to send a message to the coach."""

    message: str = Field(max_length=5000)


class CoachMessageResponse(BaseModel):
    """A single coach chat message."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    study_block_id: int
    role: str  # 'student' | 'coach'
    content: str
    sources_cited: list[dict] | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Block Guide + Artifact (Phase 6)
# ---------------------------------------------------------------------------


class BlockGuideResponse(BaseModel):
    """Full study_block_guides record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    block_id: int
    concepts_json: list[dict] | None = None
    source_bundle_json: list[dict] | None = None
    steps_json: list[dict] | None = None
    warmup_items_json: list[dict] | None = None
    exit_items_json: list[dict] | None = None
    completion_criteria_json: dict | None = None
    success_criteria_json: list[str] | None = None
    guide_version: str
    generated_at: datetime


class BlockArtifactCreate(BaseModel):
    """Create a new block artifact."""

    step_number: int = Field(ge=1)
    artifact_type: str = Field(max_length=50)
    content_json: dict


class BlockArtifactResponse(BaseModel):
    """Full block_artifacts record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    block_id: int
    step_number: int
    artifact_type: str
    content_json: dict | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Test-Prep types  (US-002 / DEC-006 / DEC-008)
# ---------------------------------------------------------------------------

SessionPhase = Literal[
    "diagnostic",
    "focused_practice",
    "error_analysis",
    "mixed_test",
    "calibration",
]

TestPrepProblemType = Literal[
    "multiple_choice",
    "free_response",
    "worked_example",
    "error_analysis",
    "mixed",
    "calibration",
]

ErrorType = Literal[
    "conceptual",
    "procedural",
    "careless",
    "incomplete",
    "unknown",
    "arithmetic",
    "sign",
    "transcription",
]

AnalysisStatus = Literal[
    "started",
    "page_complete",
    "analyzing",
    "complete",
    "error",
]


# ---------------------------------------------------------------------------
# Homework Analysis
# ---------------------------------------------------------------------------


class HomeworkProblemDetail(BaseModel):
    """Single problem extracted from homework analysis."""

    problem_number: int = Field(ge=1)
    correctness: float = Field(ge=0.0, le=1.0)
    error_type: ErrorType | None = None
    concept: str | None = None


class HomeworkAnalysisTrigger(BaseModel):
    """POST request to trigger homework analysis."""

    assignment_id: int
    course_id: int


class HomeworkAnalysisResponse(BaseModel):
    """GET response for a completed homework analysis."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID
    assignment_id: int
    course_id: int
    page_number: int
    analysis_json: dict
    image_tokens: int | None = None
    analyzed_at: datetime
    per_problem_json: list[HomeworkProblemDetail] | None = None


# ---------------------------------------------------------------------------
# Homework Analysis SSE Progress
# ---------------------------------------------------------------------------


class AnalysisProgressEvent(BaseModel):
    """SSE event for homework analysis progress."""

    status: AnalysisStatus
    page_number: int | None = None
    total_pages: int | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# Test Prep Session (DEC-006: UUID PK, DEC-008: server-authoritative state)
# ---------------------------------------------------------------------------


class TestPrepSessionCreate(BaseModel):
    """POST request to create a new test prep session."""

    course_id: int
    assessment_id: int | None = None
    concepts: list[str] = Field(min_length=1, max_length=50)


class TestPrepSessionResponse(BaseModel):
    """GET response for a test prep session."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    course_id: int
    assessment_id: int | None = None
    state_json: dict
    started_at: datetime
    completed_at: datetime | None = None
    total_problems: int = 0
    total_correct: int = 0
    duration_seconds: int | None = None
    phase_reached: SessionPhase | None = None


# ---------------------------------------------------------------------------
# Test Prep Problem
# ---------------------------------------------------------------------------


class TestPrepProblem(BaseModel):
    """A single problem presented to the student during a test prep session."""

    id: int = Field(
        description="Problem identifier (sequence key from test_prep_results)"
    )
    problem_type: TestPrepProblemType
    concept: str
    difficulty: float = Field(ge=0.0, le=1.0)
    prompt: str = Field(max_length=10000)
    choices: list[str] | None = None
    correct_answer: str | None = Field(default=None, max_length=10000)


# ---------------------------------------------------------------------------
# Test Prep Answer Submit / Result
# ---------------------------------------------------------------------------


class TestPrepAnswerSubmit(BaseModel):
    """POST request to submit an answer for a test prep problem."""

    session_id: UUID
    problem_id: int
    student_answer: str = Field(max_length=5000)
    time_spent_seconds: int | None = Field(default=None, ge=0)


class TestPrepAnswerResult(BaseModel):
    """Response after evaluating a submitted answer."""

    is_correct: bool
    score: float = Field(ge=0.0, le=1.0)
    explanation: str
    next_problem: TestPrepProblem | None = None


# ---------------------------------------------------------------------------
# Test Prep Mastery Profile
# ---------------------------------------------------------------------------


class TestPrepMasteryProfile(BaseModel):
    """Per-concept mastery summary for a test prep session."""

    concept: str
    mastery_level: float = Field(ge=0.0, le=1.0)
    problems_attempted: int = Field(ge=0)
    problems_correct: int = Field(ge=0)
    avg_time_seconds: float | None = None
    error_types: list[ErrorType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Test Prep Session Summary
# ---------------------------------------------------------------------------


class PhaseScore(BaseModel):
    """Score breakdown for a single session phase."""

    phase: SessionPhase
    total: int = Field(ge=0)
    correct: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)


class TestPrepSessionSummary(BaseModel):
    """End-of-session summary for a test prep session."""

    session_id: UUID
    phase_scores: list[PhaseScore]
    total_correct: int = Field(ge=0)
    total_problems: int = Field(ge=0)
    duration_seconds: int | None = None
    mastery_profile: list[TestPrepMasteryProfile] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
