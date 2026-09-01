"""Mock Order Management System.

Quirks: order lines are a separate resource (the OMS never embeds them), and the
OMS uses ``status`` where the CRM uses ``state`` - the System API normalises both
to the canonical ``orderStatus``.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from mock_services._base import LimitQ, OffsetQ, load, make_app, maybe_inject_fault, paginate

app: FastAPI = make_app("Order Management", "Orders and order lines.")


@app.get("/api/v1/orders", tags=["orders"])
async def list_orders(customerId: str | None = None, status: str | None = None,
                      fromDate: str | None = None, limit: int = LimitQ, offset: int = OffsetQ,
                      _: None = Depends(maybe_inject_fault)) -> dict:
    rows = load("orders")
    if customerId:
        rows = [o for o in rows if o["customerId"] == customerId]
    if status:
        rows = [o for o in rows if o["orderStatus"] == status.upper()]
    if fromDate:
        rows = [o for o in rows if o["orderDate"] >= fromDate]
    rows = sorted(rows, key=lambda o: o["orderDate"], reverse=True)
    return paginate(rows, offset, limit)


@app.get("/api/v1/orders/{order_id}", tags=["orders"])
async def get_order(order_id: str, _: None = Depends(maybe_inject_fault)) -> dict:
    for o in load("orders"):
        if o["orderId"] == order_id:
            return o
    raise HTTPException(status_code=404, detail="Order not found")


@app.get("/api/v1/orders/{order_id}/lines", tags=["orders"])
async def get_lines(order_id: str, _: None = Depends(maybe_inject_fault)) -> list[dict]:
    return [i for i in load("order-items") if i["orderId"] == order_id]


@app.get("/api/v1/order-lines", tags=["orders"])
async def list_lines(limit: int = LimitQ, offset: int = OffsetQ,
                     _: None = Depends(maybe_inject_fault)) -> dict:
    return paginate(load("order-items"), offset, limit)
