"""
Data Inspector — deterministic DB profiler for forensic databases.

Runs quality checks on a forensic DuckDB and returns structured findings:
  - Period label fragmentation
  - Garbage account names (OCR artifacts, numeric-only, short strings)
  - Related-party entity classification (real entities vs. noise)
  - Extraction duplicates (multi-column parse artifacts)
  - Mixed-unit warnings

No LLM calls.  Pure SQL + regex heuristics.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

# Accounts that are clearly garbage / OCR artifacts
_GARBAGE_ACCOUNT_RX = re.compile(
    r"^[\d\.\-\,\s\%\(\)]+$"     # purely numeric / punctuation
    r"|^\S{1,2}$"                 # single-char or two-char junk
    r"|^\d+\.\d+$"               # decimal number as name  (e.g. "0.99")
    r"|^[\d\s]+$",               # space-separated digits
    re.IGNORECASE,
)

# Entity-like suffixes (company names)
_COMPANY_SUFFIX_RX = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|corp|foundation|trust|"
    r"enterprises|systems|industries|holdings|associates|"
    r"consultants|solutions|services|agency|co\.?)\b",
    re.IGNORECASE,
)

# Person name indicators (honorifics)
_PERSON_PREFIX_RX = re.compile(
    r"^(mr\.?|mrs\.?|ms\.?|dr\.?|shri\.?|smt\.?)\s",
    re.IGNORECASE,
)

# Non-entity noise in related_parties
_NON_ENTITY_RX = re.compile(
    r"^\d+[\.\)]\s"                          # numbered list items "1. ..."
    r"|^\(\w+\)\s"                           # roman/alpha labels "(i) ..."
    r"|^(total|gross|net|balance|closing|opening|payable|receivable)\b"
    r"|^(shortfall|unspent|contribution|construction|acquisition|promotion)\b"
    r"|membership\s+fees"
    r"|CSR|expenditure|amount\s+required"
    r"|^[\d\.\-\,\s]+$"                     # pure numbers
    r"|\bhealth\s*care\b"
    r"|\bprime\s*minister\b"
    r"|\bnational\s*relief\b"
    r"|\beducation\b",
    re.IGNORECASE,
)

# Transaction types masquerading as party names
_TRANSACTION_TYPE_RX = re.compile(
    r"\b(payable|receivable|remuneration|reimbursement|dividend|purchase|"
    r"sales|expenses|services|advance|rent|commission|interest|salary|"
    r"jobwork|material)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Profile result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PeriodProfile:
    """Profile of period labels in the database."""
    raw_labels: list[dict[str, Any]] = field(default_factory=list)
    suggested_map: dict[str, str] = field(default_factory=dict)
    canonical_labels: list[str] = field(default_factory=list)


@dataclass
class AccountProfile:
    """Profile of account names in line_items."""
    total_distinct: int = 0
    garbage_names: list[str] = field(default_factory=list)
    garbage_count: int = 0


@dataclass
class RelatedPartyProfile:
    """Profile of related_parties entity quality."""
    total_distinct: int = 0
    entities: list[str] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    non_entities: list[str] = field(default_factory=list)
    suggested_whitelist: list[str] = field(default_factory=list)


@dataclass
class DuplicateProfile:
    """Profile of extraction-level duplicates."""
    total_dup_groups: int = 0
    total_dup_rows: int = 0
    top_groups: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class UnitProfile:
    """Profile of source_unit distribution."""
    distribution: dict[str, int] = field(default_factory=dict)
    mixed_units: bool = False


@dataclass
class DatabaseProfile:
    """Full database quality profile."""
    periods: PeriodProfile = field(default_factory=PeriodProfile)
    accounts: AccountProfile = field(default_factory=AccountProfile)
    related_parties: RelatedPartyProfile = field(default_factory=RelatedPartyProfile)
    duplicates: DuplicateProfile = field(default_factory=DuplicateProfile)
    units: UnitProfile = field(default_factory=UnitProfile)
    needs_curation: bool = False
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return {
            "periods": {
                "raw_labels": self.periods.raw_labels,
                "suggested_map": self.periods.suggested_map,
                "canonical_labels": self.periods.canonical_labels,
            },
            "accounts": {
                "total_distinct": self.accounts.total_distinct,
                "garbage_names": self.accounts.garbage_names,
                "garbage_count": self.accounts.garbage_count,
            },
            "related_parties": {
                "total_distinct": self.related_parties.total_distinct,
                "entities": self.related_parties.entities,
                "persons": self.related_parties.persons,
                "non_entities": self.related_parties.non_entities,
                "suggested_whitelist": self.related_parties.suggested_whitelist,
            },
            "duplicates": {
                "total_dup_groups": self.duplicates.total_dup_groups,
                "total_dup_rows": self.duplicates.total_dup_rows,
                "top_groups": self.duplicates.top_groups,
            },
            "units": {
                "distribution": self.units.distribution,
                "mixed_units": self.units.mixed_units,
            },
            "needs_curation": self.needs_curation,
            "issues": self.issues,
        }


# ---------------------------------------------------------------------------
# Profiler functions
# ---------------------------------------------------------------------------

def _get_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Return list of table names (and views) in the database."""
    try:
        rows = con.execute("SHOW TABLES").fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def profile_periods(con: duckdb.DuckDBPyConnection) -> PeriodProfile:
    """Profile period label fragmentation and suggest canonical mapping."""
    prof = PeriodProfile()

    try:
        rows = con.execute("""
            SELECT period_label, period_start, period_end, COUNT(*) as cnt
            FROM line_items
            GROUP BY period_label, period_start, period_end
            ORDER BY period_start, period_label
        """).fetchall()
    except Exception:
        return prof

    # Build raw label list
    for label, start, end, cnt in rows:
        prof.raw_labels.append({
            "period_label": label,
            "period_start": str(start) if start else None,
            "period_end": str(end) if end else None,
            "row_count": cnt,
        })

    # Group by (period_start, period_end) → canonical label
    date_groups: dict[tuple[str | None, str | None], list[dict]] = {}
    for entry in prof.raw_labels:
        key = (entry["period_start"], entry["period_end"])
        date_groups.setdefault(key, []).append(entry)

    # Derive canonical label from date range
    for (start, end), entries in date_groups.items():
        canonical = _derive_canonical_label(start, end)
        for entry in entries:
            raw = entry["period_label"]
            if raw != canonical:
                prof.suggested_map[raw] = canonical

    prof.canonical_labels = sorted(set(
        prof.suggested_map.get(e["period_label"], e["period_label"])
        for e in prof.raw_labels
    ))

    return prof


def _derive_canonical_label(start: str | None, end: str | None) -> str:
    """Derive a canonical period label like 'FY 2022-23' from date range."""
    if not start or not end:
        return "Unknown Period"
    try:
        # Parse YYYY-MM-DD
        sy = int(start[:4])
        ey = int(end[:4])
        sm = int(start[5:7])

        # Indian fiscal year: April-March
        if sm >= 3 and sm <= 5:
            # Start is around April → fiscal year starts this calendar year
            fy_start = sy
            fy_end = ey
        else:
            fy_start = sy
            fy_end = ey

        if fy_start == fy_end:
            return f"FY {fy_start}-{fy_start + 1:02d}"

        return f"FY {fy_start}-{str(fy_end)[-2:]}"
    except (ValueError, IndexError):
        return f"{start} to {end}"


def profile_accounts(con: duckdb.DuckDBPyConnection) -> AccountProfile:
    """Detect garbage account names in line_items."""
    prof = AccountProfile()

    try:
        rows = con.execute(
            "SELECT DISTINCT account_name FROM line_items WHERE account_name IS NOT NULL"
        ).fetchall()
    except Exception:
        return prof

    all_names = [r[0] for r in rows]
    prof.total_distinct = len(all_names)

    for name in all_names:
        if _GARBAGE_ACCOUNT_RX.match(name.strip()):
            prof.garbage_names.append(name)

    prof.garbage_count = len(prof.garbage_names)
    return prof


def profile_related_parties(con: duckdb.DuckDBPyConnection) -> RelatedPartyProfile:
    """Classify party_name entries as entity / person / non-entity."""
    prof = RelatedPartyProfile()

    try:
        rows = con.execute(
            "SELECT DISTINCT party_name FROM related_parties WHERE party_name IS NOT NULL"
        ).fetchall()
    except Exception:
        return prof

    all_names = [r[0] for r in rows]
    prof.total_distinct = len(all_names)

    for name in all_names:
        stripped = name.strip()
        if _NON_ENTITY_RX.search(stripped):
            prof.non_entities.append(name)
        elif _PERSON_PREFIX_RX.match(stripped):
            prof.persons.append(name)
        elif _COMPANY_SUFFIX_RX.search(stripped) and not _TRANSACTION_TYPE_RX.search(stripped):
            # Company name with suffix and no transaction-type keywords
            prof.entities.append(name)
        elif _TRANSACTION_TYPE_RX.search(stripped):
            # Transaction types (e.g. "Remuneration", "Purchase of Materials")
            prof.non_entities.append(name)
        elif len(stripped) <= 3 or stripped.replace(".", "").replace(",", "").strip().isdigit():
            prof.non_entities.append(name)
        else:
            # Ambiguous — check length and format
            if len(stripped) > 60:
                prof.non_entities.append(name)
            else:
                # Default: treat as potential entity for whitelist
                prof.entities.append(name)

    prof.suggested_whitelist = sorted(set(prof.entities + prof.persons))
    return prof


def profile_extraction_duplicates(con: duckdb.DuckDBPyConnection) -> DuplicateProfile:
    """Count rows sharing (table_id, account_name, amount, source_page, period_end).

    The fiscal period is part of the key so that an unchanged balance shown
    for both years of a comparative statement is not treated as a duplicate.
    """
    prof = DuplicateProfile()

    try:
        rows = con.execute("""
            SELECT table_id, account_name, amount, source_page, COUNT(*) as cnt
            FROM line_items
            GROUP BY table_id, account_name, amount, source_page, period_end
            HAVING cnt > 1
            ORDER BY cnt DESC
        """).fetchall()
    except Exception:
        return prof

    prof.total_dup_groups = len(rows)
    prof.total_dup_rows = sum(r[4] for r in rows)

    for table_id, acct, amt, page, cnt in rows[:20]:
        prof.top_groups.append({
            "table_id": table_id,
            "account_name": acct,
            "amount": amt,
            "source_page": page,
            "duplicate_count": cnt,
        })

    return prof


def profile_units(con: duckdb.DuckDBPyConnection) -> UnitProfile:
    """Check source_unit distribution and flag mixed units."""
    prof = UnitProfile()

    try:
        rows = con.execute("""
            SELECT source_unit, COUNT(*) as cnt
            FROM line_items
            GROUP BY source_unit
            ORDER BY cnt DESC
        """).fetchall()
    except Exception:
        return prof

    for unit, cnt in rows:
        prof.distribution[unit or "NULL"] = cnt

    non_null_units = [u for u in prof.distribution if u != "NULL"]
    prof.mixed_units = len(non_null_units) > 1

    return prof


# ---------------------------------------------------------------------------
# Main profiler entry point
# ---------------------------------------------------------------------------

def profile_database(db_path: str) -> DatabaseProfile:
    """Run all profilers on the forensic database and return a DatabaseProfile.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB file.

    Returns
    -------
    DatabaseProfile
        Structured profile with quality findings and a needs_curation flag.
    """
    p = Path(db_path)
    if not p.exists():
        print(f"[inspector] Database not found: {db_path}", file=sys.stderr)
        prof = DatabaseProfile()
        prof.issues.append(f"Database not found: {db_path}")
        return prof

    con = duckdb.connect(str(p), read_only=True)
    tables = _get_tables(con)

    profile = DatabaseProfile()
    issues: list[str] = []

    # Periods
    if "line_items" in tables:
        profile.periods = profile_periods(con)
        if len(profile.periods.suggested_map) > 0:
            n_raw = len(profile.periods.raw_labels)
            n_canonical = len(profile.periods.canonical_labels)
            issues.append(
                f"Period fragmentation: {n_raw} raw labels → {n_canonical} canonical periods. "
                f"{len(profile.periods.suggested_map)} labels need remapping."
            )

        # Accounts
        profile.accounts = profile_accounts(con)
        if profile.accounts.garbage_count > 0:
            issues.append(
                f"Garbage accounts: {profile.accounts.garbage_count} of "
                f"{profile.accounts.total_distinct} distinct account names are "
                f"OCR artifacts or numeric-only strings."
            )

        # Extraction duplicates
        profile.duplicates = profile_extraction_duplicates(con)
        if profile.duplicates.total_dup_groups > 0:
            issues.append(
                f"Extraction duplicates: {profile.duplicates.total_dup_groups} groups, "
                f"{profile.duplicates.total_dup_rows} total duplicate rows "
                f"(same table_id + account_name + amount + source_page + period)."
            )

        # Units
        profile.units = profile_units(con)
        if profile.units.mixed_units:
            issues.append(
                f"Mixed units: {list(profile.units.distribution.keys())}. "
                f"Amount comparisons across units will be unreliable."
            )

    # Related parties
    if "related_parties" in tables:
        profile.related_parties = profile_related_parties(con)
        n_noise = len(profile.related_parties.non_entities)
        if n_noise > 0:
            issues.append(
                f"Related-party noise: {n_noise} of "
                f"{profile.related_parties.total_distinct} party names are "
                f"non-entity strings (numbers, CSR text, disclosure headers)."
            )

    con.close()

    profile.issues = issues
    profile.needs_curation = len(issues) > 0
    return profile


# ---------------------------------------------------------------------------
# CLI entry point (for testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("Usage: python data_inspector.py <db_path>", file=sys.stderr)
        sys.exit(1)

    p = profile_database(sys.argv[1])
    print(json.dumps(p.to_dict(), indent=2, default=str))
