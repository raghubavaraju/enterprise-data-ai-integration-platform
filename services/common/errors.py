"""Canonical error model.

One error shape is used by *every* API in the platform - experience, process and
system.  ``docs/api-governance.md`` specifies it; this module is the single
implementation, and ``api-specs/fragments/error.oas.yaml`` is the published
contract.  Keeping the three in step is what stops error handling from drifting
between layers.
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class PlatformError(Exception):
    """Base class for all intentionally raised platform errors."""

    status_code: int = 500
    error_code: str = "PLATFORM:INTERNAL_ERROR"
    message: str = "An unexpected error occurred."
    retryable: bool = False

    def __init__(self, message: str | None = None, details: list[dict[str, Any]] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or []


class ValidationError(PlatformError):
    status_code, error_code = 400, "PLATFORM:VALIDATION_ERROR"
    message = "The request failed validation."


class UnauthorizedError(PlatformError):
    status_code, error_code = 401, "PLATFORM:UNAUTHORIZED"
    message = "Authentication is required."


class ForbiddenError(PlatformError):
    status_code, error_code = 403, "PLATFORM:FORBIDDEN"
    message = "The token does not carry the scope required for this operation."


class NotFoundError(PlatformError):
    status_code, error_code = 404, "PLATFORM:RESOURCE_NOT_FOUND"
    message = "The requested resource does not exist."


class ConflictError(PlatformError):
    status_code, error_code = 409, "PLATFORM:CONFLICT"
    message = "The request conflicts with the current state of the resource."


class RateLimitError(PlatformError):
    status_code, error_code = 429, "PLATFORM:RATE_LIMIT_EXCEEDED"
    message = "Rate limit exceeded."
    retryable = True


class DownstreamUnavailableError(PlatformError):
    status_code, error_code = 503, "PLATFORM:DOWNSTREAM_UNAVAILABLE"
    message = "A downstream system is unavailable."
    retryable = True


class DownstreamTimeoutError(PlatformError):
    status_code, error_code = 504, "PLATFORM:DOWNSTREAM_TIMEOUT"
    message = "A downstream system did not respond in time."
    retryable = True


class DataPlatformError(PlatformError):
    status_code, error_code = 502, "DATA:QUERY_FAILED"
    message = "The analytical data platform rejected or failed the query."
    retryable = True


class AIServiceError(PlatformError):
    status_code, error_code = 502, "AI:GENERATION_FAILED"
    message = "The AI service could not produce a grounded response."
    retryable = True


def error_body(exc: PlatformError, correlation_id: str, path: str) -> dict[str, Any]:
    return {
        "errorCode": exc.error_code,
        "message": exc.message,
        "correlationId": correlation_id,
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
        "path": path,
        "retryable": exc.retryable,
        "details": exc.details,
    }


async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    from .middleware import current_correlation_id
    cid = current_correlation_id()
    headers = {"x-correlation-id": cid}
    if exc.retryable:
        headers["Retry-After"] = "5"
    return JSONResponse(status_code=exc.status_code, headers=headers,
                        content=error_body(exc, cid, request.url.path))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace or a downstream message to the caller."""
    import logging
    logging.getLogger("errors").exception("unhandled_exception", extra={"path": request.url.path})
    return await platform_error_handler(request, PlatformError())
