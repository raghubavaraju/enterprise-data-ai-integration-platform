"""Mock Customer Support system (cases + knowledge base)."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from mock_services._base import (
    DATA_DIR,
    LimitQ,
    OffsetQ,
    load,
    make_app,
    maybe_inject_fault,
    paginate,
)

app: FastAPI = make_app("Customer Support", "Support cases and knowledge articles.")
KB_DIR: Path = DATA_DIR / "knowledge-base"


@app.get("/api/v1/cases", tags=["cases"])
async def list_cases(customerId: str | None = None, status: str | None = None,
                     limit: int = LimitQ, offset: int = OffsetQ,
                     _: None = Depends(maybe_inject_fault)) -> dict:
    rows = load("support-cases")
    if customerId:
        rows = [c for c in rows if c["customerId"] == customerId]
    if status:
        rows = [c for c in rows if c["status"] == status.upper()]
    rows = sorted(rows, key=lambda c: c["openedAt"], reverse=True)
    return paginate(rows, offset, limit)


@app.get("/api/v1/cases/{case_id}", tags=["cases"])
async def get_case(case_id: str, _: None = Depends(maybe_inject_fault)) -> dict:
    for c in load("support-cases"):
        if c["caseId"] == case_id:
            return c
    raise HTTPException(status_code=404, detail="Case not found")


@app.get("/api/v1/knowledge-articles", tags=["knowledge"])
async def list_articles() -> list[dict]:
    """Source of truth for the RAG corpus (see ``services/ai_service/rag.py``)."""
    out = []
    for path in sorted(KB_DIR.glob("*.md")):
        raw = path.read_text()
        meta: dict[str, str] = {}
        body = raw
        if raw.startswith("---"):
            _, fm, body = raw.split("---", 2)
            for line in fm.strip().splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        out.append({"articleId": meta.get("article_id", path.stem),
                    "title": meta.get("title", path.stem),
                    "category": meta.get("category", "General"),
                    "owner": meta.get("owner", "Customer Service Operations"),
                    "lastReviewed": meta.get("last_reviewed"),
                    "sourceUri": f"kb://support/{path.name}",
                    "content": body.strip()})
    return out
