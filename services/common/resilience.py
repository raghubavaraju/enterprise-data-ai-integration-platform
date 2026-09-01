"""Resilience primitives shared by the process and experience layers.

Mirrors the Mule 4 constructs used in ``mule/`` so the behaviour described in
``docs/resilience-and-dr.md`` is actually demonstrable:

    concern        | Mule 4                          | here
    ---------------|---------------------------------|--------------------------
    retry          | ``until-successful``            | ``retry_async``
    timeout        | connector ``responseTimeout``   | ``httpx`` timeout
    circuit break  | Reliability pattern + object    | ``CircuitBreaker``
                   | store flag                      |
    bulkhead       | per-flow max concurrency        | ``asyncio.Semaphore``
    idempotency    | ``idempotent-message-validator``| ``IdempotencyStore``
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .config import get_settings
from .errors import DownstreamUnavailableError

T = TypeVar("T")
_settings = get_settings()


class CircuitState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    """Per-dependency breaker.

    Rationale: when Snowflake or the LLM provider is degraded, hammering it with
    retries turns a partial outage into a full one and burns credits.  The
    breaker fails fast and lets the caller fall back to cached/degraded data -
    which is exactly what the Customer 360 flow does (``degradedFields``).
    """

    name: str
    failure_threshold: int = field(default_factory=lambda: _settings.circuit_breaker_failure_threshold)
    reset_seconds: float = field(default_factory=lambda: float(_settings.circuit_breaker_reset_seconds))
    _failures: int = 0
    _opened_at: float = 0.0
    _state: str = CircuitState.CLOSED

    @property
    def state(self) -> str:
        if self._state == CircuitState.OPEN and (time.time() - self._opened_at) >= self.reset_seconds:
            self._state = CircuitState.HALF_OPEN
        return self._state

    def before_call(self) -> None:
        if self.state == CircuitState.OPEN:
            raise DownstreamUnavailableError(
                f"Circuit breaker for '{self.name}' is open; failing fast.")

    def on_success(self) -> None:
        self._failures = 0
        self._state = CircuitState.CLOSED

    def on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {"dependency": self.name, "state": self.state, "failures": self._failures}


async def retry_async(fn: Callable[[], Awaitable[T]], *, attempts: int | None = None,
                      base_delay_ms: int | None = None,
                      retry_on: tuple[type[Exception], ...] = (Exception,),
                      breaker: CircuitBreaker | None = None) -> T:
    """Exponential backoff with full jitter.

    Jitter matters: without it, every Mule worker retries on the same schedule
    and the recovering downstream is knocked over by the synchronised wave.
    """
    attempts = attempts or _settings.max_retry_attempts
    base = (base_delay_ms or _settings.retry_base_delay_ms) / 1000.0
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        if breaker:
            breaker.before_call()
        try:
            result = await fn()
            if breaker:
                breaker.on_success()
            return result
        except retry_on as exc:            # noqa: PERF203
            last = exc
            if breaker:
                breaker.on_failure()
            if attempt == attempts:
                break
            await asyncio.sleep(random.uniform(0, base * (2 ** (attempt - 1))))
    assert last is not None
    raise last


class Bulkhead:
    """Bounded concurrency per dependency so one slow system cannot exhaust the pool."""

    def __init__(self, limit: int = 16):
        self._sem = asyncio.Semaphore(limit)

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, *_exc):
        self._sem.release()


class IdempotencyStore:
    """In-memory idempotency keys.

    Production uses the Anypoint object store (or Redis) so the guarantee holds
    across workers and restarts; the contract is the same - a replayed
    ``Idempotency-Key`` returns the first response instead of re-running the
    side effect (notably, instead of paying for a second LLM call).
    """

    def __init__(self, ttl_seconds: int | None = None):
        # `is None`, not `or`: a configured TTL of 0 is a legitimate value
        # (useful in tests and for a on purpose non-caching deployment) and
        # `or` would silently replace it with the default.
        self.ttl = _settings.idempotency_ttl_seconds if ttl_seconds is None else ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        self._evict()
        entry = self._store.get(key)
        return entry[1] if entry else None

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)

    def _evict(self) -> None:
        now = time.time()
        for k in [k for k, (ts, _) in self._store.items() if now - ts > self.ttl]:
            self._store.pop(k, None)
