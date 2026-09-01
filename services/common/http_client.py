"""Outbound HTTP with the platform's non-negotiables baked in.

Any call that leaves a service must carry the correlation id, obey the timeout
budget, be retried only when the failure is retryable, and be guarded by the
dependency's circuit breaker.  Putting that in one place is what stops each
flow from inventing its own (subtly wrong) version.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import get_settings
from .errors import (
    DownstreamTimeoutError,
    DownstreamUnavailableError,
    NotFoundError,
    PlatformError,
    UnauthorizedError,
)
from .middleware import current_correlation_id
from .resilience import CircuitBreaker, retry_async

log = logging.getLogger("http_client")
_settings = get_settings()
_breakers: dict[str, CircuitBreaker] = {}


def breaker_for(name: str) -> CircuitBreaker:
    return _breakers.setdefault(name, CircuitBreaker(name=name))


def breaker_snapshots() -> list[dict[str, Any]]:
    return [b.snapshot() for b in _breakers.values()]


class DownstreamClient:
    def __init__(self, name: str, base_url: str, timeout: float | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or _settings.downstream_timeout_seconds
        self.breaker = breaker_for(name)

    async def request(self, method: str, path: str, *, json: Any = None,
                      params: dict | None = None, headers: dict | None = None,
                      retries: int | None = None) -> Any:
        url = f"{self.base_url}{path}"
        hdrs = {_settings.correlation_id_header: current_correlation_id(),
                "accept": "application/json"}
        if headers:
            hdrs.update(headers)

        async def _call() -> Any:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(method, url, json=json, params=params, headers=hdrs)
            except httpx.TimeoutException as exc:
                raise DownstreamTimeoutError(
                    f"{self.name} did not respond within {self.timeout}s.") from exc
            except httpx.HTTPError as exc:
                raise DownstreamUnavailableError(f"{self.name} is unreachable.") from exc

            if resp.status_code == 404:
                raise NotFoundError(f"{self.name} has no record for {path}.")
            if resp.status_code in (401, 403):
                raise UnauthorizedError(f"{self.name} rejected the platform credentials.")
            if resp.status_code >= 500:
                raise DownstreamUnavailableError(
                    f"{self.name} returned HTTP {resp.status_code}.")
            if resp.status_code >= 400:
                err = PlatformError(f"{self.name} rejected the request "
                                    f"(HTTP {resp.status_code}).")
                err.status_code, err.error_code = 400, "PLATFORM:DOWNSTREAM_REJECTED"
                raise err
            return resp.json() if resp.content else None

        # Only transient classes are retried.  Retrying a 404 or a 400 is a bug,
        # not resilience: it multiplies load without any chance of succeeding.
        return await retry_async(
            _call,
            attempts=retries if retries is not None else _settings.max_retry_attempts,
            retry_on=(DownstreamTimeoutError, DownstreamUnavailableError),
            breaker=self.breaker,
        )

    async def get(self, path: str, **kw) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw) -> Any:
        return await self.request("POST", path, **kw)
