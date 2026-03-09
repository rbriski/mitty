"""Tests for mitty.config — Settings model and CLI arg parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from mitty.config import load_settings, parse_args


class TestLoadSettingsMissingToken:
    """load_settings() must raise ValueError when CANVAS_TOKEN is absent."""

    def test_load_settings_missing_token_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Prevent load_dotenv() from injecting CANVAS_TOKEN from .env
        monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
        monkeypatch.delenv("CANVAS_TOKEN", raising=False)
        with pytest.raises(ValueError, match="CANVAS_TOKEN"):
            load_settings()


class TestLoadSettingsDefaults:
    """With only CANVAS_TOKEN set, all other fields use their defaults."""

    def test_load_settings_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANVAS_TOKEN", "test-token-abc")
        # Clear optional override env vars so defaults apply
        monkeypatch.delenv("CANVAS_BASE_URL", raising=False)
        monkeypatch.delenv("MAX_CONCURRENT", raising=False)
        monkeypatch.delenv("REQUEST_DELAY", raising=False)

        settings = load_settings()

        assert settings.canvas_token.get_secret_value() == "test-token-abc"
        assert settings.canvas_base_url == "https://mitty.instructure.com"
        assert settings.cache_dir == Path("data/.cache")
        assert settings.cache_enabled is True
        assert settings.cache_ttl_seconds == 3600
        assert settings.request_delay == 0.25
        assert settings.max_retries == 3
        assert settings.per_page == 100
        assert settings.max_concurrent == 3


class TestLoadSettingsEnvOverrides:
    """Environment variables override defaults where supported."""

    def test_load_settings_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANVAS_TOKEN", "override-token")
        monkeypatch.setenv("CANVAS_BASE_URL", "https://custom.instructure.com")
        monkeypatch.setenv("MAX_CONCURRENT", "5")
        monkeypatch.setenv("REQUEST_DELAY", "0.5")

        settings = load_settings()

        assert settings.canvas_token.get_secret_value() == "override-token"
        assert settings.canvas_base_url == "https://custom.instructure.com"
        assert settings.max_concurrent == 5
        assert settings.request_delay == 0.5


class TestParseArgs:
    """parse_args() CLI flag tests."""

    def test_parse_args_defaults(self) -> None:
        ns = parse_args([])

        assert ns.no_cache is False
        assert ns.verbose is False
        assert ns.debug is False

    def test_parse_args_no_cache(self) -> None:
        ns = parse_args(["--no-cache"])

        assert ns.no_cache is True

    def test_parse_args_verbose(self) -> None:
        ns = parse_args(["--verbose"])

        assert ns.verbose is True

    def test_parse_args_debug(self) -> None:
        ns = parse_args(["--debug"])

        assert ns.debug is True

    def test_parse_args_all_flags(self) -> None:
        ns = parse_args(["--no-cache", "--verbose", "--debug"])

        assert ns.no_cache is True
        assert ns.verbose is True
        assert ns.debug is True
