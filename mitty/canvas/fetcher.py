"""High-level async fetch functions for Canvas LMS API endpoints.

Each function delegates pagination and HTTP handling to
:class:`~mitty.canvas.client.CanvasClient` and parses the raw JSON
responses into validated Pydantic models.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from mitty.models import Assignment, Course, Enrollment, Module, ModuleItem

if TYPE_CHECKING:
    from mitty.canvas.client import CanvasClient
    from mitty.config import Settings

logger = logging.getLogger(__name__)


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
    # Canvas returns minimal stubs for access-restricted courses (e.g. past
    # semesters) that lack required fields like ``name``.  Skip them.
    return [
        Course.model_validate(item)
        for item in raw
        if not item.get("access_restricted_by_date")
    ]


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


async def fetch_modules(
    client: CanvasClient,
    course_id: int,
) -> list[Module]:
    """Fetch all modules for a given course.

    Calls ``GET /api/v1/courses/:id/modules?include[]=items&per_page=100``
    and parses each item into a :class:`~mitty.models.Module`.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``Module`` model instances.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/modules",
        {"include[]": "items", "per_page": "100"},
    )
    return [Module.model_validate(item) for item in raw]


async def fetch_module_items(
    client: CanvasClient,
    course_id: int,
    module_id: int,
) -> list[ModuleItem]:
    """Fetch all items within a specific module.

    Calls ``GET /api/v1/courses/:course_id/modules/:module_id/items?per_page=100``
    and parses each item into a :class:`~mitty.models.ModuleItem`.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.
        module_id: The Canvas module ID.

    Returns:
        A list of validated ``ModuleItem`` model instances.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/modules/{module_id}/items",
        {"per_page": "100"},
    )
    return [ModuleItem.model_validate(item) for item in raw]


async def fetch_all(
    client: CanvasClient,
    settings: Settings,
) -> dict:
    """Fetch courses, enrollments, and all per-course assignments concurrently.

    Courses and enrollments are fetched in parallel first.  Then each
    course's assignments are fetched concurrently, bounded by
    ``settings.max_concurrent`` to avoid overwhelming the Canvas API.

    If fetching assignments for a particular course fails, the error is
    logged and appended to the ``errors`` list in the result dict.  Other
    courses are unaffected.

    Args:
        client: An authenticated Canvas API client.
        settings: Application settings (used for ``max_concurrent``).

    Returns:
        A dict with keys ``courses``, ``assignments``, ``enrollments``,
        and ``errors``.  The ``assignments`` value is a dict mapping
        ``str(course_id)`` to a list of ``Assignment`` models.
    """
    courses, enrollments = await asyncio.gather(
        fetch_courses(client),
        fetch_enrollments(client),
    )

    errors: list[str] = []
    assignments: dict[str, list[Assignment]] = {}
    semaphore = asyncio.Semaphore(settings.max_concurrent)

    async def _fetch_course_assignments(course: Course) -> tuple[int, list[Assignment]]:
        async with semaphore:
            result = await fetch_assignments(client, course.id)
            return course.id, result

    tasks = [_fetch_course_assignments(c) for c in courses]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for course, result in zip(courses, results, strict=True):
        if isinstance(result, BaseException):
            error_msg = (
                f"Failed to fetch assignments for course "
                f"{course.id} ({course.name}): {result}"
            )
            logger.warning(error_msg)
            errors.append(error_msg)
        else:
            course_id, assignment_list = result
            assignments[str(course_id)] = assignment_list

    return {
        "courses": courses,
        "assignments": assignments,
        "enrollments": enrollments,
        "errors": errors,
    }
