"""Tests for mitty.config — Settings model and CLI arg parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from mitty.config import Settings, load_settings, parse_args


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


class TestSupabaseSettingsFields:
    """Settings model supports optional Supabase configuration fields."""

    def test_supabase_fields_default_to_none(self) -> None:
        """Supabase fields are None when not provided."""
        settings = Settings(canvas_token="test-token")

        assert settings.supabase_url is None
        assert settings.supabase_key is None
        assert settings.database_url is None

    def test_supabase_fields_accept_values(self) -> None:
        """Supabase fields accept string / SecretStr values."""
        settings = Settings(
            canvas_token="test-token",
            supabase_url="https://abc.supabase.co",
            supabase_key="sb-key-123",
            database_url="postgresql://user:pass@host:5432/db",
        )

        assert settings.supabase_url == "https://abc.supabase.co"
        assert settings.supabase_key is not None
        assert settings.supabase_key.get_secret_value() == "sb-key-123"
        assert settings.database_url is not None
        assert (
            settings.database_url.get_secret_value()
            == "postgresql://user:pass@host:5432/db"
        )


class TestLoadSettingsSupabaseEnv:
    """load_settings() picks up Supabase env vars when present."""

    def test_supabase_env_vars_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
        monkeypatch.setenv("CANVAS_TOKEN", "test-token")
        monkeypatch.setenv("SUPABASE_URL", "https://xyz.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "sb-secret")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")

        settings = load_settings()

        assert settings.supabase_url == "https://xyz.supabase.co"
        assert settings.supabase_key is not None
        assert settings.supabase_key.get_secret_value() == "sb-secret"
        assert settings.database_url is not None
        assert settings.database_url.get_secret_value() == "postgresql://u:p@h:5432/d"

    def test_missing_supabase_vars_return_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("mitty.config.load_dotenv", lambda: None)
        monkeypatch.setenv("CANVAS_TOKEN", "test-token")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        settings = load_settings()

        assert settings.supabase_url is None
        assert settings.supabase_key is None
        assert settings.database_url is None


class TestParseArgsJsonFlag:
    """parse_args() supports --json flag."""

    def test_json_flag_default_false(self) -> None:
        ns = parse_args([])

        assert ns.json is False

    def test_json_flag_set(self) -> None:
        ns = parse_args(["--json"])

        assert ns.json is True

    def test_json_flag_with_other_flags(self) -> None:
        ns = parse_args(["--json", "--verbose", "--no-cache"])

        assert ns.json is True
        assert ns.verbose is True
        assert ns.no_cache is True
