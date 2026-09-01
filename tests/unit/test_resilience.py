"""Retry, circuit breaking, bulkheads and idempotency.

These are the behaviours that only matter on a bad day, which is exactly why
they need tests: nobody exercises them by hand.
"""
from __future__ import annotations

import asyncio

import pytest

from common.errors import DownstreamTimeoutError, DownstreamUnavailableError, NotFoundError
from common.resilience import Bulkhead, CircuitBreaker, CircuitState, IdempotencyStore, retry_async


class TestCircuitBreaker:
    def test_opens_after_the_failure_threshold(self):
        cb = CircuitBreaker(name="snowflake", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        for _ in range(3):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_breaker_fails_fast(self):
        cb = CircuitBreaker(name="ai", failure_threshold=1)
        cb.on_failure()
        with pytest.raises(DownstreamUnavailableError):
            cb.before_call()

    def test_half_opens_after_the_reset_window(self):
        cb = CircuitBreaker(name="crm", failure_threshold=1, reset_seconds=0)
        cb.on_failure()
        assert cb.state == CircuitState.HALF_OPEN
        cb.before_call()       # a half-open breaker allows a probe through
        cb.on_success()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_the_failure_count(self):
        cb = CircuitBreaker(name="oms", failure_threshold=3)
        cb.on_failure()
        cb.on_failure()
        cb.on_success()
        cb.on_failure()
        assert cb.state == CircuitState.CLOSED, "the count must not carry over a success"


class TestRetry:
    @pytest.mark.asyncio
    async def test_retries_transient_failures_and_eventually_succeeds(self):
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise DownstreamTimeoutError("still warming up")
            return "ok"

        assert await retry_async(flaky, attempts=5, base_delay_ms=1,
                                 retry_on=(DownstreamTimeoutError,)) == "ok"
        assert attempts["n"] == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_a_non_transient_failure(self):
        # Retrying a 404 cannot succeed; it only multiplies load and latency.
        attempts = {"n": 0}

        async def missing():
            attempts["n"] += 1
            raise NotFoundError("no such customer")

        with pytest.raises(NotFoundError):
            await retry_async(missing, attempts=4, base_delay_ms=1,
                              retry_on=(DownstreamTimeoutError, DownstreamUnavailableError))
        assert attempts["n"] == 1

    @pytest.mark.asyncio
    async def test_gives_up_after_the_configured_attempts(self):
        attempts = {"n": 0}

        async def always_down():
            attempts["n"] += 1
            raise DownstreamUnavailableError("down")

        with pytest.raises(DownstreamUnavailableError):
            await retry_async(always_down, attempts=3, base_delay_ms=1,
                              retry_on=(DownstreamUnavailableError,))
        assert attempts["n"] == 3

    @pytest.mark.asyncio
    async def test_retry_stops_once_the_breaker_opens(self):
        cb = CircuitBreaker(name="x", failure_threshold=2, reset_seconds=60)
        attempts = {"n": 0}

        async def always_down():
            attempts["n"] += 1
            raise DownstreamUnavailableError("down")

        with pytest.raises(DownstreamUnavailableError):
            await retry_async(always_down, attempts=10, base_delay_ms=1,
                              retry_on=(DownstreamUnavailableError,), breaker=cb)
        # Two real attempts open the breaker; the third is refused before the
        # call is made. Without this, a breaker inside a retry loop is useless.
        assert attempts["n"] == 2


class TestBulkhead:
    @pytest.mark.asyncio
    async def test_bounds_concurrency(self):
        bulkhead = Bulkhead(limit=2)
        live, peak = 0, 0

        async def work():
            nonlocal live, peak
            async with bulkhead:
                live += 1
                peak = max(peak, live)
                await asyncio.sleep(0.01)
                live -= 1

        await asyncio.gather(*(work() for _ in range(10)))
        assert peak <= 2, "concurrency must never exceed the bulkhead limit"


class TestIdempotency:
    def test_replayed_key_returns_the_first_response(self):
        store = IdempotencyStore(ttl_seconds=60)
        store.put("k1", {"action": "RETENTION_OFFER_15_PCT"})
        assert store.get("k1") == {"action": "RETENTION_OFFER_15_PCT"}

    def test_unknown_key_is_a_miss(self):
        assert IdempotencyStore(ttl_seconds=60).get("never-seen") is None

    def test_entries_expire(self):
        import time
        store = IdempotencyStore(ttl_seconds=0)
        store.put("k1", {"a": 1})
        time.sleep(0.01)
        assert store.get("k1") is None, "an expired key must not replay stale content"
