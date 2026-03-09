"""Tests for mitty.__main__ — CLI entry point."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.canvas.client import CanvasAuthError
from mitty.config import Settings
from mitty.models import Assignment, Course, Enrollment


def _make_settings() -> Settings:
    """Create a Settings instance with a fake token for testing."""
    return Settings(canvas_token="fake-token")


def _make_fetch_all_result() -> dict:
    """Build a minimal fetch_all return value with real pydantic models."""
    courses = [Course(id=1, name="Math", course_code="MATH-101")]
    assignments = {
        "1": [Assignment(id=10, name="HW 1", course_id=1)],
    }
    enrollments = [Enrollment(id=100, course_id=1, type="StudentEnrollment")]
    return {
        "courses": courses,
        "assignments": assignments,
        "enrollments": enrollments,
        "errors": [],
    }


class TestMainOutputsJSON:
    """main() should output valid JSON to stdout on success."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_outputs_valid_json(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False
        )
        mock_load_settings.return_value = _make_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

        # Set up async context manager
        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from mitty.__main__ import main

        await main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert "courses" in output
        assert "assignments" in output
        assert "enrollments" in output
        assert "errors" in output
        assert len(output["courses"]) == 1
        assert output["courses"][0]["name"] == "Math"
        assert len(output["assignments"]["1"]) == 1
        assert output["enrollments"][0]["type"] == "StudentEnrollment"


class TestMissingToken:
    """Missing CANVAS_TOKEN should print error to stderr and exit non-zero."""

    @patch("mitty.__main__.parse_args")
    @patch("mitty.__main__.load_settings")
    async def test_missing_token_exits_nonzero(
        self,
        mock_load_settings: MagicMock,
        mock_parse_args: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False
        )
        mock_load_settings.side_effect = ValueError(
            "CANVAS_TOKEN environment variable is required"
        )

        from mitty.__main__ import main

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "CANVAS_TOKEN" in captured.err


class TestCanvasAuthError:
    """CanvasAuthError should print error to stderr and exit non-zero."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_auth_error_exits_nonzero(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False
        )
        mock_load_settings.return_value = _make_settings()
        mock_fetch_all.side_effect = CanvasAuthError(
            "Canvas authentication failed: 401 Unauthorized"
        )

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from mitty.__main__ import main

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert (
            "authentication" in captured.err.lower() or "auth" in captured.err.lower()
        )


class TestNoCacheFlag:
    """--no-cache flag should disable caching in settings."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_no_cache_disables_cache(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=True, verbose=False, debug=False
        )
        settings = _make_settings()
        assert settings.cache_enabled is True  # Sanity: default is True
        mock_load_settings.return_value = settings
        mock_fetch_all.return_value = _make_fetch_all_result()

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from mitty.__main__ import main

        await main()

        # fetch_all receives settings — check what CanvasClient was called with
        call_args = mock_canvas_client_cls.call_args
        passed_settings = call_args[0][0]
        assert passed_settings.cache_enabled is False


class TestVerboseFlag:
    """--verbose flag should set log level to INFO."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_verbose_sets_info_level(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=True, debug=False
        )
        mock_load_settings.return_value = _make_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from mitty.__main__ import main

        await main()

        mitty_logger = logging.getLogger("mitty")
        assert mitty_logger.level == logging.INFO


class TestDebugFlag:
    """--debug flag should set log level to DEBUG."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_debug_sets_debug_level(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=True
        )
        mock_load_settings.return_value = _make_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from mitty.__main__ import main

        await main()

        mitty_logger = logging.getLogger("mitty")
        assert mitty_logger.level == logging.DEBUG
