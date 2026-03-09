"""CLI entry point for Mitty — Canvas LMS assignment & grade scraper.

Run with ``python -m mitty`` or ``uv run python -m mitty``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from mitty.canvas.client import CanvasAPIError, CanvasAuthError, CanvasClient
from mitty.canvas.fetcher import fetch_all
from mitty.config import load_settings, parse_args


def _serialize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a fetch_all result dict into a JSON-serializable structure.

    Pydantic models are converted to dicts via ``.model_dump()``.
    Nested structures (lists, dicts of models) are handled recursively.
    """
    from pydantic import BaseModel

    def _convert(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if isinstance(obj, list):
            return [_convert(item) for item in obj]
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        return obj

    return _convert(result)


async def main() -> None:
    """Parse CLI args, load settings, fetch Canvas data, and print JSON."""
    args = parse_args()

    # Configure logging
    logger = logging.getLogger("mitty")
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)

    if args.debug:
        logger.setLevel(logging.DEBUG)
    elif args.verbose:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)

    # Load settings
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Apply --no-cache override
    if args.no_cache:
        settings = settings.model_copy(update={"cache_enabled": False})

    # Fetch data and output JSON
    try:
        async with CanvasClient(settings) as client:
            result = await fetch_all(client, settings)
    except CanvasAuthError as exc:
        print(f"Authentication error: {exc}", file=sys.stderr)
        sys.exit(1)
    except CanvasAPIError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        sys.exit(1)

    serializable = _serialize_result(result)
    print(json.dumps(serializable, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
