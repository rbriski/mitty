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


class BudgetExceededError(AIClientError):
    """Raised when a cost budget (per-session or per-day) is exceeded.

    Attributes:
        budget_type: Either ``"session"`` or ``"daily"``.
        limit_usd: The budget cap that was exceeded.
        spent_usd: The amount already spent.
    """

    def __init__(
        self,
        *,
        budget_type: str,
        limit_usd: float,
        spent_usd: float,
    ) -> None:
        message = (
            f"{budget_type.capitalize()} budget exceeded: "
            f"${spent_usd:.4f} spent, ${limit_usd:.4f} limit"
        )
        super().__init__(message, status_code=None)
        self.budget_type = budget_type
        self.limit_usd = limit_usd
        self.spent_usd = spent_usd
