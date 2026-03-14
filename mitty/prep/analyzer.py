"""Homework image analysis pipeline using Claude Vision.

Orchestrates: fetch submission attachments -> download PDFs -> convert to
page images -> parallel vision analysis (Semaphore(3)) -> store results
in ``homework_analyses``.

Cache check skips already-analyzed pages.  Graceful partial failure: if
one page fails, the pipeline continues with the remaining pages and returns
whatever succeeded.

Traces: DEC-002 (parallel semaphore), DEC-007 (wrap_user_input for student
content).

Public API:
    analyze_homework_set(assignment_ids, course_id, user_id, ai_client,
                         supabase_client) -> list[dict]
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mitty.ai.prompts import get_prompt, wrap_user_input
from mitty.canvas.extract import download_file_content, pdf_pages_to_images
from mitty.canvas.fetcher import fetch_submission_attachments

if TYPE_CHECKING:
    from mitty.ai.client import AIClient
    from mitty.canvas.client import CanvasClient
    from supabase import AsyncClient

logger = logging.getLogger(__name__)

# Maximum concurrent vision API calls (DEC-002).
_MAX_CONCURRENT_VISION = 3

# Content types that indicate a PDF attachment.
_PDF_CONTENT_TYPES = {"application/pdf"}


# ---------------------------------------------------------------------------
# Pydantic model for structured vision output
# ---------------------------------------------------------------------------


class HomeworkPageAnalysis(BaseModel):
    """Structured result from vision analysis of a single homework page."""

    per_problem_json: list[dict[str, Any]] = Field(
        description=(
            "List of per-problem results, each with: problem_number (int), "
            "correctness (float 0.0-1.0), error_type (str|null), "
            "concept (str)."
        ),
    )
    analysis_json: dict[str, Any] = Field(
        description=(
            "Overall analysis summary with keys: overall (str), "
            "strengths (list[str]), areas_for_improvement (list[str])."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_pdf_attachment(attachment: dict[str, Any]) -> bool:
    """Return True if the attachment is a PDF based on content type or filename."""
    ct = attachment.get("content_type", "")
    if ct in _PDF_CONTENT_TYPES:
        return True
    filename = attachment.get("filename", "")
    return filename.lower().endswith(".pdf")


async def _get_cached_pages(
    supabase_client: AsyncClient,
    user_id: str,
    assignment_id: int,
) -> set[int]:
    """Return the set of page numbers already analyzed for this assignment."""
    try:
        result = (
            await supabase_client.table("homework_analyses")
            .select("assignment_id, page_number")
            .eq("user_id", user_id)
            .eq("assignment_id", assignment_id)
            .execute()
        )
        return {row["page_number"] for row in (result.data or [])}
    except Exception:
        logger.warning(
            "Cache check failed for assignment %d, will re-analyze all pages",
            assignment_id,
            exc_info=True,
        )
        return set()


async def _store_page_analysis(
    supabase_client: AsyncClient,
    *,
    user_id: str,
    assignment_id: int,
    course_id: int,
    page_number: int,
    analysis: HomeworkPageAnalysis,
) -> None:
    """Write a single page analysis row to homework_analyses."""
    row = {
        "user_id": user_id,
        "assignment_id": assignment_id,
        "course_id": course_id,
        "page_number": page_number,
        "analysis_json": {
            "per_problem": analysis.per_problem_json,
            "summary": analysis.analysis_json,
        },
        "analyzed_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    try:
        await supabase_client.table("homework_analyses").insert(row).execute()
    except Exception:
        logger.warning(
            "Failed to store analysis for assignment %d page %d",
            assignment_id,
            page_number,
            exc_info=True,
        )


async def _analyze_page(
    *,
    semaphore: asyncio.Semaphore,
    ai_client: AIClient,
    supabase_client: AsyncClient,
    image: bytes,
    assignment_id: int,
    course_id: int,
    user_id: str,
    page_number: int,
    prompt_config: Any,
) -> dict[str, Any] | None:
    """Analyze a single page image under the concurrency semaphore.

    Returns a result dict on success, or None on failure.
    """
    async with semaphore:
        try:
            user_prompt = prompt_config.user_template.replace(
                "{page_description}",
                wrap_user_input(f"Assignment {assignment_id}, page {page_number + 1}"),
            )

            analysis = await ai_client.call_vision(
                images=[image],
                system=prompt_config.system_prompt,
                user_prompt=user_prompt,
                response_model=HomeworkPageAnalysis,
                call_type="homework_analysis",
                user_id=user_id,
                supabase_client=supabase_client,
            )

            # Store in Supabase
            await _store_page_analysis(
                supabase_client,
                user_id=user_id,
                assignment_id=assignment_id,
                course_id=course_id,
                page_number=page_number,
                analysis=analysis,
            )

            return {
                "assignment_id": assignment_id,
                "page_number": page_number,
                "per_problem_json": analysis.per_problem_json,
                "analysis_json": analysis.analysis_json,
            }

        except Exception:
            logger.warning(
                "Vision analysis failed for assignment %d page %d",
                assignment_id,
                page_number,
                exc_info=True,
            )
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze_homework_set(
    *,
    assignment_ids: list[int],
    course_id: int,
    user_id: str,
    ai_client: AIClient,
    supabase_client: AsyncClient,
    canvas_client: CanvasClient | None = None,
) -> list[dict[str, Any]]:
    """Analyze submitted homework PDFs via vision for a set of assignments.

    Orchestration:
      1. Fetch submission attachments from Canvas.
      2. Filter to PDF attachments.
      3. Download each PDF and convert to page images.
      4. Check cache -- skip already-analyzed pages.
      5. Run vision analysis in parallel (Semaphore(3), DEC-002).
      6. Store results in ``homework_analyses``.

    Args:
        assignment_ids: Canvas assignment IDs to analyze.
        course_id: The Canvas course ID.
        user_id: Authenticated user ID.
        ai_client: AIClient for vision calls.
        supabase_client: Supabase client for cache checks and storage.
        canvas_client: Optional CanvasClient for fetching attachments.
            If None, fetch_submission_attachments is called directly
            (useful for testing with mocks).

    Returns:
        List of result dicts for successfully analyzed pages.  Each dict
        contains: assignment_id, page_number, per_problem_json,
        analysis_json.  Pages that failed are omitted (graceful partial
        failure).
    """
    if not assignment_ids:
        return []

    # Step 1: Fetch submission attachments
    attachments = await fetch_submission_attachments(
        canvas_client, course_id, assignment_ids
    )

    if not attachments:
        logger.info("No attachments found for assignments %s", assignment_ids)
        return []

    # Step 2: Filter to PDFs only
    pdf_attachments = [a for a in attachments if _is_pdf_attachment(a)]
    if not pdf_attachments:
        logger.info("No PDF attachments found for assignments %s", assignment_ids)
        return []

    # Load prompt configuration once
    prompt_config = get_prompt("homework_analyzer")
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_VISION)

    all_results: list[dict[str, Any]] = []

    for attachment in pdf_attachments:
        url = attachment.get("url", "")
        filename = attachment.get("filename", "unknown")

        if not url:
            logger.debug("Attachment %s has no URL, skipping", filename)
            continue

        # Step 3: Download PDF
        # Use an httpx client for download; canvas_client may be None in tests
        http_client = getattr(canvas_client, "_http", None)
        pdf_bytes = await download_file_content(http_client, url)

        if pdf_bytes is None:
            logger.warning("Download failed for %s, skipping", filename)
            continue

        # Step 3b: Convert to page images
        try:
            page_images = pdf_pages_to_images(pdf_bytes)
        except (ValueError, Exception):
            logger.warning(
                "PDF conversion failed for %s, skipping",
                filename,
                exc_info=True,
            )
            continue

        if not page_images:
            logger.debug("No pages extracted from %s", filename)
            continue

        # Determine assignment_id for this attachment
        # For simplicity, use the first assignment_id since Canvas returns
        # attachments per assignment via fetch_submission_attachments
        assignment_id = (
            assignment_ids[0] if len(assignment_ids) == 1 else assignment_ids[0]
        )

        # Step 4: Cache check
        cached_pages = await _get_cached_pages(supabase_client, user_id, assignment_id)

        # Step 5: Parallel vision analysis for uncached pages
        tasks = []
        for page_num, image in enumerate(page_images):
            if page_num in cached_pages:
                logger.debug(
                    "Page %d of assignment %d already cached, skipping",
                    page_num,
                    assignment_id,
                )
                continue

            tasks.append(
                _analyze_page(
                    semaphore=semaphore,
                    ai_client=ai_client,
                    supabase_client=supabase_client,
                    image=image,
                    assignment_id=assignment_id,
                    course_id=course_id,
                    user_id=user_id,
                    page_number=page_num,
                    prompt_config=prompt_config,
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks)
            # Filter out None (failed pages)
            all_results.extend(r for r in results if r is not None)

    logger.info(
        "Homework analysis complete: %d pages analyzed for %d assignments",
        len(all_results),
        len(assignment_ids),
    )
    return all_results
