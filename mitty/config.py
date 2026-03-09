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

    return Settings(**overrides)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list to parse.  Defaults to ``sys.argv[1:]``
              when *None*.

    Returns:
        Namespace with ``no_cache``, ``verbose``, and ``debug`` flags.
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
    return parser.parse_args(argv)
