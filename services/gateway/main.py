"""Entry point.

    GATEWAY_LAYER=experience       uvicorn gateway.main:app --port 8080
    GATEWAY_LAYER=process          uvicorn gateway.main:app --port 8091
    GATEWAY_LAYER=system           uvicorn gateway.main:app --port 8092
    GATEWAY_LAYER=store-experience uvicorn gateway.main:app --port 8093

One image, four deployments - the same shape as four Mule applications
deployed from one pipeline to four CloudHub targets. ``store-experience`` is a
second consumer of the same process layer as ``experience``: see
store_experience_layer.py for what that does and does not change.
"""
from __future__ import annotations

import os

_LAYER = os.getenv("GATEWAY_LAYER", "experience").lower()

if _LAYER == "experience":
    from .experience_layer import app
elif _LAYER == "store-experience":
    from .store_experience_layer import app
elif _LAYER == "process":
    from .process_layer import app
elif _LAYER == "system":
    from .system_layer import app
else:                                       # pragma: no cover
    raise SystemExit(f"Unknown GATEWAY_LAYER '{_LAYER}'. "
                     f"Expected experience, store-experience, process or system.")

__all__ = ["app"]
