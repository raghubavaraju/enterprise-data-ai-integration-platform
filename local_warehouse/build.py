"""Build the local warehouse end to end.

    python -m local_warehouse.build            # full rebuild
    python -m local_warehouse.build --verify   # rebuild + row counts

Run order is explicit rather than alphabetical because there is a genuine
dependency cycle to break:

    CUSTOMER_360 wants the churn probability (for predicted CLV)
    churn scoring wants the feature store
    the feature store wants the ANALYTICS aggregates

so the aggregates and the engagement score are built first, then features, then
scores, and CUSTOMER_360 last.  This ordering is the same in Snowflake, where it
is expressed as a task DAG (05-pipelines/04-orchestration-tasks.sql).
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid

from . import dialect
from .loader import load_raw
from .warehouse import db_path, repo_root, shared

DDL_SCRIPTS = [
    "01-schemas/01-create-schemas.sql",
    "02-tables/raw/01-raw-tables.sql",
    "02-tables/staging/01-staging-tables.sql",
    "02-tables/core/01-core-tables.sql",
    "02-tables/analytics/01-analytics-tables.sql",
    "02-tables/ai/01-ai-tables.sql",
    "02-tables/governance/01-governance-tables.sql",
]

TRANSFORM_SCRIPTS = [
    "06-transformations/01-raw-to-staging-customer.sql",
    "06-transformations/02-raw-to-staging-orders.sql",
    "06-transformations/03-raw-to-staging-service-loyalty.sql",
    "06-transformations/04-staging-to-core-scd2.sql",
    "07-customer-360/01-order-summary.sql",
    "07-customer-360/02-support-and-engagement-summary.sql",
    "08-ai/01-feature-engineering.sql",
    "08-ai/02-churn-scoring.sql",
    "07-customer-360/03-customer-360-build.sql",
]

VIEW_SCRIPTS = [
    "03-views/01-core-views.sql",
    "03-views/02-consumption-views.sql",
]

DQ_SCRIPTS = [
    "09-data-quality/01-rule-catalog.sql",
    "09-data-quality/02-run-checks.sql",
    "09-data-quality/03-quarantine-failed-records.sql",
]

GOVERNANCE_SCRIPTS = [
    "09-data-quality/04-data-dictionary-seed.sql",
    "09-data-quality/05-lineage-seed.sql",
]


def _run_script(rel_path: str, verbose: bool = True) -> tuple[int, str | None]:
    path = repo_root() / "snowflake" / rel_path
    if not path.exists():
        return 0, f"missing: {rel_path}"
    sql = path.read_text()
    reason = dialect.unportable_reason(sql)
    if reason:
        if verbose:
            print(f"  SKIP  {rel_path}\n        Snowflake-only: {reason}")
        return 0, None
    translated = dialect.translate(sql)
    con = shared()
    executed = 0
    for stmt in dialect.split_statements(translated):
        try:
            con.execute(stmt)
            executed += 1
        except Exception as exc:                      # noqa: BLE001
            head = " ".join(stmt.split())[:160]
            return executed, f"{rel_path}: {exc}\n        statement: {head}"
    if verbose:
        print(f"  OK    {rel_path}  ({executed} statements)")
    return executed, None


def build(verify: bool = False) -> int:
    started = time.time()
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"
    correlation_id = f"acme-{uuid.uuid4()}"
    target = db_path()
    if target.exists():
        target.unlink()
    print(f"Building local warehouse at {target}")
    print(f"  batch_id={batch_id}  correlation_id={correlation_id}\n")

    errors: list[str] = []
    print("[1/6] DDL")
    for s in DDL_SCRIPTS:
        _, err = _run_script(s)
        if err:
            errors.append(err)

    print("\n[2/6] Ingest sample data into RAW")
    counts = load_raw(batch_id=batch_id, correlation_id=correlation_id)
    for t, n in counts.items():
        print(f"  LOAD  {t:32s} {n:6d} rows")

    print("\n[3/6] Transformations")
    for s in TRANSFORM_SCRIPTS:
        _, err = _run_script(s)
        if err:
            errors.append(err)

    print("\n[4/6] Views")
    for s in VIEW_SCRIPTS:
        _, err = _run_script(s)
        if err:
            errors.append(err)

    print("\n[5/6] Data quality")
    for s in DQ_SCRIPTS + GOVERNANCE_SCRIPTS:
        _, err = _run_script(s)
        if err:
            errors.append(err)
    from .dq_runner import run_all  # noqa: PLC0415
    dq = run_all(correlation_id=correlation_id)
    print(f"  RUN   {dq['rules']} rules -> {dq['summary']}")

    print("\n[6/6] RAG corpus")
    try:
        sys.path.insert(0, str(repo_root() / "services"))
        sys.path.insert(0, str(repo_root()))
        from ai_service.rag import build_corpus  # noqa: PLC0415
        chunks = build_corpus()
        print(f"  OK    embedded {chunks} knowledge-base chunks")
    except Exception as exc:                              # noqa: BLE001
        errors.append(f"RAG corpus build: {exc}")

    if errors:
        print("\nERRORS")
        for e in errors:
            print(f"  !! {e}")
        return 1

    print(f"\nBuild completed in {time.time() - started:.1f}s")
    if verify:
        verify_counts()
    return 0


VERIFY_TABLES = [
    "RAW.RAW_CRM_CUSTOMER", "STAGING.STG_CUSTOMER", "CORE.CUSTOMER", "CORE.SALES_ORDER",
    "CORE.SALES_ORDER_ITEM", "CORE.SUPPORT_CASE", "CORE.LOYALTY_ACCOUNT",
    "ANALYTICS.CUSTOMER_ORDER_SUMMARY", "ANALYTICS.CUSTOMER_SUPPORT_SUMMARY",
    "ANALYTICS.CUSTOMER_ENGAGEMENT_SUMMARY", "ANALYTICS.CUSTOMER_360",
    "AI.CUSTOMER_FEATURES", "AI.CUSTOMER_CHURN_SCORE", "AI.KB_DOCUMENT", "AI.KB_CHUNK",
    "GOVERNANCE.DQ_RESULT", "GOVERNANCE.DATA_DICTIONARY", "GOVERNANCE.LINEAGE_EDGE",
    "RAW.RAW_REJECTED_RECORDS",
]


def verify_counts() -> None:
    con = shared()
    print("\nRow counts")
    for t in VERIFY_TABLES:
        try:
            # noqa: S608 - `t` comes from VERIFY_TABLES, a literal in this file.
            n = con.execute(f"SELECT COUNT(*) FROM ACME_EDP.{t}").fetchone()[0]  # noqa: S608  # nosec B608
            print(f"  {t:42s} {n:7d}")
        except Exception as exc:                       # noqa: BLE001
            print(f"  {t:42s}   ERROR  {exc}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    raise SystemExit(build(verify=ap.parse_args().verify))
