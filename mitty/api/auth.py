"""Authentication dependency for FastAPI routes.

Validates Supabase JWT tokens via the server-side auth.get_user() call
using the service-role (admin) client.  Returns user info plus the raw
JWT so downstream dependencies can set it on the anon-key data client
for RLS enforcement.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

logger = logging.getLogger("mitty.api.auth")


async def get_current_user(request: Request) -> dict[str, str]:
    """Extract and validate the Bearer token from the Authorization header.

    Uses the Supabase **admin** (service-role) client stored on
    ``request.app.state.supabase_admin`` to call ``auth.get_user(jwt)``
    for server-side JWT validation.

    Returns:
        dict with ``user_id`` (str), ``email`` (str), and ``access_token``
        (str — the raw JWT for RLS passthrough).

    Raises:
        HTTPException: 401 if the token is missing, malformed, invalid,
            or if the Supabase admin client is unavailable.
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

    # Get the admin client (service-role) — used ONLY for token validation
    admin = getattr(request.app.state, "supabase_admin", None)
    if admin is None:
        logger.error("Supabase admin client is not configured — cannot validate token")
        raise HTTPException(
            status_code=401,
            detail={"code": "401", "message": "Authentication service unavailable"},
        )

    # Validate token via Supabase
    try:
        response = await admin.auth.get_user(token)
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

    return {
        "user_id": str(user.id),
        "email": user.email,
        "access_token": token,
    }
