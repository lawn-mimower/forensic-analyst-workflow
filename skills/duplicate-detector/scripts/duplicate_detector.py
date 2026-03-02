# /// script
# dependencies = ["pandas", "duckdb", "rapidfuzz"]
# ///
"""
Duplicate & Near-Duplicate Detector for Forensic Accounting
============================================================

Detects exact, near-amount, fuzzy-name, and cross-period duplicate line items
in DuckDB financial data.  Also flags round-number concentration.  Designed
for the two-pass forensic workflow:

  Pass 1 (Sweep):  Run all tests with defaults on the full dataset.
  Pass 2 (Investigate):  Re-run with filters based on Pass 1 findings.

Tests implemented:
  - exact_duplicates      : Same account_name + amount + period_label
  - near_amount_duplicates: Same account_name, amounts within ±tolerance
  - fuzzy_name_duplicates : Similar account_name (rapidfuzz ≥ threshold) + same amount
  - cross_period_duplicates: Same account_name + amount across different periods
  - round_number_concentration: % of amounts ending in 000, 00, 50, 0

All output is structured JSON written to --output.
Diagnostics and progress messages go to stderr.

Usage:
  python skills/duplicate-detector/scripts/duplicate_detector.py \\
      --db case.duckdb --output results.json \\
      [--table line_items] [--filter "NOT is_total"] \\
      [--tolerance 0.01] [--fuzzy-threshold 85] [--case-id CASE-001]
"""

from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Allow running from project root: python skills/duplicate-detector/scripts/...
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from skills.shared.forensic_utils import build_meta, load_db, write_output  # noqa: E402

import pandas as pd  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

_LOG_PREFIX = "[duplicate-detector]"


def _log(msg: str) -> None:
    """Print a progress message to stderr."""
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Test 1: Exact Duplicates
# ---------------------------------------------------------------------------

def find_exact_duplicates(df: pd.DataFrame) -> dict[str, Any]:
    """
    GROUP BY account_name, amount, period_label HAVING COUNT > 1.
    Returns groups of exact duplicate line items.
    """
    key_cols = ["account_name", "amount", "period_label"]
    grouped = df.groupby(key_cols, dropna=False)

    duplicates: list[dict[str, Any]] = []
    total_duplicate_rows = 0

    for key, group in grouped:
        if len(group) <= 1:
            continue
        acct, amt, period = key
        items = group[["line_item_id", "table_id", "source_page", "raw_cell_text"]].to_dict("records")
        duplicates.append({
            "account_name": acct,
            "amount": float(amt) if pd.notna(amt) else None,
            "period_label": str(period) if pd.notna(period) else None,
            "count": len(group),
            "line_items": items,
        })
        total_duplicate_rows += len(group)

    return {
        "test_name": "exact_duplicates",
        "duplicate_groups": len(duplicates),
        "total_duplicate_rows": total_duplicate_rows,
        "details": duplicates,
    }


# ---------------------------------------------------------------------------
# Test 2: Near-Amount Duplicates
# ---------------------------------------------------------------------------

def find_near_amount_duplicates(df: pd.DataFrame, tolerance: float) -> dict[str, Any]:
    """
    Same account_name, amounts within ±tolerance fraction of each other.
    Excludes pairs already flagged as exact duplicates.
    """
    matches: list[dict[str, Any]] = []

    for acct_name, group in df.groupby("account_name", dropna=False):
        if len(group) < 2:
            continue
        amounts = group[["line_item_id", "amount", "period_label", "table_id"]].dropna(subset=["amount"])
        if len(amounts) < 2:
            continue

        rows = amounts.to_dict("records")
        for i, j in combinations(range(len(rows)), 2):
            a = rows[i]["amount"]
            b = rows[j]["amount"]
            if a == b:
                continue  # exact dup handled in test 1
            denom = max(abs(a), abs(b))
            if denom == 0:
                continue
            if abs(a - b) / denom <= tolerance:
                matches.append({
                    "account_name": acct_name,
                    "amount_a": float(a),
                    "amount_b": float(b),
                    "difference": round(float(abs(a - b)), 4),
                    "difference_pct": round(float(abs(a - b) / denom * 100), 4),
                    "period_a": rows[i].get("period_label"),
                    "period_b": rows[j].get("period_label"),
                    "line_item_id_a": rows[i]["line_item_id"],
                    "line_item_id_b": rows[j]["line_item_id"],
                })

    return {
        "test_name": "near_amount_duplicates",
        "tolerance": tolerance,
        "matches_found": len(matches),
        "details": matches,
    }


# ---------------------------------------------------------------------------
# Test 3: Fuzzy-Name Duplicates
# ---------------------------------------------------------------------------

def find_fuzzy_name_duplicates(
    df: pd.DataFrame,
    fuzzy_threshold: int,
) -> dict[str, Any]:
    """
    Different account_name but rapidfuzz token_sort_ratio >= threshold,
    with the same exact amount.  Groups by amount first to avoid O(n^2)
    on the full dataset.
    """
    matches: list[dict[str, Any]] = []

    # Build unique (account_name, amount) pairs
    pairs = (
        df[["account_name", "amount"]]
        .dropna(subset=["account_name", "amount"])
        .drop_duplicates()
    )

    # Group by amount — only compare names within the same amount bucket
    for amt, group in pairs.groupby("amount"):
        names = group["account_name"].unique().tolist()
        if len(names) < 2:
            continue
        for i, j in combinations(range(len(names)), 2):
            name_a = names[i]
            name_b = names[j]
            score = fuzz.token_sort_ratio(name_a, name_b)
            if score >= fuzzy_threshold:
                # Find all line_item_ids for each name+amount combo
                ids_a = df.loc[
                    (df["account_name"] == name_a) & (df["amount"] == amt),
                    "line_item_id",
                ].tolist()
                ids_b = df.loc[
                    (df["account_name"] == name_b) & (df["amount"] == amt),
                    "line_item_id",
                ].tolist()
                matches.append({
                    "name_a": name_a,
                    "name_b": name_b,
                    "amount": float(amt),
                    "similarity_score": round(float(score), 2),
                    "line_item_ids_a": ids_a,
                    "line_item_ids_b": ids_b,
                })

    return {
        "test_name": "fuzzy_name_duplicates",
        "fuzzy_threshold": fuzzy_threshold,
        "matches_found": len(matches),
        "details": matches,
    }


# ---------------------------------------------------------------------------
# Test 4: Cross-Period Duplicates
# ---------------------------------------------------------------------------

def find_cross_period_duplicates(df: pd.DataFrame) -> dict[str, Any]:
    """
    Same account_name + same amount across different period_labels.
    """
    matches: list[dict[str, Any]] = []

    # Only rows that actually have a period_label
    subset = df.dropna(subset=["account_name", "amount", "period_label"])
    if subset.empty:
        return {
            "test_name": "cross_period_duplicates",
            "matches_found": 0,
            "details": [],
        }

    grouped = subset.groupby(["account_name", "amount"], dropna=False)

    for (acct, amt), group in grouped:
        periods = group["period_label"].unique()
        if len(periods) < 2:
            continue
        items = (
            group[["line_item_id", "period_label", "table_id", "source_page"]]
            .to_dict("records")
        )
        matches.append({
            "account_name": acct,
            "amount": float(amt) if pd.notna(amt) else None,
            "periods": sorted(str(p) for p in periods),
            "count": len(group),
            "line_items": items,
        })

    return {
        "test_name": "cross_period_duplicates",
        "matches_found": len(matches),
        "details": matches,
    }


# ---------------------------------------------------------------------------
# Test 5: Round-Number Concentration
# ---------------------------------------------------------------------------

def analyze_round_numbers(df: pd.DataFrame) -> dict[str, Any]:
    """
    Percentage of amounts ending in 000, 00, 50, 0.
    Uses the integer part of the absolute value.
    """
    amounts = df["amount"].dropna().abs()
    n = len(amounts)
    if n == 0:
        return {
            "test_name": "round_number_concentration",
            "n_analyzed": 0,
            "concentrations": {},
            "details": [],
        }

    int_amounts = amounts.apply(lambda x: int(round(x)))

    # Count various round-number patterns (from most specific to least)
    ends_000 = int(int_amounts.apply(lambda x: x % 1000 == 0).sum())
    ends_00 = int(int_amounts.apply(lambda x: x % 100 == 0).sum())
    ends_50 = int(int_amounts.apply(lambda x: x % 100 == 50).sum())
    ends_0 = int(int_amounts.apply(lambda x: x % 10 == 0).sum())

    concentrations = {
        "ends_000": {
            "count": ends_000,
            "pct": round(ends_000 / n * 100, 2),
            "description": "Amounts divisible by 1,000",
        },
        "ends_00": {
            "count": ends_00,
            "pct": round(ends_00 / n * 100, 2),
            "description": "Amounts divisible by 100",
        },
        "ends_50": {
            "count": ends_50,
            "pct": round(ends_50 / n * 100, 2),
            "description": "Amounts ending in 50 (mod 100)",
        },
        "ends_0": {
            "count": ends_0,
            "pct": round(ends_0 / n * 100, 2),
            "description": "Amounts divisible by 10",
        },
    }

    # Top round amounts by frequency
    round_mask = int_amounts.apply(lambda x: x % 100 == 0 or x % 100 == 50)
    if round_mask.any():
        round_vals = int_amounts[round_mask]
        top_round = (
            round_vals.value_counts()
            .head(10)
            .reset_index()
        )
        top_round.columns = ["amount", "count"]
        top_details = top_round.to_dict("records")
    else:
        top_details = []

    return {
        "test_name": "round_number_concentration",
        "n_analyzed": n,
        "concentrations": concentrations,
        "top_round_amounts": top_details,
    }


# ---------------------------------------------------------------------------
# Risk Scoring
# ---------------------------------------------------------------------------

def compute_risk_score(findings: dict[str, dict]) -> int:
    """
    Risk score 1-10 based on:
      - Exact duplicate groups (high weight)
      - Fuzzy matches (medium weight)
      - Round-number concentration (lower weight)
    """
    score = 1.0

    # Exact duplicates -- high weight
    exact = findings.get("exact_duplicates", {})
    n_exact_groups = exact.get("duplicate_groups", 0)
    if n_exact_groups >= 10:
        score += 4.0
    elif n_exact_groups >= 5:
        score += 3.0
    elif n_exact_groups >= 2:
        score += 2.0
    elif n_exact_groups >= 1:
        score += 1.0

    # Near-amount duplicates
    near = findings.get("near_amount_duplicates", {})
    n_near = near.get("matches_found", 0)
    if n_near >= 10:
        score += 1.5
    elif n_near >= 3:
        score += 1.0
    elif n_near >= 1:
        score += 0.5

    # Fuzzy-name duplicates -- medium weight
    fuzzy = findings.get("fuzzy_name_duplicates", {})
    n_fuzzy = fuzzy.get("matches_found", 0)
    if n_fuzzy >= 10:
        score += 2.0
    elif n_fuzzy >= 5:
        score += 1.5
    elif n_fuzzy >= 2:
        score += 1.0
    elif n_fuzzy >= 1:
        score += 0.5

    # Cross-period duplicates
    cross = findings.get("cross_period_duplicates", {})
    n_cross = cross.get("matches_found", 0)
    if n_cross >= 20:
        score += 1.0
    elif n_cross >= 5:
        score += 0.5

    # Round-number concentration
    rnd = findings.get("round_number_concentration", {})
    concentrations = rnd.get("concentrations", {})
    ends_00_pct = concentrations.get("ends_00", {}).get("pct", 0)
    if ends_00_pct >= 50:
        score += 2.0
    elif ends_00_pct >= 30:
        score += 1.0
    elif ends_00_pct >= 15:
        score += 0.5

    return max(1, min(10, int(round(score))))


# ---------------------------------------------------------------------------
# Investigation Suggestions
# ---------------------------------------------------------------------------

def generate_suggestions(findings: dict[str, dict]) -> list[str]:
    """Generate follow-up investigation suggestions based on findings."""
    suggestions: list[str] = []

    # --- Exact duplicates ---
    exact = findings.get("exact_duplicates", {})
    n_exact = exact.get("duplicate_groups", 0)
    if n_exact > 0:
        total_rows = exact.get("total_duplicate_rows", 0)
        suggestions.append(
            f"Found {n_exact} exact duplicate group(s) comprising {total_rows} rows. "
            f"Verify whether these represent data extraction artifacts (same cell read "
            f"twice) or genuine double-booked entries. Cross-reference with source "
            f"documents and check if both entries hit the general ledger."
        )

    # --- Near-amount duplicates ---
    near = findings.get("near_amount_duplicates", {})
    n_near = near.get("matches_found", 0)
    if n_near > 0:
        suggestions.append(
            f"Found {n_near} near-amount duplicate pair(s) within tolerance. "
            f"These may indicate slightly modified duplicate entries to evade exact-match "
            f"controls. Compare the original vouchers for these pairs and verify "
            f"whether both amounts are supported by independent documentation."
        )

    # --- Fuzzy-name duplicates ---
    fuzzy = findings.get("fuzzy_name_duplicates", {})
    n_fuzzy = fuzzy.get("matches_found", 0)
    if n_fuzzy > 0:
        suggestions.append(
            f"Found {n_fuzzy} fuzzy-name duplicate pair(s) -- different account names "
            f"with the same amount and high name similarity. This may indicate renamed "
            f"line items to disguise duplication. Verify whether these represent the "
            f"same underlying transaction booked under different account headings."
        )
        # Show top examples if available
        details = fuzzy.get("details", [])
        if details:
            examples = details[:3]
            for ex in examples:
                suggestions.append(
                    f"  Fuzzy match: '{ex['name_a']}' vs '{ex['name_b']}' "
                    f"(score={ex['similarity_score']}, amount={ex['amount']})"
                )

    # --- Cross-period duplicates ---
    cross = findings.get("cross_period_duplicates", {})
    n_cross = cross.get("matches_found", 0)
    if n_cross > 0:
        suggestions.append(
            f"Found {n_cross} cross-period duplicate(s) -- same account + amount "
            f"appearing across different periods. While some are expected (e.g., "
            f"straight-line depreciation, fixed rent), a high count on non-recurring "
            f"items suggests copy-paste from prior period. Filter by account type "
            f"to separate recurring from non-recurring items."
        )

    # --- Round-number concentration ---
    rnd = findings.get("round_number_concentration", {})
    concentrations = rnd.get("concentrations", {})
    ends_00_pct = concentrations.get("ends_00", {}).get("pct", 0)
    ends_000_pct = concentrations.get("ends_000", {}).get("pct", 0)
    if ends_00_pct >= 30:
        suggestions.append(
            f"Round-number concentration is high: {ends_00_pct:.1f}% of amounts "
            f"are divisible by 100, {ends_000_pct:.1f}% by 1,000. "
            f"In natural financial data, round numbers typically comprise 10-15% "
            f"of entries. High concentration suggests estimation, fabrication, or "
            f"use of provisional figures. Verify supporting documents for the "
            f"largest round amounts."
        )
    elif ends_00_pct >= 15:
        suggestions.append(
            f"Moderate round-number concentration: {ends_00_pct:.1f}% of amounts "
            f"divisible by 100. Cross-reference with Benford's last-two-digit "
            f"test results for corroboration."
        )

    if not suggestions:
        suggestions.append(
            "No significant duplicate patterns detected. Data appears clean "
            "from a duplication perspective. Proceed with other forensic tests."
        )

    return suggestions


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(findings: dict[str, dict], n_records: int) -> dict[str, Any]:
    """Create a concise summary dict for the output."""
    exact = findings.get("exact_duplicates", {})
    near = findings.get("near_amount_duplicates", {})
    fuzzy = findings.get("fuzzy_name_duplicates", {})
    cross = findings.get("cross_period_duplicates", {})
    rnd = findings.get("round_number_concentration", {})

    return {
        "total_records_analyzed": n_records,
        "exact_duplicate_groups": exact.get("duplicate_groups", 0),
        "exact_duplicate_rows": exact.get("total_duplicate_rows", 0),
        "near_amount_matches": near.get("matches_found", 0),
        "fuzzy_name_matches": fuzzy.get("matches_found", 0),
        "cross_period_matches": cross.get("matches_found", 0),
        "round_number_pct_ends_00": rnd.get("concentrations", {}).get("ends_00", {}).get("pct", 0),
        "round_number_pct_ends_000": rnd.get("concentrations", {}).get("ends_000", {}).get("pct", 0),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Duplicate & near-duplicate detection for forensic accounting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pass 1 sweep on all line items
  python duplicate_detector.py --db case.duckdb --output results.json

  # Pass 2 targeted re-run excluding totals
  python duplicate_detector.py --db case.duckdb --output results.json \\
      --filter "NOT is_total AND NOT is_comparative" --tolerance 0.02
        """,
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database file")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument(
        "--table", default="line_items",
        help="Table name to analyze (default: line_items)",
    )
    parser.add_argument(
        "--filter", default=None,
        help="SQL WHERE clause to filter data",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.01,
        help="Near-amount tolerance as a fraction (default: 0.01 = 1%%)",
    )
    parser.add_argument(
        "--fuzzy-threshold", type=int, default=85,
        help="Minimum rapidfuzz token_sort_ratio for fuzzy match (default: 85)",
    )
    parser.add_argument(
        "--case-id", default=None,
        help="Case identifier for audit trail",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    meta = build_meta(
        skill_name="duplicate-detector",
        db_path=args.db,
        table=args.table,
        filter_sql=args.filter,
        case_id=args.case_id,
        extra={
            "tolerance": args.tolerance,
            "fuzzy_threshold": args.fuzzy_threshold,
        },
    )

    # --- Connect and load data ---
    _log(f"Connecting to {args.db}...")
    con = load_db(args.db)

    # Validate table exists
    try:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    except Exception:
        tables = []
    if args.table not in tables:
        con.close()
        _log(f"ERROR: Table '{args.table}' not found. Available: {tables}")
        sys.exit(1)

    # Build query -- select columns needed for all five tests
    columns = [
        "line_item_id", "table_id", "account_name", "amount",
        "period_label", "source_page", "source_row", "raw_cell_text",
        "is_total", "is_comparative",
    ]
    # Only select columns that actually exist in the table
    try:
        col_info = con.execute(f'DESCRIBE "{args.table}"').fetchall()
        existing_cols = {row[0] for row in col_info}
    except Exception as e:
        con.close()
        _log(f"ERROR: Cannot describe table: {e}")
        sys.exit(1)

    select_cols = [c for c in columns if c in existing_cols]
    if "account_name" not in existing_cols or "amount" not in existing_cols:
        con.close()
        _log("ERROR: Table must have 'account_name' and 'amount' columns.")
        sys.exit(1)

    col_str = ", ".join(f'"{c}"' for c in select_cols)
    query = f'SELECT {col_str} FROM "{args.table}"'
    if args.filter:
        query += f" WHERE {args.filter}"

    _log(f"Executing: {query}")
    try:
        df = con.execute(query).df()
    except Exception as e:
        con.close()
        _log(f"ERROR: Query failed: {e}")
        sys.exit(1)

    con.close()

    n_records = len(df)
    meta["total_records"] = n_records
    _log(f"Loaded {n_records} records")

    if n_records == 0:
        _log("WARNING: No records loaded. Writing empty results.")
        result = {
            "meta": meta,
            "findings": {},
            "summary": {"total_records_analyzed": 0},
            "risk_score": 1,
            "investigation_suggestions": ["No records to analyze."],
        }
        write_output(result, args.output)
        return

    # Ensure amount is numeric
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    # --- Run all five tests ---
    findings: dict[str, dict] = {}

    _log("Running test 1/5: exact duplicates...")
    findings["exact_duplicates"] = find_exact_duplicates(df)
    _log(
        f"  Found {findings['exact_duplicates']['duplicate_groups']} "
        f"duplicate group(s)"
    )

    _log("Running test 2/5: near-amount duplicates...")
    findings["near_amount_duplicates"] = find_near_amount_duplicates(
        df, args.tolerance
    )
    _log(
        f"  Found {findings['near_amount_duplicates']['matches_found']} "
        f"near-amount match(es)"
    )

    _log("Running test 3/5: fuzzy-name duplicates...")
    findings["fuzzy_name_duplicates"] = find_fuzzy_name_duplicates(
        df, args.fuzzy_threshold
    )
    _log(
        f"  Found {findings['fuzzy_name_duplicates']['matches_found']} "
        f"fuzzy-name match(es)"
    )

    _log("Running test 4/5: cross-period duplicates...")
    findings["cross_period_duplicates"] = find_cross_period_duplicates(df)
    _log(
        f"  Found {findings['cross_period_duplicates']['matches_found']} "
        f"cross-period match(es)"
    )

    _log("Running test 5/5: round-number concentration...")
    findings["round_number_concentration"] = analyze_round_numbers(df)
    rnd_pct = (
        findings["round_number_concentration"]
        .get("concentrations", {})
        .get("ends_00", {})
        .get("pct", 0)
    )
    _log(f"  Round-number concentration (ends_00): {rnd_pct:.1f}%")

    # --- Risk score ---
    risk_score = compute_risk_score(findings)
    _log(f"Risk score: {risk_score}/10")

    # --- Summary and suggestions ---
    summary = build_summary(findings, n_records)
    suggestions = generate_suggestions(findings)

    # --- Assemble and write output ---
    result = {
        "meta": meta,
        "findings": findings,
        "summary": summary,
        "risk_score": risk_score,
        "investigation_suggestions": suggestions,
    }
    write_output(result, args.output)

    _log(f"Risk score: {risk_score}/10")
    _log(f"Results written to {args.output}")
    if suggestions:
        _log(f"Investigation suggestions: {len(suggestions)}")


if __name__ == "__main__":
    main()
