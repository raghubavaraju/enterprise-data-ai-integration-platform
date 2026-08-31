#!/usr/bin/env python3
"""Lint the Snowflake SQL against this repository's conventions.

Not a general-purpose SQL linter.  It checks the handful of rules that, left
unchecked, produce the bugs this kind of platform actually suffers from:

  * ``SELECT *`` in a consumption view - a column added upstream silently
    changes an API response;
  * an unqualified object reference in a script marked portable - it will
    resolve to the wrong schema, or to nothing, depending on session state;
  * a query against an SCD2 table without ``IS_CURRENT`` - silently multiplies
    every metric by the number of versions;
  * a hard-coded credential, account identifier or e-mail address;
  * a ``DELETE`` or ``UPDATE`` with no ``WHERE``, outside the deliberate
    full-refresh transformation scripts;
  * a missing header comment - every script must say what it does and whether
    it is portable.

Run: ``python scripts/lint_sql.py``   (or ``make lint-sql``)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SQL_ROOT = REPO / "snowflake"

SCD2_TABLES = {"CORE.CUSTOMER"}
FULL_REFRESH_DIRS = {"06-transformations", "07-customer-360", "08-ai", "09-data-quality"}

SECRET_PATTERNS = [
    (re.compile(r"(?i)\bpassword\s*=\s*'[^']+'"), "hard-coded password"),
    (re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key material"),
    (re.compile(r"(?i)\baccount\s*=\s*'[a-z0-9_-]{6,}'"), "hard-coded Snowflake account"),
    (re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(com|org))[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "real-looking e-mail address (use an example.com address)"),
]

findings: list[str] = []
warnings: list[str] = []


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def strip_literals(sql: str) -> str:
    """Blank out string literals.

    Needed because several scripts store SQL *as data* - the data-quality rule
    catalogue and the lineage seed both contain SELECT statements inside quoted
    values. Without this the linter reads English prose in a business definition
    as an unqualified table reference.
    """
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def check(path: Path) -> None:
    rel = path.relative_to(REPO)
    raw = path.read_text()
    body = strip_comments(raw)
    layer = path.parent.name if path.parent.parent.name == "snowflake" else path.parent.parent.name

    # --- documentation -----------------------------------------------------
    if not raw.lstrip().startswith("--"):
        findings.append(f"{rel}: script must open with a header comment explaining what it does")
    elif "[portable]" not in raw and "Snowflake only" not in raw and layer in FULL_REFRESH_DIRS:
        warnings.append(f"{rel}: header does not state whether the script is portable")

    # --- secrets -----------------------------------------------------------
    for pattern, description in SECRET_PATTERNS:
        for match in pattern.finditer(raw):
            findings.append(f"{rel}: {description}: {match.group(0)[:40]}")

    # --- SELECT * in a view ------------------------------------------------
    if "03-views" in str(rel) and re.search(r"(?i)SELECT\s+\*", body):
        findings.append(f"{rel}: SELECT * in a consumption view - an upstream column "
                        f"addition would silently change an API response")

    # --- unqualified references in portable scripts ------------------------
    if "[portable]" in raw:
        for match in re.finditer(r"(?i)\b(FROM|JOIN|INTO|UPDATE)\s+([A-Z_][A-Z0-9_]*)\s",
                                 strip_literals(body)):
            obj = match.group(2).upper()
            if obj in {"SELECT", "VALUES", "SET", "LATERAL", "TABLE", "UNNEST"}:
                continue
            # CTE names are declared in a WITH clause in the same file.
            if re.search(rf"(?i)\b{obj}\s+AS\s*\(", strip_literals(body)):
                continue
            findings.append(f"{rel}: unqualified object reference '{obj}' in a portable "
                            f"script (use ACME_EDP.<schema>.<object>)")

    # --- SCD2 safety -------------------------------------------------------
    for table in SCD2_TABLES:
        if re.search(rf"(?i)\bFROM\s+ACME_EDP\.{table}\b", body):
            window = body
            # The SCD2 loader, the history view and the DQ rules are the
            # deliberate exceptions: they exist exactly to see every version.
            exempt = any(x in str(rel) for x in ("scd2", "01-core-views", "09-data-quality"))
            if (not re.search(r"(?i)IS_CURRENT", window) and "CUSTOMER" in table
                    and not exempt):
                findings.append(f"{rel}: reads {table} without an IS_CURRENT predicate - "
                                f"this multiplies every metric by the version count")

    # --- unbounded DML -----------------------------------------------------
    for match in re.finditer(r"(?i)\b(DELETE\s+FROM|UPDATE)\s+([A-Z_.]+)([^;]*);", body):
        verb, target, tail = match.group(1), match.group(2), match.group(3)
        # `WHEN MATCHED THEN UPDATE SET` inside a MERGE is bounded by the ON
        # clause, not by a WHERE. The regex sees the SET keyword as the target.
        if target.upper() == "SET":
            continue
        if "WHERE" in tail.upper():
            continue
        if layer in FULL_REFRESH_DIRS:
            continue      # deliberate full-refresh truncate-and-load
        findings.append(f"{rel}: unbounded {verb.split()[0]} on {target}")

    # --- naming ------------------------------------------------------------
    for match in re.finditer(r"(?i)CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                             r"([A-Za-z0-9_.]+)", body):
        name = match.group(1).split(".")[-1]
        if not re.match(r"^[A-Z][A-Z0-9_]*$", name):
            findings.append(f"{rel}: table name must be SCREAMING_SNAKE_CASE: {name}")
    if re.search(r"(?i)CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                 r"[A-Za-z0-9_.]*\bORDER\b", body):
        findings.append(f"{rel}: ORDER is a reserved word - the entity is SALES_ORDER")


def main() -> int:
    files = sorted(SQL_ROOT.rglob("*.sql")) + sorted((REPO / "mule").rglob("*.sql"))
    for path in files:
        check(path)
    print(f"Linted {len(files)} SQL files.")
    for w in warnings:
        print(f"  WARN  {w}")
    for f in findings:
        print(f"  ERROR {f}")
    if findings:
        print(f"\n{len(findings)} SQL convention violation(s).")
        return 1
    print("All SQL conforms to the conventions in snowflake/README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
