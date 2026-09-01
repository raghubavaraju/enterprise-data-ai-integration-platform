"""Entry point.

    GATEWAY_LAYER=experience uvicorn gateway.main:app --port 8080
    GATEWAY_LAYER=process    uvicorn gateway.main:app --port 8091
    GATEWAY_LAYER=system     uvicorn gateway.main:app --port 8092

One image, three deployments - the same shape as three Mule applications
deployed from one pipeline to three CloudHub targets.
"""
from __future__ import annotations

import os

_LAYER = os.getenv("GATEWAY_LAYER", "experience").lower()

if _LAYER == "experience":
    from .experience_layer import app
elif _LAYER == "process":
    from .process_layer import app
elif _LAYER == "system":
    from .system_layer import app
else:                                       # pragma: no cover
    raise SystemExit(f"Unknown GATEWAY_LAYER '{_LAYER}'. "
                     f"Expected experience, process or system.")

__all__ = ["app"]
