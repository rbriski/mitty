"""Tests for discussion topic fetching and storage pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from mitty.canvas.fetcher import fetch_discussion_topics, strip_html
from mitty.models import DiscussionAuthor, DiscussionTopic
from mitty.storage import (
    StorageError,
    upsert_discussions_as_resources,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    """Load a JSON fixture file and return a list of dicts."""
    return json.loads((FIXTURES / name).read_text())


def _mock_client() -> AsyncMock:
    """Build a mock AsyncClient with chained table().upsert().execute()."""
    client = AsyncMock()
    table_builder = MagicMock()
    upsert_builder = MagicMock()
    execute_result = MagicMock()
    execute_result.data = []

    upsert_builder.execute = AsyncMock(return_value=execute_result)
    table_builder.upsert = MagicMock(return_value=upsert_builder)
    client.table = MagicMock(return_value=table_builder)

    return client


# ------------------------------------------------------------------ #
#  fetch_discussion_topics
# ------------------------------------------------------------------ #


class TestFetchDiscussionTopics:
    """fetch_discussion_topics calls get_paginated and strips HTML."""

    async def test_parses_discussion_topics_from_fixture(self) -> None:
        raw = _load_fixture("discussion_topics.json")
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_discussion_topics(client, course_id=12345)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/12345/discussion_topics",
            {"per_page": "100"},
        )
        assert len(result) == 3
        assert all(isinstance(t, DiscussionTopic) for t in result)

        # First topic: announcement with HTML stripped
        t0 = result[0]
        assert t0.id == 11001
        assert t0.title == "Welcome & Introductions"
        assert t0.is_announcement is True
        assert "<" not in (t0.message or "")
        assert "Welcome to the Course!" in (t0.message or "")
        assert "favorite book" in (t0.message or "")
        assert isinstance(t0.author, DiscussionAuthor)
        assert t0.author.id == 42
        assert t0.author.display_name == "Mrs. Johnson"
        assert t0.posted_at is not None

        # Second topic: threaded discussion with script/style removed
        t1 = result[1]
        assert t1.id == 11002
        assert t1.is_announcement is False
        assert t1.discussion_type == "threaded"
        assert "alert" not in (t1.message or "")
        assert "color: red" not in (t1.message or "")
        assert "rhetorical strategies" in (t1.message or "")

        # Third topic: null message preserved
        t2 = result[2]
        assert t2.id == 11003
        assert t2.message is None
        assert t2.author is None

    async def test_empty_response_returns_empty_list(self) -> None:
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        result = await fetch_discussion_topics(client, course_id=99999)

        client.get_paginated.assert_called_once_with(
            "/api/v1/courses/99999/discussion_topics",
            {"per_page": "100"},
        )
        assert result == []

    async def test_uses_correct_course_id_in_path(self) -> None:
        """Verify the course_id is interpolated into the URL path."""
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=[])

        await fetch_discussion_topics(client, course_id=42)

        call_args = client.get_paginated.call_args
        assert call_args[0][0] == "/api/v1/courses/42/discussion_topics"

    async def test_null_message_preserved(self) -> None:
        """Topics with null message are returned with message=None."""
        raw = [
            {
                "id": 9001,
                "title": "Empty Discussion",
                "message": None,
                "is_announcement": False,
            }
        ]
        client = AsyncMock()
        client.get_paginated = AsyncMock(return_value=raw)

        result = await fetch_discussion_topics(client, course_id=99)

        assert len(result) == 1
        assert result[0].message is None


# ------------------------------------------------------------------ #
#  HTML stripping for discussions
# ------------------------------------------------------------------ #


class TestDiscussionHtmlStripping:
    """Verify HTML stripping works on discussion message content."""

    def test_strips_script_and_style_tags(self) -> None:
        html = (
            "<p>Read the article.</p>"
            "<script>alert('xss')</script>"
            "<style>.hidden { display: none; }</style>"
        )
        text = strip_html(html)
        assert "Read the article." in text
        assert "alert" not in text
        assert "display: none" not in text

    def test_strips_nested_html_tags(self) -> None:
        html = "<div><h2>Discussion</h2><p>Please <em>discuss</em> the topic.</p></div>"
        text = strip_html(html)
        assert "Discussion" in text
        assert "discuss" in text
        assert "<" not in text


# ------------------------------------------------------------------ #
#  upsert_discussions_as_resources
# ------------------------------------------------------------------ #


class TestUpsertDiscussionsAsResources:
    """upsert_discussions_as_resources stores topics as resource rows."""

    async def test_upserts_discussion_topics(self) -> None:
        client = _mock_client()
        topics = [
            DiscussionTopic(
                id=11001,
                title="Welcome",
                message="Hello everyone!",
                is_announcement=True,
                html_url="https://mitty.instructure.com/courses/1/discussion_topics/11001",
            ),
            DiscussionTopic(
                id=11002,
                title="Discussion Week 1",
                message="Discuss the reading.",
                is_announcement=False,
            ),
        ]

        result = await upsert_discussions_as_resources(client, topics, course_id=1)

        client.table.assert_called_once_with("resources")
        rows = client.table.return_value.upsert.call_args[0][0]
        assert len(rows) == 2

        # First row: uses html_url from topic
        row0 = rows[0]
        assert row0["course_id"] == 1
        assert row0["title"] == "Welcome"
        assert row0["resource_type"] == "discussion"
        assert row0["content_text"] == "Hello everyone!"
        assert row0["canvas_item_id"] == 2_000_000_000 + 11001
        assert (
            row0["source_url"]
            == "https://mitty.instructure.com/courses/1/discussion_topics/11001"
        )
        assert "created_at" in row0
        assert "updated_at" in row0

        # Second row: fallback source_url constructed
        row1 = rows[1]
        assert row1["title"] == "Discussion Week 1"
        assert row1["canvas_item_id"] == 2_000_000_000 + 11002
        assert (
            row1["source_url"]
            == "https://mitty.instructure.com/courses/1/discussion_topics/11002"
        )

        # Returns canvas_item_ids
        assert result == [2_000_000_000 + 11001, 2_000_000_000 + 11002]

    async def test_upsert_on_conflict_canvas_item_id(self) -> None:
        client = _mock_client()
        topics = [
            DiscussionTopic(id=1, title="Test"),
        ]

        await upsert_discussions_as_resources(client, topics, course_id=1)

        upsert_call = client.table.return_value.upsert
        kwargs = upsert_call.call_args[1]
        assert kwargs.get("on_conflict") == "canvas_item_id"

    async def test_empty_list_returns_empty(self) -> None:
        client = _mock_client()

        result = await upsert_discussions_as_resources(client, [], course_id=1)

        assert result == []
        client.table.assert_not_called()

    async def test_null_message_stored_as_none(self) -> None:
        client = _mock_client()
        topics = [
            DiscussionTopic(id=1, title="No Content", message=None),
        ]

        await upsert_discussions_as_resources(client, topics, course_id=1)

        rows = client.table.return_value.upsert.call_args[0][0]
        assert rows[0]["content_text"] is None

    async def test_api_failure_raises_storage_error(self) -> None:
        import pytest

        client = _mock_client()
        client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("API timeout")
        )
        topics = [DiscussionTopic(id=1, title="Test")]

        with pytest.raises(StorageError, match="API timeout"):
            await upsert_discussions_as_resources(client, topics, course_id=1)
