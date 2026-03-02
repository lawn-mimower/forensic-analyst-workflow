"""
Shared utilities for forensic analysis skills.

Provides common boilerplate: DB connection, audit-trail metadata, JSON output.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


def load_db(db_path: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection, or exit with an error."""
    p = Path(db_path)
    if not p.exists():
        print(f"[ERROR] Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    return duckdb.connect(str(p), read_only=True)


def build_meta(
    *,
    skill_name: str,
    db_path: str,
    table: str | None = None,
    column: str | None = None,
    filter_sql: str | None = None,
    case_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return audit-trail metadata dict matching the Benford's pattern."""
    meta: dict[str, Any] = {
        "skill": skill_name,
        "case_id": case_id or "unspecified",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": str(uuid.uuid4()),
        "db_path": db_path,
    }
    if table:
        meta["table"] = table
    if column:
        meta["column"] = column
    if filter_sql:
        meta["filter_applied"] = filter_sql
    if extra:
        meta.update(extra)
    return meta


def write_output(result: dict[str, Any], output_path: str) -> None:
    """Serialize *result* to JSON at *output_path*, creating dirs as needed."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[output] Written to {output_path}", file=sys.stderr)
