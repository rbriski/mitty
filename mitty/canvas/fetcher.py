"""High-level async fetch functions for Canvas LMS API endpoints.

Each function delegates pagination and HTTP handling to
:class:`~mitty.canvas.client.CanvasClient` and parses the raw JSON
responses into validated Pydantic models.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from mitty.models import (
    Assignment,
    CalendarEvent,
    Course,
    Enrollment,
    Module,
    ModuleItem,
    Page,
    Quiz,
)

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


async def fetch_quizzes(
    client: CanvasClient,
    course_id: int,
) -> list[Quiz]:
    """Fetch all quizzes for a given course.

    Calls ``GET /api/v1/courses/:id/quizzes?per_page=100``
    and parses each item into a :class:`~mitty.models.Quiz`.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``Quiz`` model instances.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/quizzes",
        {"per_page": "100"},
    )
    return [Quiz.model_validate(item) for item in raw]


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


def strip_html(html: str) -> str:
    """Strip HTML to plain text, removing scripts and style tags.

    Uses BeautifulSoup to decompose ``<script>`` and ``<style>`` elements
    before extracting visible text with newline separators.

    Args:
        html: Raw HTML string.

    Returns:
        Plain text with tags, scripts, and styles removed.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


async def fetch_pages(
    client: CanvasClient,
    course_id: int,
) -> list[Page]:
    """Fetch all wiki pages for a given course, including HTML bodies.

    Calls ``GET /api/v1/courses/:id/pages?include[]=body&per_page=100``
    and parses each item into a :class:`~mitty.models.Page`.  The HTML body
    is stripped to plain text via :func:`strip_html` and stored back on the
    ``Page.body`` field.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``Page`` model instances with plain-text bodies.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/pages",
        {"include[]": "body", "per_page": "100"},
    )
    pages: list[Page] = []
    for item in raw:
        page = Page.model_validate(item)
        if page.body:
            page = page.model_copy(update={"body": strip_html(page.body)})
        pages.append(page)
    return pages


async def fetch_calendar_events(
    client: CanvasClient,
    course_ids: list[int],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[CalendarEvent]:
    """Fetch calendar events for the given courses.

    Calls ``GET /api/v1/calendar_events`` with ``context_codes[]`` set to
    ``course_<id>`` for each course ID and optional date range filtering.

    Args:
        client: An authenticated Canvas API client.
        course_ids: List of Canvas course IDs to fetch events for.
        start_date: Optional ISO-8601 start date filter.
        end_date: Optional ISO-8601 end date filter.

    Returns:
        A list of validated ``CalendarEvent`` model instances.
    """
    if not course_ids:
        return []

    params: dict[str, str] = {
        "per_page": "100",
    }
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    # Canvas expects multiple context_codes[] params; we pass a list and
    # let get_paginated handle list-valued params (or send them one by one).
    context_codes = [f"course_{cid}" for cid in course_ids]

    all_events: list[CalendarEvent] = []
    for code in context_codes:
        raw = await client.get_paginated(
            "/api/v1/calendar_events",
            {**params, "context_codes[]": code},
        )
        all_events.extend(CalendarEvent.model_validate(item) for item in raw)

    logger.info(
        "Fetched %d calendar events for %d courses", len(all_events), len(course_ids)
    )
    return all_events


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
