"""Tests for mitty.__main__ — CLI entry point."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mitty.canvas.client import CanvasAPIError, CanvasAuthError
from mitty.config import Settings
from mitty.models import Assignment, Course, Enrollment


def _make_settings(**overrides: object) -> Settings:
    """Create a Settings instance with a fake token for testing."""
    defaults: dict = {"canvas_token": "fake-token"}
    defaults.update(overrides)
    return Settings(**defaults)


def _make_supabase_settings() -> Settings:
    """Create a Settings instance with Supabase credentials for testing."""
    return _make_settings(
        supabase_url="https://test.supabase.co",
        supabase_key="fake-supabase-key",
    )


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
    """main() with --json should output valid JSON to stdout on success."""

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
            no_cache=False, verbose=False, debug=False, json=True
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
            no_cache=False, verbose=False, debug=False, json=True
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
            no_cache=False, verbose=False, debug=False, json=True
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


class TestCanvasAPIError:
    """CanvasAPIError should print error to stderr and exit non-zero."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_api_error_exits_nonzero(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=True
        )
        mock_load_settings.return_value = _make_settings()
        mock_fetch_all.side_effect = CanvasAPIError(
            "Canvas API error after 3 retries: 500 for /api/v1/courses"
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
        assert "api error" in captured.err.lower() or "API" in captured.err


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
            no_cache=True, verbose=False, debug=False, json=True
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
            no_cache=False, verbose=True, debug=False, json=True
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
            no_cache=False, verbose=False, debug=True, json=True
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


# ------------------------------------------------------------------ #
#  New tests: Supabase default mode, missing config, failures
# ------------------------------------------------------------------ #


class TestSupabaseDefaultMode:
    """Default mode (no --json) stores data to Supabase."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_stores_to_supabase(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=False
        )
        mock_load_settings.return_value = _make_supabase_settings()
        result = _make_fetch_all_result()
        mock_fetch_all.return_value = result

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_storage_client = AsyncMock()
        mock_create_storage = AsyncMock(return_value=mock_storage_client)
        mock_store_all = AsyncMock()

        with (
            patch("mitty.storage.create_storage", mock_create_storage),
            patch("mitty.storage.store_all", mock_store_all),
        ):
            from mitty.__main__ import main

            await main()

        mock_create_storage.assert_awaited_once_with(
            supabase_url="https://test.supabase.co",
            supabase_key="fake-supabase-key",
        )
        mock_store_all.assert_awaited_once_with(mock_storage_client, result)

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_prints_success_to_stderr(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=False
        )
        mock_load_settings.return_value = _make_supabase_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("mitty.storage.create_storage", AsyncMock()),
            patch("mitty.storage.store_all", AsyncMock()),
        ):
            from mitty.__main__ import main

            await main()

        captured = capsys.readouterr()
        assert "Data stored successfully" in captured.err
        assert captured.out == ""  # No JSON to stdout


class TestMissingSupabaseConfig:
    """Missing Supabase env vars in default mode should error."""

    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_missing_supabase_url_exits(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=False
        )
        mock_load_settings.return_value = _make_settings(
            supabase_url=None, supabase_key="some-key"
        )

        from mitty.__main__ import main

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "SUPABASE_URL" in captured.err
        assert "SUPABASE_KEY" in captured.err

    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_missing_supabase_key_exits(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=False
        )
        mock_load_settings.return_value = _make_settings(
            supabase_url="https://test.supabase.co", supabase_key=None
        )

        from mitty.__main__ import main

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "SUPABASE_URL" in captured.err
        assert "SUPABASE_KEY" in captured.err


class TestSupabaseFailure:
    """Supabase storage errors should print to stderr and exit."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_storage_error_exits(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from mitty.storage import StorageError

        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=False
        )
        mock_load_settings.return_value = _make_supabase_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_create_storage = AsyncMock(
            side_effect=StorageError("Failed to create Supabase client: timeout")
        )

        with patch("mitty.storage.create_storage", mock_create_storage):
            from mitty.__main__ import main

            with pytest.raises(SystemExit) as exc_info:
                await main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Storage error" in captured.err
        assert "timeout" in captured.err

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_store_all_error_exits(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from mitty.storage import StorageError

        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=False
        )
        mock_load_settings.return_value = _make_supabase_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

        mock_client = AsyncMock()
        mock_canvas_client_cls.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_canvas_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_store_all = AsyncMock(
            side_effect=StorageError("Failed to upsert courses: connection lost")
        )

        with (
            patch("mitty.storage.create_storage", AsyncMock()),
            patch("mitty.storage.store_all", mock_store_all),
        ):
            from mitty.__main__ import main

            with pytest.raises(SystemExit) as exc_info:
                await main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Storage error" in captured.err
        assert "connection lost" in captured.err


class TestJsonFlagPreservesOldBehavior:
    """--json flag outputs JSON even without Supabase config."""

    @patch("mitty.__main__.fetch_all", new_callable=AsyncMock)
    @patch("mitty.__main__.CanvasClient")
    @patch("mitty.__main__.load_settings")
    @patch("mitty.__main__.parse_args")
    async def test_json_flag_without_supabase_config(
        self,
        mock_parse_args: MagicMock,
        mock_load_settings: MagicMock,
        mock_canvas_client_cls: MagicMock,
        mock_fetch_all: AsyncMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_parse_args.return_value = MagicMock(
            no_cache=False, verbose=False, debug=False, json=True
        )
        # No Supabase config — should still work with --json
        mock_load_settings.return_value = _make_settings()
        mock_fetch_all.return_value = _make_fetch_all_result()

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
        assert len(output["courses"]) == 1
