"""High-level async fetch functions for Canvas LMS API endpoints.

Each function delegates pagination and HTTP handling to
:class:`~mitty.canvas.client.CanvasClient` and parses the raw JSON
responses into validated Pydantic models.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup

from mitty.canvas.client import CanvasAPIError, CanvasAuthError
from mitty.models import (
    Assignment,
    CalendarEvent,
    Course,
    DiscussionTopic,
    Enrollment,
    FileMetadata,
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

    The ``description`` HTML body is included in the response and stripped
    to plain text via :func:`strip_html`.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``Assignment`` model instances with plain-text
        descriptions.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/assignments",
        {"include[]": "submission", "per_page": "100"},
    )
    assignments: list[Assignment] = []
    for item in raw:
        assignment = Assignment.model_validate(item)
        if assignment.description:
            assignment = assignment.model_copy(
                update={"description": strip_html(assignment.description)}
            )
        assignments.append(assignment)
    return assignments


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


async def resolve_module_item_pages(
    client: CanvasClient,
    course_id: int,
    module_items: list[ModuleItem],
) -> dict[int, str]:
    """Fetch page bodies for module items of type ``Page``.

    For each module item with ``type="Page"`` and a non-empty ``page_url``,
    fetches the page body via the Canvas Pages API and strips the HTML to
    plain text.

    Failures on individual pages are logged as warnings and skipped so the
    pipeline continues.  A small delay between requests avoids hammering
    the Canvas API.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID the module items belong to.
        module_items: List of module items to inspect.

    Returns:
        Mapping of ``module_item.id`` to plain-text page body for items
        that were successfully resolved.
    """
    page_items = [
        item for item in module_items if item.type == "Page" and item.page_url
    ]
    if not page_items:
        return {}

    result: dict[int, str] = {}
    for item in page_items:
        try:
            response = await client.get(
                f"/api/v1/courses/{course_id}/pages/{item.page_url}",
            )
            data = response.json()
            body = data.get("body")
            if body:
                result[item.id] = strip_html(body)
            else:
                logger.debug(
                    "Page %r for module item %d has no body, skipping",
                    item.page_url,
                    item.id,
                )
        except Exception as exc:
            logger.warning(
                "Failed to resolve page %r for module item %d (course %d): %s",
                item.page_url,
                item.id,
                course_id,
                exc,
            )
    return result


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


async def fetch_files(
    client: CanvasClient,
    course_id: int,
) -> list[FileMetadata]:
    """Fetch all file metadata for a given course.

    Calls ``GET /api/v1/courses/:id/files?per_page=100``
    and parses each item into a :class:`~mitty.models.FileMetadata`.
    No file content is downloaded.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``FileMetadata`` model instances.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/files",
        {"per_page": "100"},
    )
    return [FileMetadata.model_validate(item) for item in raw]


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


async def fetch_discussion_topics(
    client: CanvasClient,
    course_id: int,
) -> list[DiscussionTopic]:
    """Fetch discussion topics for a given course, filtering to teacher posts.

    Calls ``GET /api/v1/courses/:id/discussion_topics?per_page=100``
    and parses each item into a :class:`~mitty.models.DiscussionTopic`.
    Only announcements and teacher-authored posts are returned; student
    replies are excluded by the endpoint itself (discussion_topics only
    returns top-level topics, not replies).

    HTML in the ``message`` field is stripped to plain text via
    :func:`strip_html`.

    Args:
        client: An authenticated Canvas API client.
        course_id: The Canvas course ID.

    Returns:
        A list of validated ``DiscussionTopic`` model instances with
        plain-text messages.
    """
    raw = await client.get_paginated(
        f"/api/v1/courses/{course_id}/discussion_topics",
        {"per_page": "100"},
    )
    topics: list[DiscussionTopic] = []
    for item in raw:
        topic = DiscussionTopic.model_validate(item)
        if topic.message:
            topic = topic.model_copy(update={"message": strip_html(topic.message)})
        topics.append(topic)
    return topics


async def fetch_all(
    client: CanvasClient,
    settings: Settings,
) -> dict:
    """Fetch courses, enrollments, and all per-course data concurrently.

    Courses and enrollments are fetched in parallel first.  Then each
    course's assignments, quizzes, modules (with items), pages, files,
    and discussion topics are fetched concurrently, bounded by
    ``settings.max_concurrent`` to avoid overwhelming the Canvas API.
    Calendar events are fetched once globally across all courses.

    If fetching data for a particular course fails, the error is logged
    and appended to the ``errors`` list in the result dict.  Other
    courses are unaffected.

    Args:
        client: An authenticated Canvas API client.
        settings: Application settings (used for ``max_concurrent``).

    Returns:
        A dict with keys ``courses``, ``assignments``, ``enrollments``,
        ``quizzes``, ``modules``, ``pages``, ``files``,
        ``discussion_topics``, ``calendar_events``, and ``errors``.

        Per-course data (assignments, quizzes, modules, pages, files,
        discussion_topics) is keyed by ``str(course_id)``.  The
        ``modules`` value contains dicts with ``"modules"``,
        ``"module_items"``, and ``"resolved_page_content"`` sub-keys.
        Assignments include plain-text ``description`` fields.
    """
    courses, enrollments = await asyncio.gather(
        fetch_courses(client),
        fetch_enrollments(client),
    )

    errors: list[str] = []
    assignments: dict[str, list[Assignment]] = {}
    quizzes: dict[str, list[Quiz]] = {}
    modules: dict[str, dict] = {}
    pages: dict[str, list[Page]] = {}
    files: dict[str, list[FileMetadata]] = {}
    discussion_topics: dict[str, list[DiscussionTopic]] = {}
    semaphore = asyncio.Semaphore(settings.max_concurrent)

    async def _fetch_or_empty(coro: Any, label: str, course: Course) -> Any:
        """Run a fetch coroutine, returning [] on 404/403 (feature disabled)."""
        try:
            return await coro
        except (CanvasAPIError, CanvasAuthError) as exc:
            exc_str = str(exc)
            if "404" in exc_str or "403" in exc_str:
                logger.debug(
                    "Skipping %s for course %d (%s): %s",
                    label,
                    course.id,
                    course.name,
                    exc,
                )
                return []
            raise

    async def _fetch_course_data(course: Course) -> dict:
        """Fetch all data types for a single course under the semaphore."""
        async with semaphore:
            course_assignments = await _fetch_or_empty(
                fetch_assignments(client, course.id), "assignments", course
            )
            course_quizzes = await _fetch_or_empty(
                fetch_quizzes(client, course.id), "quizzes", course
            )
            course_modules = await _fetch_or_empty(
                fetch_modules(client, course.id), "modules", course
            )

            # Fetch items for each module
            all_module_items: dict[int, list[ModuleItem]] = {}
            for mod in course_modules:
                items = await _fetch_or_empty(
                    fetch_module_items(client, course.id, mod.id),
                    f"module_items[{mod.id}]",
                    course,
                )
                all_module_items[mod.id] = items

            # Resolve page bodies for Page-type module items
            all_items_flat = [
                item for items_list in all_module_items.values() for item in items_list
            ]
            resolved_pages: dict[int, str] = {}
            if all_items_flat:
                try:
                    resolved_pages = await resolve_module_item_pages(
                        client, course.id, all_items_flat
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to resolve module item pages for course %d (%s): %s",
                        course.id,
                        course.name,
                        exc,
                    )

            course_pages = await _fetch_or_empty(
                fetch_pages(client, course.id), "pages", course
            )
            course_files = await _fetch_or_empty(
                fetch_files(client, course.id), "files", course
            )
            course_discussions = await _fetch_or_empty(
                fetch_discussion_topics(client, course.id),
                "discussion_topics",
                course,
            )

            return {
                "course_id": course.id,
                "assignments": course_assignments,
                "quizzes": course_quizzes,
                "modules": course_modules,
                "module_items": all_module_items,
                "resolved_page_content": resolved_pages,
                "pages": course_pages,
                "files": course_files,
                "discussion_topics": course_discussions,
            }

    tasks = [_fetch_course_data(c) for c in courses]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for course, result in zip(courses, results, strict=True):
        if isinstance(result, KeyboardInterrupt | SystemExit):
            raise result
        if isinstance(result, BaseException):
            error_msg = (
                f"Failed to fetch data for course "
                f"{course.id} ({course.name}): {result!r}"
            )
            logger.warning(error_msg)
            errors.append(error_msg)
        else:
            cid = str(result["course_id"])
            assignments[cid] = result["assignments"]
            quizzes[cid] = result["quizzes"]
            modules[cid] = {
                "modules": result["modules"],
                "module_items": result["module_items"],
                "resolved_page_content": result["resolved_page_content"],
            }
            pages[cid] = result["pages"]
            files[cid] = result["files"]
            discussion_topics[cid] = result["discussion_topics"]

    # Calendar events: fetch once globally for all courses
    course_ids = [c.id for c in courses]
    calendar_events: list[CalendarEvent] = []
    if course_ids:
        try:
            calendar_events = await fetch_calendar_events(client, course_ids)
        except Exception as exc:
            error_msg = f"Failed to fetch calendar events: {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)

    return {
        "courses": courses,
        "assignments": assignments,
        "enrollments": enrollments,
        "quizzes": quizzes,
        "modules": modules,
        "pages": pages,
        "files": files,
        "discussion_topics": discussion_topics,
        "calendar_events": calendar_events,
        "errors": errors,
    }
