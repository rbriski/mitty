"""Authentication dependency for FastAPI routes.

Validates Supabase JWT tokens via the server-side auth.get_user() call.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

logger = logging.getLogger("mitty.api.auth")


async def get_current_user(request: Request) -> dict[str, str]:
    """Extract and validate the Bearer token from the Authorization header.

    Uses the Supabase service-role client stored on ``request.app.state``
    to call ``auth.get_user(jwt)`` for server-side JWT validation.

    Returns:
        dict with ``user_id`` (str) and ``email`` (str) on success.

    Raises:
        HTTPException: 401 if the token is missing, malformed, invalid,
            or if the Supabase client is unavailable.
    """
    # Extract Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=401,
            detail={"code": "401", "message": "Missing Authorization header"},
        )

    # Validate Bearer prefix and extract token
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "401",
                "message": "Malformed Authorization header — expected 'Bearer <token>'",
            },
        )

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "401",
                "message": "Malformed Authorization header — empty token",
            },
        )

    # Get Supabase client
    client = getattr(request.app.state, "supabase_client", None)
    if client is None:
        logger.error("Supabase client is not configured — cannot validate token")
        raise HTTPException(
            status_code=401,
            detail={"code": "401", "message": "Authentication service unavailable"},
        )

    # Validate token via Supabase
    try:
        response = await client.auth.get_user(token)
    except Exception:
        logger.warning("Supabase auth.get_user failed", exc_info=True)
        raise HTTPException(
            status_code=401,
            detail={"code": "401", "message": "Invalid or expired token"},
        ) from None

    user = response.user
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "401", "message": "Invalid or expired token"},
        )

    return {"user_id": str(user.id), "email": user.email}
