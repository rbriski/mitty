"""Application settings and CLI argument parsing.

Loads configuration from environment variables (with .env support)
and provides CLI flags for runtime overrides.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr


class Settings(BaseModel):
    """Immutable application configuration.

    Fields:
        canvas_base_url: Root URL for the Canvas LMS instance.
        canvas_token: Bearer token for Canvas API authentication.
        cache_dir: Local directory for HTTP response caching.
        cache_enabled: Whether to read/write cached responses.
        cache_ttl_seconds: Maximum age (seconds) of a valid cache entry.
        request_delay: Seconds to wait between HTTP requests.
        max_retries: Number of retry attempts for transient HTTP errors.
        per_page: Default page size for paginated Canvas API requests.
        max_concurrent: Maximum concurrent HTTP requests (semaphore size).
        supabase_url: Supabase project URL (optional).
        supabase_key: Supabase anon/service key (optional, secret).
        supabase_service_role_key: Supabase service-role key for API (optional).
        allowed_origins: Comma-separated CORS origins for the API.
        fastapi_debug: Enable FastAPI debug mode.
        anthropic_api_key: Anthropic API key for LLM calls (optional).
        anthropic_model: Anthropic model identifier for LLM calls.
        ai_rate_limit_rpm: Max AI requests per minute per user.
        ai_rate_limit_tpm: Max AI tokens per minute per user.
        ai_budget_per_session: Max USD spend per session.
        ai_budget_per_day: Max USD spend per day.
    """

    canvas_base_url: str = "https://mitty.instructure.com"
    canvas_token: SecretStr
    cache_dir: Path = Path("data/.cache")
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    request_delay: float = 0.25
    max_retries: int = 3
    per_page: int = 100
    max_concurrent: int = 3
    supabase_url: str | None = None
    supabase_key: SecretStr | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    allowed_origins: str = ""
    fastapi_debug: bool = False
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    ai_rate_limit_rpm: int = 30
    ai_rate_limit_tpm: int = 100_000
    ai_budget_per_session: float = 1.0
    ai_budget_per_day: float = 5.0


def load_settings() -> Settings:
    """Build a ``Settings`` instance from environment variables.

    Reads ``.env`` via *python-dotenv*, then pulls values from
    ``os.environ``.  ``CANVAS_TOKEN`` is required; all other
    variables fall back to the defaults declared on ``Settings``.

    Raises:
        ValueError: If ``CANVAS_TOKEN`` is not set.
    """
    load_dotenv()

    canvas_token = os.environ.get("CANVAS_TOKEN")
    if not canvas_token:
        msg = (
            "CANVAS_TOKEN environment variable is required but not set. "
            "Add it to your .env file or export it in your shell."
        )
        raise ValueError(msg)

    overrides: dict[str, str | int | float] = {
        "canvas_token": canvas_token,
    }

    if base_url := os.environ.get("CANVAS_BASE_URL"):
        overrides["canvas_base_url"] = base_url

    if max_concurrent := os.environ.get("MAX_CONCURRENT"):
        overrides["max_concurrent"] = int(max_concurrent)

    if request_delay := os.environ.get("REQUEST_DELAY"):
        overrides["request_delay"] = float(request_delay)

    if supabase_url := os.environ.get("SUPABASE_URL"):
        overrides["supabase_url"] = supabase_url

    if supabase_key := os.environ.get("SUPABASE_KEY"):
        overrides["supabase_key"] = supabase_key

    if anon_key := os.environ.get("SUPABASE_ANON_KEY"):
        overrides["supabase_anon_key"] = anon_key

    if service_role_key := os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        overrides["supabase_service_role_key"] = service_role_key

    if allowed_origins := os.environ.get("ALLOWED_ORIGINS"):
        overrides["allowed_origins"] = allowed_origins

    if os.environ.get("FASTAPI_DEBUG", "").lower() in ("1", "true", "yes"):
        overrides["fastapi_debug"] = True

    if anthropic_api_key := os.environ.get("ANTHROPIC_API_KEY"):
        overrides["anthropic_api_key"] = anthropic_api_key

    if anthropic_model := os.environ.get("ANTHROPIC_MODEL"):
        overrides["anthropic_model"] = anthropic_model

    return Settings(**overrides)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list to parse.  Defaults to ``sys.argv[1:]``
              when *None*.

    Returns:
        Namespace with ``no_cache``, ``verbose``, ``debug``, and ``json`` flags.
    """
    parser = argparse.ArgumentParser(
        prog="mitty",
        description="Canvas LMS assignment & grade scraper",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Disable response caching for this run",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Set log level to INFO (default is WARNING)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Set log level to DEBUG (implies --verbose)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON to stdout",
    )
    return parser.parse_args(argv)
