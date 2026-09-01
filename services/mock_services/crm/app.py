"""Mock CRM.

Quirks modelled on purpose: the CRM calls the business key ``CustomerNumber``,
returns dates as ISO strings without timezone, and answers 200 with an empty
list rather than 404 for an unknown customer's addresses.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request

from mock_services._base import LimitQ, OffsetQ, load, make_app, maybe_inject_fault, paginate

app: FastAPI = make_app("CRM", "Customer master, addresses and contact points.")


@app.get("/api/v1/customers", tags=["customers"])
async def list_customers(request: Request, limit: int = LimitQ, offset: int = OffsetQ,
                         updatedSince: str | None = None,
                         _: None = Depends(maybe_inject_fault)) -> dict:
    rows = [c for c in load("customers") if c.get("customerId")]
    if updatedSince:
        rows = [c for c in rows if (c.get("updatedAt") or "") >= updatedSince]
    return paginate(rows, offset, limit)


@app.get("/api/v1/customers/{customer_number}", tags=["customers"])
async def get_customer(customer_number: str, request: Request,
                       _: None = Depends(maybe_inject_fault)) -> dict:
    for c in load("customers"):
        if c.get("customerId") == customer_number:
            return c
    raise HTTPException(status_code=404, detail="CustomerNumber not found in CRM")


@app.get("/api/v1/customers/{customer_number}/addresses", tags=["customers"])
async def get_addresses(customer_number: str, _: None = Depends(maybe_inject_fault)) -> list[dict]:
    return [a for a in load("customer-addresses") if a["customerId"] == customer_number]


@app.get("/api/v1/customers/{customer_number}/contacts", tags=["customers"])
async def get_contacts(customer_number: str, _: None = Depends(maybe_inject_fault)) -> list[dict]:
    return [c for c in load("customer-contacts") if c["customerId"] == customer_number]


@app.get("/api/v1/interactions", tags=["interactions"])
async def list_interactions(customerId: str | None = None, limit: int = LimitQ,
                            offset: int = OffsetQ,
                            _: None = Depends(maybe_inject_fault)) -> dict:
    rows = load("customer-interactions")
    if customerId:
        rows = [i for i in rows if i["customerId"] == customerId]
    return paginate(rows, offset, limit)
