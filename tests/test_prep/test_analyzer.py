"""Tests for mitty.prep.analyzer — homework image analysis pipeline.

Covers: full pipeline, cache hits, partial failure, and semaphore concurrency.

Traces: DEC-002 (parallel semaphore), DEC-007 (wrap_user_input).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from mitty.prep.analyzer import (
    HomeworkPageAnalysis,
    analyze_homework_set,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_supabase_client(
    *,
    existing_pages: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Supabase client.

    Supabase client's ``table()`` is synchronous; only ``.execute()`` is async.

    Args:
        existing_pages: Rows returned by the cache lookup query.
            Each dict should have ``assignment_id`` and ``page_number``.
    """
    client = MagicMock()

    # Cache check: .table("homework_analyses").select(...).eq(...).eq(...).execute()
    cache_result = MagicMock()
    cache_result.data = existing_pages or []

    # Build a fluent chain mock that supports repeated .eq() calls
    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.execute = AsyncMock(return_value=cache_result)

    # Insert chain: .table("homework_analyses").insert({...}).execute()
    insert_chain = MagicMock()
    insert_chain.execute = AsyncMock(return_value=MagicMock(data=[{"id": 1}]))

    table_mock = MagicMock()
    table_mock.select.return_value = select_chain
    table_mock.insert.return_value = insert_chain

    client.table.return_value = table_mock
    return client


def _mock_ai_client(
    response: HomeworkPageAnalysis | None = None,
    side_effect: Exception | None = None,
) -> AsyncMock:
    """Build a mock AIClient for call_vision."""
    ai = AsyncMock()
    if side_effect is not None:
        ai.call_vision = AsyncMock(side_effect=side_effect)
    else:
        ai.call_vision = AsyncMock(
            return_value=response
            or HomeworkPageAnalysis(
                per_problem_json=[
                    {
                        "problem_number": 1,
                        "correctness": 0.9,
                        "error_type": None,
                        "concept": "linear equations",
                    }
                ],
                analysis_json={
                    "overall": "Good work",
                    "strengths": ["clear steps"],
                    "areas_for_improvement": [],
                },
            )
        )
    return ai


def _fake_attachments() -> list[dict]:
    """Return fake attachment dicts as fetch_submission_attachments would."""
    return [
        {
            "url": "https://mitty.instructure.com/files/1/download",
            "filename": "hw1.pdf",
            "content_type": "application/pdf",
            "size": 1024,
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Happy path: fetch -> download -> convert -> analyze -> store."""

    @patch("mitty.prep.analyzer.pdf_pages_to_images")
    @patch("mitty.prep.analyzer.download_file_content")
    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_full_pipeline(
        self,
        mock_fetch: AsyncMock,
        mock_download: AsyncMock,
        mock_pdf_to_images: MagicMock,
    ) -> None:
        # Setup mocks
        mock_fetch.return_value = _fake_attachments()
        mock_download.return_value = b"%PDF-fake-content"
        mock_pdf_to_images.return_value = [b"png-page-1", b"png-page-2"]

        ai_client = _mock_ai_client()
        supabase_client = _mock_supabase_client()

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        # Should have results for 2 pages
        assert len(results) == 2

        # Vision was called once per page
        assert ai_client.call_vision.call_count == 2

        # Each result has expected keys
        for r in results:
            assert "assignment_id" in r
            assert "page_number" in r
            assert "per_problem_json" in r
            assert "analysis_json" in r

        # Supabase insert was called for each page
        assert supabase_client.table.return_value.insert.call_count == 2

        # Verify wrap_user_input was used in the user prompt
        for call in ai_client.call_vision.call_args_list:
            user_prompt = call.kwargs["user_prompt"]
            assert "<user_input>" in user_prompt
            assert "</user_input>" in user_prompt


class TestCacheHit:
    """Already-analyzed pages are skipped via cache check."""

    @patch("mitty.prep.analyzer.pdf_pages_to_images")
    @patch("mitty.prep.analyzer.download_file_content")
    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_cache_hit(
        self,
        mock_fetch: AsyncMock,
        mock_download: AsyncMock,
        mock_pdf_to_images: MagicMock,
    ) -> None:
        mock_fetch.return_value = _fake_attachments()
        mock_download.return_value = b"%PDF-fake-content"
        # 3 pages in PDF
        mock_pdf_to_images.return_value = [
            b"png-page-1",
            b"png-page-2",
            b"png-page-3",
        ]

        ai_client = _mock_ai_client()
        # Pages 0 and 2 already analyzed
        supabase_client = _mock_supabase_client(
            existing_pages=[
                {"assignment_id": 101, "page_number": 0},
                {"assignment_id": 101, "page_number": 2},
            ]
        )

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        # Only page 1 should be analyzed (pages 0 and 2 cached)
        assert ai_client.call_vision.call_count == 1
        # We still get a result for the one new page
        assert len(results) == 1
        assert results[0]["page_number"] == 1


class TestPartialFailure:
    """One page vision call fails, others succeed."""

    @patch("mitty.prep.analyzer.pdf_pages_to_images")
    @patch("mitty.prep.analyzer.download_file_content")
    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_partial_failure(
        self,
        mock_fetch: AsyncMock,
        mock_download: AsyncMock,
        mock_pdf_to_images: MagicMock,
    ) -> None:
        mock_fetch.return_value = _fake_attachments()
        mock_download.return_value = b"%PDF-fake-content"
        mock_pdf_to_images.return_value = [
            b"png-page-1",
            b"png-page-2",
            b"png-page-3",
        ]

        success_response = HomeworkPageAnalysis(
            per_problem_json=[
                {
                    "problem_number": 1,
                    "correctness": 1.0,
                    "error_type": None,
                    "concept": "algebra",
                }
            ],
            analysis_json={"overall": "Good"},
        )

        ai_client = AsyncMock()
        # Page 0 succeeds, page 1 fails, page 2 succeeds
        ai_client.call_vision = AsyncMock(
            side_effect=[
                success_response,
                RuntimeError("Vision API timeout"),
                success_response,
            ]
        )
        supabase_client = _mock_supabase_client()

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        # 2 out of 3 pages succeeded
        assert len(results) == 2
        # All 3 pages were attempted
        assert ai_client.call_vision.call_count == 3
        # Only 2 inserts (the successful ones)
        assert supabase_client.table.return_value.insert.call_count == 2


class TestParallelSemaphore:
    """Confirms max 3 concurrent vision calls (DEC-002)."""

    @patch("mitty.prep.analyzer.pdf_pages_to_images")
    @patch("mitty.prep.analyzer.download_file_content")
    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_parallel_semaphore(
        self,
        mock_fetch: AsyncMock,
        mock_download: AsyncMock,
        mock_pdf_to_images: MagicMock,
    ) -> None:
        mock_fetch.return_value = _fake_attachments()
        mock_download.return_value = b"%PDF-fake-content"
        # 6 pages to test concurrency limiting
        mock_pdf_to_images.return_value = [b"png"] * 6

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        success_response = HomeworkPageAnalysis(
            per_problem_json=[
                {
                    "problem_number": 1,
                    "correctness": 1.0,
                    "error_type": None,
                    "concept": "test",
                }
            ],
            analysis_json={"overall": "OK"},
        )

        async def _tracked_call(**kwargs):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            # Simulate some work
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return success_response

        ai_client = AsyncMock()
        ai_client.call_vision = AsyncMock(side_effect=_tracked_call)
        supabase_client = _mock_supabase_client()

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        assert len(results) == 6
        # Semaphore should limit concurrency to at most 3
        assert max_concurrent <= 3


class TestNoAttachments:
    """No attachments returns empty results."""

    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_no_attachments(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = []
        ai_client = _mock_ai_client()
        supabase_client = _mock_supabase_client()

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        assert results == []
        ai_client.call_vision.assert_not_called()


class TestDownloadFailure:
    """Download failure for a file skips it gracefully."""

    @patch("mitty.prep.analyzer.pdf_pages_to_images")
    @patch("mitty.prep.analyzer.download_file_content")
    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_download_failure(
        self,
        mock_fetch: AsyncMock,
        mock_download: AsyncMock,
        mock_pdf_to_images: MagicMock,
    ) -> None:
        mock_fetch.return_value = _fake_attachments()
        mock_download.return_value = None  # download failed
        mock_pdf_to_images.return_value = []

        ai_client = _mock_ai_client()
        supabase_client = _mock_supabase_client()

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        assert results == []
        ai_client.call_vision.assert_not_called()


class TestNonPdfSkipped:
    """Non-PDF attachments are skipped."""

    @patch("mitty.prep.analyzer.fetch_submission_attachments")
    async def test_non_pdf_skipped(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = [
            {
                "url": "https://mitty.instructure.com/files/1/download",
                "filename": "notes.docx",
                "content_type": (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
                "size": 1024,
            },
        ]
        ai_client = _mock_ai_client()
        supabase_client = _mock_supabase_client()

        results = await analyze_homework_set(
            assignment_ids=[101],
            course_id=42,
            user_id="user-abc",
            ai_client=ai_client,
            supabase_client=supabase_client,
        )

        assert results == []
        ai_client.call_vision.assert_not_called()
