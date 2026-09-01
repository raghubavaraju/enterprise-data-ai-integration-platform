"""Mock Loyalty platform."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from mock_services._base import LimitQ, OffsetQ, load, make_app, maybe_inject_fault, paginate

app: FastAPI = make_app("Loyalty", "Loyalty accounts, tiers and point balances.")


@app.get("/api/v1/loyalty-accounts", tags=["loyalty"])
async def list_accounts(limit: int = LimitQ, offset: int = OffsetQ,
                        _: None = Depends(maybe_inject_fault)) -> dict:
    return paginate(load("loyalty"), offset, limit)


@app.get("/api/v1/loyalty-accounts/by-customer/{customer_id}", tags=["loyalty"])
async def by_customer(customer_id: str, _: None = Depends(maybe_inject_fault)) -> dict:
    for a in load("loyalty"):
        if a["customerId"] == customer_id:
            return a
    # Not every customer is enrolled - this is a legitimate 404, and the
    # Customer 360 process flow treats it as "no loyalty account", not an error.
    raise HTTPException(status_code=404, detail="No loyalty account for customer")
