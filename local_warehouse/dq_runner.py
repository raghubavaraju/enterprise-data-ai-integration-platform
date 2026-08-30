"""Execute the data quality rule catalogue against the local warehouse.

Deliberately dumb: it reads GOVERNANCE.DQ_RULE, runs each rule's stored SQL,
compares the failing-row count against the rule's threshold, and writes
GOVERNANCE.DQ_RESULT.  The Snowflake executor
(``snowflake/04-procedures/02-sp-run-data-quality.sql``) does the same thing with
EXECUTE IMMEDIATE.  Two executors, one rule definition.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from .warehouse import shared

# Denominator per rule target, so FAIL_PCT means something.
ROWCOUNT_SQL = "SELECT TARGET_TABLE, ROWS_EVALUATED FROM ACME_EDP.GOVERNANCE.V_DQ_ROWCOUNTS"


def run_all(run_id: str | None = None, correlation_id: str | None = None) -> dict:
    con = shared()
    run_id = run_id or f"dqrun-{uuid.uuid4().hex[:12]}"
    executed_at = datetime.now(UTC).replace(tzinfo=None)
    counts = dict(con.execute(ROWCOUNT_SQL).fetchall())

    rules = con.execute(
        "SELECT RULE_ID, RULE_NAME, SEVERITY, TARGET_TABLE, THRESHOLD_PCT, RULE_SQL "
        "FROM ACME_EDP.GOVERNANCE.DQ_RULE WHERE IS_ACTIVE = TRUE ORDER BY RULE_ID").fetchall()

    results, summary = [], {"PASS": 0, "WARN": 0, "FAIL": 0, "ERROR": 0}
    for rule_id, _name, severity, table, threshold, sql in rules:
        try:
            failed = con.execute(sql).fetchone()[0] or 0
            evaluated = counts.get(table, 0) or 0
            pct = (failed / evaluated * 100.0) if evaluated else (100.0 if failed else 0.0)
            if failed == 0 or pct <= float(threshold or 0):
                status = "PASS"
            elif severity == "BLOCKING":
                status = "FAIL"
            elif severity == "WARNING":
                status = "WARN"
            else:
                status = "PASS"          # INFO rules are measured, never gate
            summary[status] += 1
            results.append((
                hashlib.md5(f"{run_id}:{rule_id}".encode(), usedforsecurity=False).hexdigest(), rule_id, run_id,
                executed_at, evaluated, failed, round(pct, 4), status, None, correlation_id))
        except Exception as exc:                                   # noqa: BLE001
            summary["ERROR"] += 1
            results.append((
                hashlib.md5(f"{run_id}:{rule_id}".encode(), usedforsecurity=False).hexdigest(), rule_id, run_id,
                executed_at, 0, -1, 0.0, "FAIL", f"rule execution error: {exc}"[:3900],
                correlation_id))

    con.execute("DELETE FROM ACME_EDP.GOVERNANCE.DQ_RESULT WHERE RUN_ID = ?", [run_id])
    con.executemany(
        "INSERT INTO ACME_EDP.GOVERNANCE.DQ_RESULT (RESULT_ID, RULE_ID, RUN_ID, EXECUTED_AT,"
        " ROWS_EVALUATED, ROWS_FAILED, FAIL_PCT, STATUS, SAMPLE_FAILING_KEYS, _CORRELATION_ID)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)", results)
    return {"runId": run_id, "rules": len(rules), "summary": summary}


if __name__ == "__main__":
    out = run_all()
    print(out)
    con = shared()
    for row in con.execute(
        "SELECT RULE_ID, SEVERITY, ROWS_FAILED, FAIL_PCT, STATUS FROM ACME_EDP.GOVERNANCE.V_DQ_LATEST"
        " ORDER BY CASE STATUS WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, RULE_ID").fetchall():
        print(f"  {row[0]:<12} {row[1]:<9} failed={row[2]:<5} pct={row[3]:<8} {row[4]}")
