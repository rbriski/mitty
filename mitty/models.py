"""Pydantic v2 data models for Canvas LMS API objects."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Term(BaseModel):
    """Canvas enrollment term."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class Course(BaseModel):
    """Canvas course.

    The ``term`` field is nullable because Canvas may omit it or return null
    depending on the include[] parameters used in the API request.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    course_code: str = ""
    term: Term | None = None
    workflow_state: str = ""


class Submission(BaseModel):
    """Canvas assignment submission.

    All scoring fields are nullable because unsubmitted or ungraded
    assignments will have null values.
    """

    model_config = ConfigDict(extra="ignore")

    score: float | None = None
    grade: str | None = None
    submitted_at: datetime | None = None
    workflow_state: str = "unsubmitted"
    late: bool = False
    missing: bool = False


class Assignment(BaseModel):
    """Canvas assignment, optionally including an embedded submission.

    When fetched with ``include[]=submission``, the API nests the student's
    submission inside the assignment object. The ``submission`` field is null
    when no submission data is available.

    The ``description`` field contains the assignment's body text (HTML stripped
    to plain text during fetch).
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    course_id: int
    due_at: datetime | None = None
    points_possible: float | None = None
    submission: Submission | None = None
    html_url: str = ""
    description: str | None = None


class Enrollment(BaseModel):
    """Canvas enrollment with optional nested grades.

    Canvas returns grades as a sub-object with keys like ``current_score``,
    ``current_grade``, ``final_score``, ``final_grade``.  We keep it as a
    plain dict to avoid coupling to every possible key Canvas might add.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    course_id: int
    type: str
    enrollment_state: str = ""
    grades: dict | None = None


class Quiz(BaseModel):
    """Canvas quiz."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    quiz_type: str = ""
    due_at: datetime | None = None
    points_possible: float | None = None
    time_limit: int | None = None
    assignment_id: int | None = None
    description: str | None = None


class Module(BaseModel):
    """Canvas course module."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    position: int = 0
    unlock_at: datetime | None = None
    items_count: int = 0


class ModuleItem(BaseModel):
    """Canvas module item (a single entry within a module)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    module_id: int
    title: str
    type: str
    content_id: int | None = None
    position: int = 0
    page_url: str | None = None
    external_url: str | None = None


class Page(BaseModel):
    """Canvas wiki page."""

    model_config = ConfigDict(extra="ignore")

    page_id: int
    title: str
    body: str | None = None
    url: str = ""
    published: bool = True


class FileMetadata(BaseModel):
    """Canvas file metadata."""

    model_config = ConfigDict(extra="ignore")

    id: int
    display_name: str
    content_type: str = ""
    size: int = 0
    url: str = ""
    folder_id: int | None = None


class CalendarEvent(BaseModel):
    """Canvas calendar event."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    context_type: str = ""
    context_code: str = ""


class DiscussionAuthor(BaseModel):
    """Canvas discussion topic author."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    display_name: str = ""


class DiscussionTopic(BaseModel):
    """Canvas discussion topic or announcement.

    Maps to the Canvas ``GET /api/v1/courses/:id/discussion_topics`` response.
    The ``message`` field contains the raw HTML body, which should be stripped
    to plain text before storage.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    message: str | None = None
    posted_at: datetime | None = None
    author: DiscussionAuthor | None = None
    is_announcement: bool = False
    discussion_type: str = ""
    html_url: str = ""
