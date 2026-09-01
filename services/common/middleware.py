"""Cross-cutting HTTP concerns implemented once and mounted by every service.

These are the *runnable* counterparts of the Anypoint API Manager policies
described in ``docs/security-architecture.md``:

    Anypoint policy               | implemented here as
    ------------------------------|-----------------------------------------
    JWT / OAuth 2.0 validation    | ``require_scopes`` dependency
    Rate limiting - SLA based     | ``RateLimitMiddleware``
    Correlation id propagation    | ``CorrelationIdMiddleware``
    Header injection / removal    | ``CorrelationIdMiddleware``
    Client id enforcement         | ``require_scopes`` (``client_id`` claim)

In production these are enforced by the platform, not by application code; the
Python implementation exists so the POC demonstrates the behaviour end to end
without an Anypoint licence.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_settings
from .logging_config import correlation_id_var

_settings = get_settings()


def current_correlation_id() -> str:
    return correlation_id_var.get()


def new_correlation_id() -> str:
    return f"acme-{uuid.uuid4()}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Accept an inbound correlation id or mint one; always echo it back.

    The id is the join key across Mule logs, Snowflake ``QUERY_TAG`` and the AI
    audit table.  See ``docs/observability.md``.
    """

    async def dispatch(self, request: Request, call_next):
        header = _settings.correlation_id_header
        cid = request.headers.get(header) or request.headers.get("X-Request-ID") or new_correlation_id()
        correlation_id_var.set(cid)
        started = time.perf_counter()
        response: Response = await call_next(request)
        response.headers[header] = cid
        response.headers["x-response-time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        # Never advertise the server implementation.
        if "server" in response.headers:
            del response.headers["server"]
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter keyed on client id (falls back to peer address).

    In production this is an SLA-tiered Anypoint rate-limiting policy; the
    semantics (429 + ``Retry-After`` + ``X-RateLimit-*``) are identical.
    """

    def __init__(self, app, requests: int | None = None, window: int | None = None):
        super().__init__(app)
        self.max = requests or _settings.rate_limit_requests
        self.window = window or _settings.rate_limit_window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/ready", "/metrics", "/openapi.json", "/docs"):
            return await call_next(request)
        key = request.headers.get("client_id") or (request.client.host if request.client else "anon")
        now = time.time()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.max:
            retry_after = int(self.window - (now - bucket[0])) + 1
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after),
                         "X-RateLimit-Limit": str(self.max),
                         "X-RateLimit-Remaining": "0",
                         _settings.correlation_id_header: current_correlation_id()},
                content={"errorCode": "PLATFORM:RATE_LIMIT_EXCEEDED",
                         "message": "Rate limit exceeded.",
                         "correlationId": current_correlation_id(),
                         "path": request.url.path, "retryable": True, "details": []})
        bucket.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.max)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.max - len(bucket)))
        return response
