"""
Data Curator — creates DuckDB VIEWs for clean skill consumption.

Builds ``curated_line_items`` and ``curated_related_parties`` views based on
agent-provided or auto-derived curation config.  Raw tables are **never**
modified.

Curation actions:
  - Period consolidation (CASE WHEN remap)
  - Extraction dedup (ROW_NUMBER PARTITION BY dup key, keep rn=1)
  - Account exclusion (regex / exact name)
  - Entity whitelist (filter related_parties to real entities only)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb


# ---------------------------------------------------------------------------
# CurationConfig
# ---------------------------------------------------------------------------

@dataclass
class CurationConfig:
    """Describes what curation actions to apply."""

    period_map: dict[str, str] | None = None
    """raw_label → canonical label mapping."""

    deduplicate: bool = True
    """Remove extraction duplicates (same table_id + account_name + amount + source_page)."""

    entity_whitelist: list[str] | None = None
    """For related_parties: keep only these party_names."""

    exclude_account_patterns: list[str] | None = None
    """Regex patterns — accounts matching any pattern are excluded."""

    exclude_account_names: list[str] | None = None
    """Exact account names to exclude."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_map": self.period_map,
            "deduplicate": self.deduplicate,
            "entity_whitelist": self.entity_whitelist,
            "exclude_account_patterns": self.exclude_account_patterns,
            "exclude_account_names": self.exclude_account_names,
        }


# ---------------------------------------------------------------------------
# CurationResult
# ---------------------------------------------------------------------------

@dataclass
class CurationResult:
    """Report of what the curator did."""

    views_created: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    line_items_before: int = 0
    line_items_after: int = 0
    related_parties_before: int = 0
    related_parties_after: int = 0
    config_used: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "views_created": self.views_created,
            "actions": self.actions,
            "line_items_before": self.line_items_before,
            "line_items_after": self.line_items_after,
            "related_parties_before": self.related_parties_before,
            "related_parties_after": self.related_parties_after,
            "config_used": self.config_used,
        }


# ---------------------------------------------------------------------------
# View builders
# ---------------------------------------------------------------------------

def _build_line_items_view_sql(config: CurationConfig) -> str:
    """Build the SQL for the curated_line_items view."""

    # Start with a CTE that handles dedup + period remap + account exclusion
    cte_parts: list[str] = []
    where_clauses: list[str] = []

    # --- Period remap (CASE expression) ---
    if config.period_map:
        cases = []
        for raw, canonical in config.period_map.items():
            safe_raw = raw.replace("'", "''")
            safe_can = canonical.replace("'", "''")
            cases.append(f"WHEN period_label = '{safe_raw}' THEN '{safe_can}'")
        period_expr = "CASE " + " ".join(cases) + " ELSE period_label END"
    else:
        period_expr = "period_label"

    # --- Account exclusion (WHERE clause) ---
    if config.exclude_account_names:
        safe_names = ", ".join(
            f"'{n.replace(chr(39), chr(39)+chr(39))}'" for n in config.exclude_account_names
        )
        where_clauses.append(f"account_name NOT IN ({safe_names})")

    if config.exclude_account_patterns:
        for pat in config.exclude_account_patterns:
            safe_pat = pat.replace("'", "''")
            where_clauses.append(f"NOT regexp_matches(account_name, '{safe_pat}')")

    # --- Build the CTE ---
    where_sql = (" AND ".join(where_clauses)) if where_clauses else "TRUE"

    if config.deduplicate:
        # Dedup with ROW_NUMBER
        sql = f"""CREATE OR REPLACE VIEW curated_line_items AS
WITH deduped AS (
    SELECT *,
        {period_expr} AS curated_period_label,
        ROW_NUMBER() OVER (
            PARTITION BY table_id, account_name, amount, source_page
            ORDER BY created_at
        ) AS _rn
    FROM line_items
    WHERE {where_sql}
)
SELECT
    line_item_id, table_id, account_name, amount, amount_inr,
    curated_period_label AS period_label,
    period_start, period_end, source_unit, source_page,
    source_row, source_col, raw_cell_text,
    is_total, is_comparative, note_ref, tags, created_at
FROM deduped
WHERE _rn = 1"""
    else:
        sql = f"""CREATE OR REPLACE VIEW curated_line_items AS
SELECT
    line_item_id, table_id, account_name, amount, amount_inr,
    {period_expr} AS period_label,
    period_start, period_end, source_unit, source_page,
    source_row, source_col, raw_cell_text,
    is_total, is_comparative, note_ref, tags, created_at
FROM line_items
WHERE {where_sql}"""

    return sql


def _build_related_parties_view_sql(config: CurationConfig) -> str:
    """Build the SQL for the curated_related_parties view."""
    where_clauses: list[str] = []

    # Period remap
    if config.period_map:
        cases = []
        for raw, canonical in config.period_map.items():
            safe_raw = raw.replace("'", "''")
            safe_can = canonical.replace("'", "''")
            cases.append(f"WHEN period_label = '{safe_raw}' THEN '{safe_can}'")
        period_expr = "CASE " + " ".join(cases) + " ELSE period_label END"
    else:
        period_expr = "period_label"

    # Entity whitelist
    if config.entity_whitelist:
        safe_names = ", ".join(
            f"'{n.replace(chr(39), chr(39)+chr(39))}'" for n in config.entity_whitelist
        )
        where_clauses.append(f"party_name IN ({safe_names})")

    where_sql = (" AND ".join(where_clauses)) if where_clauses else "TRUE"

    sql = f"""CREATE OR REPLACE VIEW curated_related_parties AS
SELECT
    rp_id, table_id, party_name, relationship_category,
    transaction_type, amount, amount_inr,
    {period_expr} AS period_label,
    source_unit, tags, created_at
FROM related_parties
WHERE {where_sql}"""

    return sql


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def curate(db_path: str, config: CurationConfig) -> CurationResult:
    """Create curated views in the database based on the provided config.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB database (opened read-write).
    config : CurationConfig
        What curation actions to apply.

    Returns
    -------
    CurationResult
        Report of actions taken and row counts.
    """
    result = CurationResult()
    result.config_used = config.to_dict()

    con = duckdb.connect(str(db_path), read_only=False)
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]

    # --- Curate line_items ---
    if "line_items" in tables:
        result.line_items_before = con.execute(
            "SELECT COUNT(*) FROM line_items"
        ).fetchone()[0]

        view_sql = _build_line_items_view_sql(config)
        con.execute(view_sql)
        result.views_created.append("curated_line_items")

        result.line_items_after = con.execute(
            "SELECT COUNT(*) FROM curated_line_items"
        ).fetchone()[0]

        removed = result.line_items_before - result.line_items_after
        if removed > 0:
            result.actions.append(
                f"curated_line_items: {result.line_items_before} → "
                f"{result.line_items_after} rows ({removed} removed)"
            )
        else:
            result.actions.append(
                f"curated_line_items: {result.line_items_after} rows (no rows removed)"
            )

        if config.period_map:
            result.actions.append(
                f"Period consolidation: {len(config.period_map)} labels remapped"
            )
        if config.deduplicate:
            result.actions.append("Extraction dedup applied (ROW_NUMBER partition)")
        if config.exclude_account_patterns:
            result.actions.append(
                f"Account exclusion: {len(config.exclude_account_patterns)} regex pattern(s)"
            )
        if config.exclude_account_names:
            result.actions.append(
                f"Account exclusion: {len(config.exclude_account_names)} exact name(s)"
            )

    # --- Curate related_parties ---
    if "related_parties" in tables:
        result.related_parties_before = con.execute(
            "SELECT COUNT(*) FROM related_parties"
        ).fetchone()[0]

        view_sql = _build_related_parties_view_sql(config)
        con.execute(view_sql)
        result.views_created.append("curated_related_parties")

        result.related_parties_after = con.execute(
            "SELECT COUNT(*) FROM curated_related_parties"
        ).fetchone()[0]

        removed = result.related_parties_before - result.related_parties_after
        if removed > 0:
            result.actions.append(
                f"curated_related_parties: {result.related_parties_before} → "
                f"{result.related_parties_after} rows ({removed} removed)"
            )
        else:
            result.actions.append(
                f"curated_related_parties: {result.related_parties_after} rows (no rows removed)"
            )

        if config.entity_whitelist:
            result.actions.append(
                f"Entity whitelist: {len(config.entity_whitelist)} entities kept"
            )

    con.close()
    return result


def auto_curate(db_path: str, profile_dict: dict[str, Any]) -> CurationResult:
    """Auto-curate using the inspector's profile suggestions.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB database.
    profile_dict : dict
        Output of DatabaseProfile.to_dict() from the inspector.

    Returns
    -------
    CurationResult
    """
    periods = profile_dict.get("periods", {})
    accounts = profile_dict.get("accounts", {})
    rp = profile_dict.get("related_parties", {})

    config = CurationConfig(
        period_map=periods.get("suggested_map") or None,
        deduplicate=True,
        entity_whitelist=rp.get("suggested_whitelist") or None,
        exclude_account_names=accounts.get("garbage_names") or None,
    )

    return curate(db_path, config)


def has_curated_views(db_path: str) -> bool:
    """Check if curated views already exist in the database."""
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        # DuckDB SHOW TABLES includes views
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return "curated_line_items" in tables or "curated_related_parties" in tables
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI entry point (for testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("Usage: python data_curator.py <db_path> [--auto]", file=sys.stderr)
        sys.exit(1)

    db = sys.argv[1]
    if "--auto" in sys.argv:
        from skills.shared.data_inspector import profile_database
        p = profile_database(db)
        r = auto_curate(db, p.to_dict())
    else:
        r = curate(db, CurationConfig())

    print(json.dumps(r.to_dict(), indent=2, default=str))
    print(f"has_curated_views: {has_curated_views(db)}")
