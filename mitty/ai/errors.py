"""Custom exceptions for the AI client module."""

from __future__ import annotations


class AIClientError(Exception):
    """Base exception for AI client errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code from the API, if applicable.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RateLimitError(AIClientError):
    """Raised when the Anthropic API returns a 429 rate-limit response.

    Inherits from AIClientError so callers can catch either.
    """

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, status_code=429)
