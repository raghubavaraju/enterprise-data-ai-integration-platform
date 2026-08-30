"""Connection helper for the local DuckDB warehouse."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

_LOCK = threading.Lock()
_CONN: duckdb.DuckDBPyConnection | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def db_path() -> Path:
    configured = os.getenv("LOCAL_WAREHOUSE_PATH", "local_warehouse/acme_edp.duckdb")
    p = Path(configured)
    return p if p.is_absolute() else repo_root() / p


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Attach the database file under the alias ACME_EDP.

    Attaching under an explicit alias - and not opening the file directly -
    is what lets the Snowflake scripts keep their fully-qualified
    ``ACME_EDP.<schema>.<table>`` references.  Without it the catalog would take
    its name from the file, every reference would have to be rewritten, and the
    "same SQL runs in both places" claim would stop being true.
    """
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    mode = " (READ_ONLY)" if read_only else ""
    con.execute(f"ATTACH '{path}' AS ACME_EDP{mode}")
    con.execute("USE ACME_EDP")
    return con


def shared() -> duckdb.DuckDBPyConnection:
    """Process-wide connection.  DuckDB allows one writer per file."""
    global _CONN
    with _LOCK:
        if _CONN is None:
            _CONN = connect()
        return _CONN


def query(sql: str, params: list | None = None) -> list[dict]:
    con = shared()
    with _LOCK:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    # strict=True: a row whose width differs from the column list is a
    # driver-level inconsistency, and failing loudly beats silently dropping a column.
    return [dict(zip(cols, r, strict=True)) for r in rows]
