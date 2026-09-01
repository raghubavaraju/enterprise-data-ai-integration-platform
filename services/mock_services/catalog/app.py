"""Mock Product Catalog / PIM."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from mock_services._base import LimitQ, OffsetQ, load, make_app, maybe_inject_fault, paginate

app: FastAPI = make_app("Product Catalog", "Product master data.")


@app.get("/api/v1/products", tags=["products"])
async def list_products(category: str | None = None, limit: int = LimitQ, offset: int = OffsetQ,
                        _: None = Depends(maybe_inject_fault)) -> dict:
    rows = load("products")
    if category:
        rows = [p for p in rows if p["category"].lower() == category.lower()]
    return paginate(rows, offset, limit)


@app.get("/api/v1/products/{product_id}", tags=["products"])
async def get_product(product_id: str, _: None = Depends(maybe_inject_fault)) -> dict:
    for p in load("products"):
        if p["productId"] == product_id:
            return p
    raise HTTPException(status_code=404, detail="Product not found")
