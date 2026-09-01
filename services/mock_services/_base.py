from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

from common.config import get_settings
from common.logging_config import configure_logging
from common.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware

_settings = get_settings()
DATA_DIR = Path(os.getenv("SAMPLE_DATA_DIR",
                          Path(__file__).resolve().parents[2] / "sample-data"))
_cache: dict[str, Any] = {}


def load(name: str) -> list[dict]:
    if name not in _cache:
        _cache[name] = json.loads((DATA_DIR / f"{name}.json").read_text())
    return _cache[name]


async def maybe_inject_fault(request: Request) -> None:
    """Deterministic fault injection for resilience demos and tests.

    ``?__fault=timeout|error|throttle`` lets the integration tests prove that the
    Mule-equivalent retry, circuit-breaker and fallback paths actually fire.
    Never enabled outside local mode.
    """
    fault = request.query_params.get("__fault")
    if not fault or not _settings.is_local:
        return
    if fault == "timeout":
        await asyncio.sleep(_settings.downstream_timeout_seconds + 2)
    elif fault == "error":
        raise HTTPException(status_code=500, detail="Simulated source system failure")
    elif fault == "throttle":
        raise HTTPException(status_code=429, detail="Simulated source system throttling")
    elif fault == "flaky" and random.random() < 0.5:
        raise HTTPException(status_code=503, detail="Simulated intermittent failure")


def make_app(system_name: str, description: str) -> FastAPI:
    configure_logging(system_name, _settings.log_level, _settings.log_format)
    app = FastAPI(
        title=f"Acme {system_name} (mock source system)",
        description=description,
        version="1.0.0",
        docs_url="/docs",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/health", tags=["operations"])
    async def health() -> dict:
        return {"status": "UP", "system": system_name}

    return app


def paginate(rows: list[dict], offset: int, limit: int) -> dict:
    window = rows[offset: offset + limit]
    return {"data": window,
            "pagination": {"offset": offset, "limit": limit, "total": len(rows),
                           "returned": len(window),
                           "hasMore": offset + limit < len(rows)}}


LimitQ = Query(default=50, ge=1, le=500)
OffsetQ = Query(default=0, ge=0)
