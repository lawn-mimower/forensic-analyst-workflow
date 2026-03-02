# /// script
# dependencies = ["duckdb", "rapidfuzz", "pandas"]
# ///
"""
Financial Ratio Analyzer for Forensic Accounting
==================================================

Computes financial ratios from DuckDB line_items, fuzzy-matching raw account
names to standard categories.  Compares ratios across periods and flags
anomalous year-on-year changes.

Designed for the two-pass forensic workflow:

  Pass 1 (Sweep):  Compute all ratios with default thresholds.
  Pass 2 (Investigate):  Re-run with --filter to focus on specific
                         table_type or accounts.

All output is structured JSON written to --output.
Diagnostics and progress messages go to stderr.

Usage:
  python ratio_analyzer.py --db case.duckdb --output results.json
  python ratio_analyzer.py --db case.duckdb --output results.json \
      --filter "NOT is_total" --change-threshold 0.15 --case-id CASE-001
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Project-root import shimming (same pattern as benfords.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.forensic_utils import build_meta, load_db, write_output  # noqa: E402

# ---------------------------------------------------------------------------
# Account category mapping (~30 entries)
# ---------------------------------------------------------------------------

ACCOUNT_CATEGORIES: dict[str, list[str]] = {
    "revenue": [
        "revenue from operations",
        "revenue",
        "sales",
        "turnover",
        "income from operations",
    ],
    "other_income": [
        "other income",
        "non-operating income",
    ],
    "total_income": [
        "total income",
        "total revenue",
    ],
    "cogs": [
        "cost of materials consumed",
        "cost of goods sold",
        "cogs",
        "purchases",
        "cost of materials",
    ],
    "employee_expense": [
        "employee benefits expense",
        "employee benefit expense",
        "staff cost",
        "salaries",
        "employee cost",
    ],
    "depreciation": [
        "depreciation and amortisation",
        "depreciation",
        "depreciation and amortization",
    ],
    "other_expense": [
        "other expenses",
        "other expenditure",
        "administrative expenses",
    ],
    "total_expense": [
        "total expenses",
        "total expenditure",
    ],
    "operating_profit": [
        "operating profit",
        "ebitda",
        "profit from operations",
    ],
    "pbt": [
        "profit before tax",
        "profit before taxation",
        "pbt",
    ],
    "tax_expense": [
        "tax expense",
        "income tax",
        "current tax",
        "tax",
    ],
    "pat": [
        "profit after tax",
        "net profit",
        "profit for the year",
        "profit for the period",
        "pat",
    ],
    "current_assets": [
        "current assets",
        "total current assets",
    ],
    "current_liabilities": [
        "current liabilities",
        "total current liabilities",
    ],
    "total_assets": [
        "total assets",
    ],
    "total_liabilities": [
        "total liabilities",
    ],
    "equity": [
        "shareholders equity",
        "total equity",
        "shareholders funds",
        "net worth",
    ],
    "finance_cost": [
        "finance costs",
        "interest expense",
        "finance cost",
        "borrowing costs",
    ],
    "inventory": [
        "inventories",
        "inventory",
        "stock in trade",
    ],
    "trade_receivables": [
        "trade receivables",
        "debtors",
        "accounts receivable",
    ],
    "trade_payables": [
        "trade payables",
        "creditors",
        "accounts payable",
    ],
    "cash": [
        "cash and cash equivalents",
        "cash and bank",
        "cash",
    ],
}

MATCH_THRESHOLD = 75  # rapidfuzz score floor

# Account names containing these words are ratio/metric descriptors, not line items
_EXCLUDE_PATTERNS = re.compile(r"\bratio\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

_FY_RE = re.compile(r"(\d{4})")


def _period_sort_key(label: str) -> int:
    """Extract a sortable integer from a period label like 'FY 2023-24'.

    Returns the first 4-digit year found, or 0 if none.  For labels like
    '2023-24' we return the starting year (2023).
    """
    match = _FY_RE.search(label)
    return int(match.group(1)) if match else 0


def _sort_periods(labels: list[str]) -> list[str]:
    """Return period labels sorted chronologically (ascending)."""
    return sorted(labels, key=_period_sort_key)


# ---------------------------------------------------------------------------
# Fuzzy matching engine
# ---------------------------------------------------------------------------

def match_accounts(
    raw_names: list[str],
) -> dict[str, dict[str, Any]]:
    """Match raw account_name values to standard categories.

    Returns a dict keyed by raw name with::

        {
            "category": "<matched_category>",
            "best_alias": "<alias that scored highest>",
            "score": <int>,
        }

    or ``None`` value when no category meets the threshold.
    """
    results: dict[str, dict[str, Any] | None] = {}
    for raw in raw_names:
        # Skip ratio/metric descriptors that aren't actual line items
        if _EXCLUDE_PATTERNS.search(raw):
            results[raw] = None
            continue
        raw_lower = raw.strip().lower()
        best_cat: str | None = None
        best_alias: str | None = None
        best_score: int = 0
        for category, aliases in ACCOUNT_CATEGORIES.items():
            for alias in aliases:
                score = fuzz.token_sort_ratio(raw_lower, alias)
                if score > best_score:
                    best_score = score
                    best_cat = category
                    best_alias = alias
        if best_score >= MATCH_THRESHOLD and best_cat is not None:
            results[raw] = {
                "category": best_cat,
                "best_alias": best_alias,
                "score": best_score,
            }
        else:
            results[raw] = None
    return results


# ---------------------------------------------------------------------------
# Data retrieval
# ---------------------------------------------------------------------------

def _fetch_line_items(
    con: duckdb.DuckDBPyConnection,
    table: str,
    filter_sql: str | None,
) -> pd.DataFrame:
    """Fetch line items as a DataFrame."""
    cols = "account_name, amount, period_label, is_total, is_comparative, table_id"
    query = f'SELECT {cols} FROM "{table}"'
    if filter_sql:
        query += f" WHERE {filter_sql}"
    print(f"[ratio-analyzer] Query: {query}", file=sys.stderr)
    return con.execute(query).df()


def _fetch_table_types(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, str]:
    """Return table_id -> table_type mapping from source_tables."""
    try:
        rows = con.execute("SELECT table_id, table_type FROM source_tables").fetchall()
        return {r[0]: (r[1] or "") for r in rows}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Build per-period amounts for each matched category
# ---------------------------------------------------------------------------

def _build_category_amounts(
    df: pd.DataFrame,
    account_matches: dict[str, dict[str, Any] | None],
) -> dict[str, dict[str, float]]:
    """Return {category: {period_label: amount}}.

    Strategy:
      - Prefer non-total line items for individual accounts.
      - Fall back to total items for aggregate categories (total_income,
        total_expense, etc.).
      - If multiple rows map to the same category+period, sum them (e.g.
        two tables covering the same line).
    """
    aggregate_cats = {
        "total_income",
        "total_expense",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "total_liabilities",
        "equity",
    }

    # Separate non-total and total rows
    df_nontotal = df[~df["is_total"].fillna(False).astype(bool)]
    df_total = df[df["is_total"].fillna(False).astype(bool)]

    cat_amounts: dict[str, dict[str, float]] = {}

    for raw_name, match in account_matches.items():
        if match is None:
            continue
        cat = match["category"]

        # Pick source: totals for aggregate categories, non-totals otherwise
        if cat in aggregate_cats:
            source = df_total[df_total["account_name"] == raw_name]
            if source.empty:
                source = df_nontotal[df_nontotal["account_name"] == raw_name]
        else:
            source = df_nontotal[df_nontotal["account_name"] == raw_name]
            if source.empty:
                source = df_total[df_total["account_name"] == raw_name]

        for _, row in source.iterrows():
            period = row["period_label"]
            amt = row["amount"]
            if pd.isna(amt) or pd.isna(period):
                continue
            cat_amounts.setdefault(cat, {})
            cat_amounts[cat][period] = cat_amounts[cat].get(period, 0.0) + float(amt)

    return cat_amounts


# ---------------------------------------------------------------------------
# Ratio computation
# ---------------------------------------------------------------------------

def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Divide, returning None if denominator is zero/None or numerator is None."""
    if numerator is None or denominator is None or denominator == 0.0:
        return None
    return numerator / denominator


def _compute_ratios_for_period(
    cat_amounts: dict[str, dict[str, float]],
    period: str,
) -> dict[str, float | None]:
    """Compute all financial ratios for a single period.

    Returns a dict of ratio_name -> value (or None when not computable).
    """

    def _get(cat: str) -> float | None:
        return cat_amounts.get(cat, {}).get(period)

    revenue = _get("revenue")
    cogs = _get("cogs")
    pat = _get("pat")
    total_income = _get("total_income")
    total_expense = _get("total_expense")
    operating_profit = _get("operating_profit")
    current_assets = _get("current_assets")
    current_liabilities = _get("current_liabilities")

    ratios: dict[str, float | None] = {}

    # Gross margin
    if revenue is not None and cogs is not None and revenue != 0:
        ratios["gross_margin"] = (revenue - cogs) / revenue
    else:
        ratios["gross_margin"] = None

    # Operating margin
    if operating_profit is not None and revenue is not None and revenue != 0:
        ratios["operating_margin"] = operating_profit / revenue
    elif (
        total_income is not None
        and total_expense is not None
        and revenue is not None
        and revenue != 0
    ):
        ratios["operating_margin"] = (total_income - total_expense) / revenue
    else:
        ratios["operating_margin"] = None

    # Net margin
    ratios["net_margin"] = _safe_div(pat, revenue)

    # Expense-to-revenue for each expense category
    expense_cats = [
        "cogs",
        "employee_expense",
        "depreciation",
        "other_expense",
        "finance_cost",
        "tax_expense",
    ]
    for ecat in expense_cats:
        val = _get(ecat)
        ratio_name = f"{ecat}_to_revenue"
        ratios[ratio_name] = _safe_div(val, revenue)

    # Current ratio (balance sheet)
    ratios["current_ratio"] = _safe_div(current_assets, current_liabilities)

    return ratios


# ---------------------------------------------------------------------------
# YoY growth
# ---------------------------------------------------------------------------

def _compute_yoy_growth(
    cat_amounts: dict[str, dict[str, float]],
    prior_period: str,
    current_period: str,
) -> dict[str, dict[str, Any]]:
    """Compute year-on-year growth for every matched category.

    Returns {category: {current, prior, change, pct_change}}.
    """
    growth: dict[str, dict[str, Any]] = {}
    for cat, amounts in cat_amounts.items():
        cur = amounts.get(current_period)
        pri = amounts.get(prior_period)
        if cur is None or pri is None:
            continue
        abs_change = cur - pri
        pct_change = abs_change / abs(pri) if pri != 0 else None
        growth[cat] = {
            "current_period": current_period,
            "prior_period": prior_period,
            "current_amount": round(cur, 4),
            "prior_amount": round(pri, 4),
            "absolute_change": round(abs_change, 4),
            "pct_change": round(pct_change, 4) if pct_change is not None else None,
        }
    return growth


# ---------------------------------------------------------------------------
# Ratio change detection & flagging
# ---------------------------------------------------------------------------

def _compute_ratio_changes(
    ratios_by_period: dict[str, dict[str, float | None]],
    prior_period: str,
    current_period: str,
) -> list[dict[str, Any]]:
    """Compute the absolute change in each ratio between two periods."""
    changes: list[dict[str, Any]] = []
    prior = ratios_by_period.get(prior_period, {})
    current = ratios_by_period.get(current_period, {})

    all_keys = sorted(set(prior.keys()) | set(current.keys()))
    for key in all_keys:
        p_val = prior.get(key)
        c_val = current.get(key)
        if p_val is None or c_val is None:
            continue
        abs_change = c_val - p_val
        changes.append(
            {
                "ratio": key,
                "prior_period": prior_period,
                "current_period": current_period,
                "prior_value": round(p_val, 6),
                "current_value": round(c_val, 6),
                "absolute_change": round(abs_change, 6),
            }
        )
    return changes


def _flag_changes(
    ratio_changes: list[dict[str, Any]],
    yoy_growth: dict[str, dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    """Flag ratio changes exceeding the absolute threshold AND large YoY moves."""
    flagged: list[dict[str, Any]] = []

    # Flag ratio changes
    for rc in ratio_changes:
        if abs(rc["absolute_change"]) > threshold:
            direction = "increase" if rc["absolute_change"] > 0 else "decrease"
            flagged.append(
                {
                    "type": "ratio_change",
                    "ratio": rc["ratio"],
                    "absolute_change": rc["absolute_change"],
                    "prior_value": rc["prior_value"],
                    "current_value": rc["current_value"],
                    "direction": direction,
                    "severity": _change_severity(abs(rc["absolute_change"]), threshold),
                }
            )

    # Flag YoY growth > threshold
    for cat, g in yoy_growth.items():
        pct = g.get("pct_change")
        if pct is not None and abs(pct) > threshold:
            direction = "increase" if pct > 0 else "decrease"
            flagged.append(
                {
                    "type": "yoy_growth",
                    "account_category": cat,
                    "pct_change": g["pct_change"],
                    "absolute_change": g["absolute_change"],
                    "direction": direction,
                    "severity": _change_severity(abs(pct), threshold),
                }
            )

    return flagged


def _change_severity(abs_change: float, threshold: float) -> str:
    """Classify change severity as low / medium / high / extreme."""
    ratio = abs_change / threshold if threshold > 0 else 0
    if ratio <= 1.5:
        return "low"
    if ratio <= 3.0:
        return "medium"
    if ratio <= 5.0:
        return "high"
    return "extreme"


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def _compute_risk_score(
    flagged: list[dict[str, Any]],
    ratio_changes: list[dict[str, Any]],
    yoy_growth: dict[str, dict[str, Any]],
    threshold: float,
) -> int:
    """Compute a 1-10 risk score.

    Factors:
      - Number of flagged items
      - Severity distribution
      - Contradictory patterns (e.g. margin up + revenue down)
    """
    if not flagged:
        return 1

    score = 1.0

    # Count by severity
    severity_weights = {"low": 0.5, "medium": 1.0, "high": 2.0, "extreme": 3.0}
    total_weight = sum(
        severity_weights.get(f.get("severity", "low"), 0.5) for f in flagged
    )
    score += min(total_weight, 5.0)

    # Bonus for many flags
    n_flags = len(flagged)
    if n_flags >= 3:
        score += 1.0
    if n_flags >= 6:
        score += 1.0

    # Contradictory pattern bonus: margin improving while revenue declining
    revenue_growth = yoy_growth.get("revenue", {}).get("pct_change")
    margin_changes = {
        rc["ratio"]: rc["absolute_change"]
        for rc in ratio_changes
        if rc["ratio"] in ("gross_margin", "operating_margin", "net_margin")
    }
    if revenue_growth is not None and revenue_growth < 0:
        for _margin, change in margin_changes.items():
            if change > 0:
                score += 1.5
                break

    return max(1, min(10, int(round(score))))


# ---------------------------------------------------------------------------
# Investigation suggestions
# ---------------------------------------------------------------------------

def _generate_suggestions(
    flagged: list[dict[str, Any]],
    yoy_growth: dict[str, dict[str, Any]],
    ratios_by_period: dict[str, dict[str, float | None]],
    cat_amounts: dict[str, dict[str, float]],
    periods: list[str],
) -> list[str]:
    """Generate plain-English, deterministic investigation suggestions."""
    suggestions: list[str] = []

    if len(periods) < 2:
        suggestions.append(
            "Only one period detected. Ratio change analysis requires at least "
            "two periods. Ingest comparative financial statements to enable "
            "year-on-year comparison."
        )
        return suggestions

    current = periods[-1]
    prior = periods[-2]

    # 1. Margin improvement + revenue decline
    rev_g = yoy_growth.get("revenue", {}).get("pct_change")
    current_ratios = ratios_by_period.get(current, {})
    prior_ratios = ratios_by_period.get(prior, {})

    for margin_name in ("gross_margin", "operating_margin", "net_margin"):
        c_m = current_ratios.get(margin_name)
        p_m = prior_ratios.get(margin_name)
        if c_m is not None and p_m is not None and c_m > p_m:
            if rev_g is not None and rev_g < 0:
                suggestions.append(
                    f"{margin_name.replace('_', ' ').title()} improved from "
                    f"{p_m:.2%} to {c_m:.2%} while revenue declined by "
                    f"{abs(rev_g):.1%}. This may indicate expense suppression "
                    f"or cost reclassification. Cross-reference with Benford's "
                    f"analysis on expense amounts."
                )

    # 2. Single expense line spike
    expense_cats = [
        "cogs",
        "employee_expense",
        "depreciation",
        "other_expense",
        "finance_cost",
    ]
    big_moves = []
    stable_count = 0
    for ecat in expense_cats:
        g = yoy_growth.get(ecat, {}).get("pct_change")
        if g is not None:
            if abs(g) > 0.30:
                big_moves.append((ecat, g))
            else:
                stable_count += 1

    if len(big_moves) == 1 and stable_count >= 2:
        ecat, g = big_moves[0]
        direction = "increase" if g > 0 else "decrease"
        suggestions.append(
            f"Only '{ecat}' shows a large {direction} ({g:+.1%}) while other "
            f"expense lines are stable. This isolated movement may indicate "
            f"targeted manipulation or reclassification. Run duplicate "
            f"detection on this expense category."
        )

    # 3. Revenue growth without asset growth
    rev_g = yoy_growth.get("revenue", {}).get("pct_change")
    asset_g = yoy_growth.get("total_assets", {}).get("pct_change")
    recv_g = yoy_growth.get("trade_receivables", {}).get("pct_change")
    if rev_g is not None and rev_g > 0.30:
        if asset_g is not None and asset_g < 0.10:
            suggestions.append(
                f"Revenue grew {rev_g:.1%} but total assets grew only "
                f"{asset_g:.1%}. Investigate whether revenue growth is "
                f"supported by real asset expansion."
            )
        if recv_g is not None and recv_g > rev_g * 1.5:
            suggestions.append(
                f"Trade receivables grew {recv_g:.1%}, significantly "
                f"outpacing revenue growth of {rev_g:.1%}. This may indicate "
                f"channel stuffing or fictitious revenue recognition."
            )

    # 4. Extreme YoY in any line
    for f in flagged:
        if f["type"] == "yoy_growth" and f.get("severity") in ("high", "extreme"):
            cat = f["account_category"]
            pct = f["pct_change"]
            suggestions.append(
                f"'{cat}' shows {f['severity']} year-on-year change of "
                f"{pct:+.1%}. Drill into sub-ledger or journal entries for "
                f"this account to identify the driver."
            )

    # 5. No computable ratios
    any_ratio = any(
        v is not None
        for period_ratios in ratios_by_period.values()
        for v in period_ratios.values()
    )
    if not any_ratio:
        suggestions.append(
            "No financial ratios could be computed. This likely means account "
            "names did not match standard categories. Review the "
            "account_matching section and verify the input data contains "
            "recognizable P&L or balance sheet line items."
        )

    return suggestions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Financial ratio analysis for forensic accounting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pass 1 sweep
  python ratio_analyzer.py --db case.duckdb --output ratios.json

  # Pass 2 filtered re-run
  python ratio_analyzer.py --db case.duckdb --output ratios.json \\
      --filter "NOT is_total" --change-threshold 0.15 --case-id CASE-001
        """,
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database file")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument(
        "--table",
        default="line_items",
        help="Table name to analyze (default: line_items)",
    )
    parser.add_argument(
        "--filter", default=None, help="SQL WHERE clause to filter data"
    )
    parser.add_argument(
        "--change-threshold",
        type=float,
        default=0.20,
        help="Flag ratio changes above this absolute amount (default: 0.20)",
    )
    parser.add_argument(
        "--case-id", default=None, help="Case identifier for audit trail"
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    meta = build_meta(
        skill_name="ratio-analyzer",
        db_path=args.db,
        table=args.table,
        filter_sql=args.filter,
        case_id=args.case_id,
        extra={"change_threshold": args.change_threshold},
    )

    # ---- Connect ----
    con = load_db(args.db)

    # ---- Validate table ----
    try:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    except Exception:
        tables = []
    if args.table not in tables:
        con.close()
        print(
            f"[ERROR] Table '{args.table}' not found. Available: {tables}",
            file=sys.stderr,
        )
        write_output({"meta": meta, "error": "TABLE_NOT_FOUND"}, args.output)
        sys.exit(1)

    # ---- Fetch data ----
    df = _fetch_line_items(con, args.table, args.filter)
    table_types = _fetch_table_types(con)
    con.close()

    total_rows = len(df)
    meta["total_line_items"] = total_rows
    print(f"[ratio-analyzer] Fetched {total_rows} line items", file=sys.stderr)

    if total_rows == 0:
        write_output(
            {
                "meta": meta,
                "error": "NO_DATA",
                "account_matching": {},
                "ratios_by_period": {},
                "ratio_changes": [],
                "flagged_changes": [],
                "yoy_growth": {},
                "risk_score": 0,
                "investigation_suggestions": [
                    "No line items found. Check --filter or verify "
                    "normalization loaded data into the line_items table."
                ],
            },
            args.output,
        )
        sys.exit(0)

    # ---- Discover periods ----
    raw_periods = df["period_label"].dropna().unique().tolist()
    periods = _sort_periods(raw_periods)
    meta["periods_found"] = periods
    print(f"[ratio-analyzer] Periods (sorted): {periods}", file=sys.stderr)

    # ---- Fuzzy-match account names ----
    raw_names = df["account_name"].dropna().unique().tolist()
    account_matches = match_accounts(raw_names)

    matched_count = sum(1 for v in account_matches.values() if v is not None)
    meta["accounts_matched"] = matched_count
    meta["accounts_unmatched"] = len(raw_names) - matched_count
    print(
        f"[ratio-analyzer] Matched {matched_count}/{len(raw_names)} account names",
        file=sys.stderr,
    )

    # Build serialisable matching log
    account_matching_log: dict[str, Any] = {}
    for raw_name, match in account_matches.items():
        if match is not None:
            account_matching_log[raw_name] = {
                "category": match["category"],
                "best_alias": match["best_alias"],
                "score": match["score"],
            }
        else:
            account_matching_log[raw_name] = {
                "category": None,
                "best_alias": None,
                "score": 0,
                "status": "unmatched",
            }

    # ---- Build category amounts ----
    cat_amounts = _build_category_amounts(df, account_matches)

    categories_with_data = sorted(cat_amounts.keys())
    meta["categories_with_data"] = categories_with_data
    print(
        f"[ratio-analyzer] Categories with data: {categories_with_data}",
        file=sys.stderr,
    )

    # ---- Compute ratios per period ----
    ratios_by_period: dict[str, dict[str, float | None]] = {}
    for period in periods:
        ratios_by_period[period] = _compute_ratios_for_period(cat_amounts, period)

    # Round for output
    ratios_by_period_out: dict[str, dict[str, float | None]] = {}
    for period, ratios in ratios_by_period.items():
        ratios_by_period_out[period] = {
            k: round(v, 6) if v is not None else None for k, v in ratios.items()
        }

    # ---- Compute ratio changes and YoY growth ----
    ratio_changes: list[dict[str, Any]] = []
    yoy_growth: dict[str, dict[str, Any]] = {}
    flagged: list[dict[str, Any]] = []

    if len(periods) >= 2:
        prior_period = periods[-2]
        current_period = periods[-1]

        ratio_changes = _compute_ratio_changes(
            ratios_by_period, prior_period, current_period
        )
        yoy_growth = _compute_yoy_growth(cat_amounts, prior_period, current_period)
        flagged = _flag_changes(ratio_changes, yoy_growth, args.change_threshold)

    # ---- Risk score ----
    risk_score = _compute_risk_score(
        flagged, ratio_changes, yoy_growth, args.change_threshold
    )

    # ---- Suggestions ----
    suggestions = _generate_suggestions(
        flagged, yoy_growth, ratios_by_period, cat_amounts, periods
    )

    # ---- Assemble output ----
    output = {
        "meta": meta,
        "account_matching": account_matching_log,
        "ratios_by_period": ratios_by_period_out,
        "ratio_changes": ratio_changes,
        "flagged_changes": flagged,
        "yoy_growth": yoy_growth,
        "risk_score": risk_score,
        "investigation_suggestions": suggestions,
    }

    write_output(output, args.output)
    print(
        f"[ratio-analyzer] Risk score: {risk_score}/10, "
        f"{len(flagged)} flags, {len(suggestions)} suggestions",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
