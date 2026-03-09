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
    course_code: str
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
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    course_id: int
    due_at: datetime | None = None
    points_possible: float | None = None
    submission: Submission | None = None
    html_url: str = ""


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
