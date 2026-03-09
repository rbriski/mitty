"""High-level async fetch functions for Canvas LMS API endpoints.

Each function delegates pagination and HTTP handling to
:class:`~mitty.canvas.client.CanvasClient` and parses the raw JSON
responses into validated Pydantic models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mitty.models import Assignment, Course, Enrollment

if TYPE_CHECKING:
    from mitty.canvas.client import CanvasClient


async def fetch_courses(client: CanvasClient) -> list[Course]:
    """Fetch all courses for the authenticated user.

    Calls ``GET /api/v1/courses?include[]=term&per_page=100`` and parses
    each item into a :class:`~mitty.models.Course`.

    Args:
        client: An authenticated Canvas API client.

    Returns:
        A list of validated ``Course`` model instances.
    """
    raw = await client.get_paginated(
        "/api/v1/courses",
        {"include[]": "term", "per_page": "100"},
    )
    return [Course.model_validate(item) for item in raw]


async def fetch_assignments(
    client: CanvasClient,
    course_id: int,
) -> list[Assignment]:
    """Fetch all assignments for a given course.

    Calls ``GET /api/v1/courses/:id/assignments?include[]=submission&per_page=100``
    and parses each item into an :class:`~mitty.models.Assignment`.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``Assignment`` model instances.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/assignments",
        {"include[]": "submission", "per_page": "100"},
    )
    return [Assignment.model_validate(item) for item in raw]


async def fetch_enrollments(client: CanvasClient) -> list[Enrollment]:
    """Fetch all enrollments for the authenticated user.

    Calls ``GET /api/v1/users/self/enrollments?include[]=current_points&per_page=100``
    and parses each item into an :class:`~mitty.models.Enrollment`.

    Args:
        client: An authenticated Canvas API client.

    Returns:
        A list of validated ``Enrollment`` model instances.
    """
    raw = await client.get_paginated(
        "/api/v1/users/self/enrollments",
        {"include[]": "current_points", "per_page": "100"},
    )
    return [Enrollment.model_validate(item) for item in raw]
