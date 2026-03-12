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
    """Parse CLI args, load settings, fetch Canvas data, and output results.

    Default mode stores results to Supabase.  With ``--json``, prints
    JSON to stdout instead (original behavior).
    """
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

    # Validate Supabase config when not in --json mode.
    # Prefer service-role key (bypasses RLS) for the scraper pipeline.
    _storage_key = settings.supabase_service_role_key or settings.supabase_key
    if not args.json and (not settings.supabase_url or not _storage_key):
        print(
            "Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) "
            "are required. Set them in .env or use --json for JSON output.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Fetch data
    try:
        async with CanvasClient(settings) as client:
            result = await fetch_all(client, settings)
    except CanvasAuthError as exc:
        print(f"Authentication error: {exc}", file=sys.stderr)
        sys.exit(1)
    except CanvasAPIError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Output: --json mode or Supabase mode
    if args.json:
        serializable = _serialize_result(result)
        print(json.dumps(serializable, indent=2, default=str))
    else:
        from mitty.storage import StorageError, create_storage, store_all

        # Both fields are guaranteed non-None by the guard above.
        assert settings.supabase_url is not None
        assert _storage_key is not None
        try:
            storage_client = await create_storage(
                supabase_url=settings.supabase_url,
                supabase_key=_storage_key.get_secret_value(),
            )
            await store_all(storage_client, result)
        except StorageError as exc:
            print(f"Storage error: {exc}", file=sys.stderr)
            sys.exit(1)

        print("Data stored successfully.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
