# /// script
# dependencies = ["pandas", "duckdb", "scipy", "numpy"]
# ///
"""
Benford's Law Analysis for Forensic Accounting
================================================

Applies Benford's Law digit-frequency tests to numeric financial data stored
in DuckDB.  Designed for the two-pass forensic workflow:

  Pass 1 (Sweep):  Run all tests with defaults on the full dataset.
  Pass 2 (Investigate):  Re-run targeted tests with filters based on
                         Pass 1 findings.

Tests implemented:
  - first_digit   : Leading digit (1-9) distribution
  - second_digit  : Second digit (0-9) distribution
  - first_two     : Leading two digits (10-99) distribution
  - last_two      : Trailing two digits (00-99) distribution
  - summation     : Monetary-value-weighted first-two-digit distribution

All output is structured JSON written to --output.
Diagnostics and progress messages go to stderr.

Usage:
  uv run scripts/benfords.py --db case.duckdb --table transactions \\
      --column total_amount --tests all --output results.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


# ---------------------------------------------------------------------------
# Benford expected distributions
# ---------------------------------------------------------------------------

def benford_expected_first_digit() -> dict[str, float]:
    """P(d) = log10(1 + 1/d) for d in 1..9"""
    return {str(d): math.log10(1 + 1 / d) for d in range(1, 10)}


def benford_expected_second_digit() -> dict[str, float]:
    """P(d2) = sum over d1=1..9 of log10(1 + 1/(10*d1 + d2))"""
    probs: dict[str, float] = {}
    for d2 in range(0, 10):
        p = sum(math.log10(1 + 1 / (10 * d1 + d2)) for d1 in range(1, 10))
        probs[str(d2)] = p
    return probs


def benford_expected_first_two() -> dict[str, float]:
    """P(dd) = log10(1 + 1/dd) for dd in 10..99"""
    return {str(dd): math.log10(1 + 1 / dd) for dd in range(10, 100)}


def benford_expected_last_two() -> dict[str, float]:
    """Uniform distribution: P = 1/100 for each 00..99"""
    return {f"{dd:02d}": 1.0 / 100 for dd in range(0, 100)}


# ---------------------------------------------------------------------------
# Digit extraction helpers
# ---------------------------------------------------------------------------

def extract_first_digit(series: pd.Series) -> pd.Series:
    """Extract the leading digit (1-9) from absolute values."""
    s = series.abs()
    # Convert to string representation, strip leading zeros and decimal points
    digits = s.apply(_first_digit_of)
    return digits


def _first_digit_of(x: float) -> str | None:
    if x == 0 or not np.isfinite(x):
        return None
    s = f"{x:.15g}"
    for ch in s:
        if ch.isdigit() and ch != "0":
            return ch
    return None


def extract_second_digit(series: pd.Series) -> pd.Series:
    """Extract the second significant digit (0-9)."""
    s = series.abs()
    return s.apply(_second_digit_of)


def _second_digit_of(x: float) -> str | None:
    if x == 0 or not np.isfinite(x):
        return None
    s = f"{x:.15g}"
    significant = []
    started = False
    for ch in s:
        if ch == "." or ch == "-":
            continue
        if ch != "0":
            started = True
        if started and ch.isdigit():
            significant.append(ch)
        if len(significant) == 2:
            return significant[1]
    # Single-digit number: second digit is 0 conceptually, but we exclude
    return None


def extract_first_two_digits(series: pd.Series) -> pd.Series:
    """Extract the first two significant digits (10-99)."""
    s = series.abs()
    return s.apply(_first_two_digits_of)


def _first_two_digits_of(x: float) -> str | None:
    if x == 0 or not np.isfinite(x):
        return None
    s = f"{x:.15g}"
    significant = []
    started = False
    for ch in s:
        if ch == "." or ch == "-":
            continue
        if ch != "0":
            started = True
        if started and ch.isdigit():
            significant.append(ch)
        if len(significant) == 2:
            return "".join(significant)
    return None


def extract_last_two_digits(series: pd.Series) -> pd.Series:
    """Extract the last two digits of the integer part."""
    s = series.abs().apply(lambda x: int(round(x)) if np.isfinite(x) else None)
    return s.apply(lambda x: f"{x % 100:02d}" if x is not None and x >= 10 else None)


# ---------------------------------------------------------------------------
# Nigrini MAD conformity thresholds
# ---------------------------------------------------------------------------

MAD_THRESHOLDS = {
    "first_digit": [
        (0.006, "CLOSE_CONFORMITY"),
        (0.012, "ACCEPTABLE_CONFORMITY"),
        (0.015, "MARGINALLY_ACCEPTABLE"),
        (float("inf"), "NON_CONFORMING"),
    ],
    "second_digit": [
        (0.008, "CLOSE_CONFORMITY"),
        (0.010, "ACCEPTABLE_CONFORMITY"),
        (0.012, "MARGINALLY_ACCEPTABLE"),
        (float("inf"), "NON_CONFORMING"),
    ],
    "first_two": [
        (0.0012, "CLOSE_CONFORMITY"),
        (0.0018, "ACCEPTABLE_CONFORMITY"),
        (0.0022, "MARGINALLY_ACCEPTABLE"),
        (float("inf"), "NON_CONFORMING"),
    ],
    "last_two": [
        # Last-two uses uniform distribution; thresholds mirror first-two
        (0.0012, "CLOSE_CONFORMITY"),
        (0.0018, "ACCEPTABLE_CONFORMITY"),
        (0.0022, "MARGINALLY_ACCEPTABLE"),
        (float("inf"), "NON_CONFORMING"),
    ],
    "summation": [
        (0.0012, "CLOSE_CONFORMITY"),
        (0.0018, "ACCEPTABLE_CONFORMITY"),
        (0.0022, "MARGINALLY_ACCEPTABLE"),
        (float("inf"), "NON_CONFORMING"),
    ],
}


def classify_mad(mad_value: float, test_name: str) -> str:
    """Return the Nigrini conformity classification for a given MAD value."""
    thresholds = MAD_THRESHOLDS.get(test_name, MAD_THRESHOLDS["first_digit"])
    for threshold, label in thresholds:
        if mad_value < threshold:
            return label
    return "NON_CONFORMING"


# ---------------------------------------------------------------------------
# Core statistical tests
# ---------------------------------------------------------------------------

def compute_digit_test(
    values: pd.Series,
    extract_fn,
    expected_dist: dict[str, float],
    test_name: str,
    significance: float,
) -> dict[str, Any]:
    """
    Run a complete Benford's digit test.

    Returns a dict with observed, expected, chi-squared, KS, MAD, Z-scores,
    flagged digits, and verdict.
    """
    digits = extract_fn(values).dropna()
    n = len(digits)

    if n == 0:
        return _empty_test_result(test_name, "No valid digits extracted")

    # Observed counts and proportions
    counts = digits.value_counts()
    all_keys = sorted(expected_dist.keys(), key=lambda k: int(k))

    observed_counts = np.array([counts.get(k, 0) for k in all_keys], dtype=float)
    observed_props = observed_counts / n
    expected_props = np.array([expected_dist[k] for k in all_keys], dtype=float)
    expected_counts = expected_props * n

    # Build observed/expected dicts for output
    observed_dict = {k: round(float(observed_props[i]), 6) for i, k in enumerate(all_keys)}
    expected_dict = {k: round(float(expected_props[i]), 6) for i, k in enumerate(all_keys)}

    # --- Chi-squared test ---
    # Avoid zero expected counts (shouldn't happen for Benford, but guard)
    valid_mask = expected_counts > 0
    if valid_mask.sum() < 2:
        return _empty_test_result(test_name, "Insufficient non-zero expected frequencies")

    chi2, chi2_p = scipy_stats.chisquare(
        observed_counts[valid_mask], f_exp=expected_counts[valid_mask]
    )
    df = int(valid_mask.sum()) - 1
    chi2_critical = float(scipy_stats.chi2.ppf(1 - significance, df))

    # --- Kolmogorov-Smirnov test ---
    obs_cumul = np.cumsum(observed_props)
    exp_cumul = np.cumsum(expected_props)
    ks_stat = float(np.max(np.abs(obs_cumul - exp_cumul)))
    # Approximate KS p-value using the asymptotic distribution
    # The critical value for KS at alpha = 0.05 is ~1.36/sqrt(n)
    ks_critical = 1.36 / math.sqrt(n)
    ks_p = float(scipy_stats.kstwobign.sf(ks_stat * math.sqrt(n))) if n > 0 else 1.0

    # --- Mean Absolute Deviation ---
    mad = float(np.mean(np.abs(observed_props - expected_props)))
    mad_conformity = classify_mad(mad, test_name)

    # --- Z-scores per digit ---
    z_scores = {}
    flagged_digits = []
    for i, k in enumerate(all_keys):
        p_exp = expected_props[i]
        # Z = (|observed - expected| - 1/(2n)) / sqrt(p*(1-p)/n)
        # The -1/(2n) is Yates' continuity correction
        se = math.sqrt(p_exp * (1 - p_exp) / n) if n > 0 and p_exp > 0 and p_exp < 1 else 0
        if se > 0:
            z = (abs(observed_props[i] - p_exp) - 1 / (2 * n)) / se
            z = max(z, 0)  # continuity correction can make it negative
        else:
            z = 0.0
        z_scores[k] = round(z, 4)

        if z > 1.96:
            direction = "excess" if observed_props[i] > p_exp else "deficit"
            flagged_digits.append({
                "digit": k,
                "observed": round(float(observed_props[i]), 6),
                "expected": round(float(p_exp), 6),
                "z_score": round(z, 4),
                "direction": direction,
            })

    # --- Verdict ---
    verdict = _compute_test_verdict(mad_conformity, chi2_p, significance)

    return {
        "test_name": test_name,
        "n_digits_analyzed": int(n),
        "observed": observed_dict,
        "expected": expected_dict,
        "chi_squared": round(float(chi2), 4),
        "chi_squared_critical": round(chi2_critical, 4),
        "degrees_of_freedom": df,
        "p_value": round(float(chi2_p), 6),
        "ks_statistic": round(ks_stat, 6),
        "ks_p_value": round(ks_p, 6),
        "mad": round(mad, 6),
        "mad_conformity": mad_conformity,
        "z_scores": z_scores,
        "verdict": verdict,
        "flagged_digits": flagged_digits,
    }


def compute_summation_test(
    values: pd.Series,
    significance: float,
) -> dict[str, Any]:
    """
    Summation test: check if the monetary value is evenly distributed across
    first-two-digit groups.  Each group should carry approximately 1/90 of
    the total value (~1.11%).
    """
    test_name = "summation"
    abs_values = values.abs()

    # Extract first-two digits and pair with values
    ft_digits = extract_first_two_digits(abs_values)
    df = pd.DataFrame({"digit": ft_digits, "value": abs_values.values})
    df = df.dropna(subset=["digit"])

    n = len(df)
    if n == 0:
        return _empty_test_result(test_name, "No valid values for summation test")

    total_value = df["value"].sum()
    if total_value == 0:
        return _empty_test_result(test_name, "Total value is zero")

    all_keys = [str(dd) for dd in range(10, 100)]
    expected_prop = 1.0 / 90  # ~0.01111

    group_sums = df.groupby("digit")["value"].sum()
    observed_props = np.array(
        [group_sums.get(k, 0) / total_value for k in all_keys], dtype=float
    )
    expected_props = np.full(90, expected_prop, dtype=float)

    observed_dict = {k: round(float(observed_props[i]), 6) for i, k in enumerate(all_keys)}
    expected_dict = {k: round(float(expected_prop), 6) for i, k in enumerate(all_keys)}

    # Chi-squared on proportions scaled to counts
    # Use synthetic counts = proportion * n for the chi-squared
    # Normalize observed to match expected sum (floating-point rounding fix)
    observed_counts = observed_props * n
    expected_counts = expected_props * n
    obs_sum = observed_counts.sum()
    if obs_sum > 0:
        observed_counts = observed_counts * (expected_counts.sum() / obs_sum)

    valid_mask = expected_counts > 0
    if valid_mask.sum() < 2:
        return _empty_test_result(test_name, "Insufficient data for summation chi-squared")

    chi2, chi2_p = scipy_stats.chisquare(
        observed_counts[valid_mask], f_exp=expected_counts[valid_mask]
    )
    df_stat = int(valid_mask.sum()) - 1
    chi2_critical = float(scipy_stats.chi2.ppf(1 - significance, df_stat))

    # KS
    obs_cumul = np.cumsum(observed_props)
    exp_cumul = np.cumsum(expected_props)
    ks_stat = float(np.max(np.abs(obs_cumul - exp_cumul)))
    ks_p = float(scipy_stats.kstwobign.sf(ks_stat * math.sqrt(n))) if n > 0 else 1.0

    # MAD
    mad = float(np.mean(np.abs(observed_props - expected_props)))
    mad_conformity = classify_mad(mad, test_name)

    # Z-scores
    z_scores = {}
    flagged_digits = []
    for i, k in enumerate(all_keys):
        se = math.sqrt(expected_prop * (1 - expected_prop) / n) if n > 0 else 0
        if se > 0:
            z = (abs(observed_props[i] - expected_prop) - 1 / (2 * n)) / se
            z = max(z, 0)
        else:
            z = 0.0
        z_scores[k] = round(z, 4)

        if z > 1.96:
            direction = "excess" if observed_props[i] > expected_prop else "deficit"
            flagged_digits.append({
                "digit": k,
                "observed_value_share": round(float(observed_props[i]), 6),
                "expected_value_share": round(float(expected_prop), 6),
                "actual_sum": round(float(group_sums.get(k, 0)), 2),
                "z_score": round(z, 4),
                "direction": direction,
            })

    verdict = _compute_test_verdict(mad_conformity, chi2_p, significance)

    return {
        "test_name": test_name,
        "n_values_analyzed": int(n),
        "total_value": round(float(total_value), 2),
        "observed_value_shares": observed_dict,
        "expected_value_share": round(float(expected_prop), 6),
        "chi_squared": round(float(chi2), 4),
        "chi_squared_critical": round(chi2_critical, 4),
        "degrees_of_freedom": df_stat,
        "p_value": round(float(chi2_p), 6),
        "ks_statistic": round(ks_stat, 6),
        "ks_p_value": round(ks_p, 6),
        "mad": round(mad, 6),
        "mad_conformity": mad_conformity,
        "z_scores": z_scores,
        "verdict": verdict,
        "flagged_digits": flagged_digits,
    }


# ---------------------------------------------------------------------------
# Verdict and risk scoring
# ---------------------------------------------------------------------------

CONFORMITY_RANK = {
    "CLOSE_CONFORMITY": 0,
    "ACCEPTABLE_CONFORMITY": 1,
    "MARGINALLY_ACCEPTABLE": 2,
    "NON_CONFORMING": 3,
}

VERDICT_MAP = {
    "CLOSE_CONFORMITY": "CONFORMING",
    "ACCEPTABLE_CONFORMITY": "CONFORMING",
    "MARGINALLY_ACCEPTABLE": "MARGINALLY_NON_CONFORMING",
    "NON_CONFORMING": "NON_CONFORMING",
}


def _compute_test_verdict(mad_conformity: str, chi2_p: float, significance: float) -> str:
    """
    Determine per-test verdict.  MAD is primary; chi-squared confirms.
    If MAD says CONFORMING but chi-squared rejects, escalate to MARGINAL.
    """
    verdict = VERDICT_MAP.get(mad_conformity, "NON_CONFORMING")
    # If MAD is acceptable but chi-squared rejects, bump up
    if verdict == "CONFORMING" and chi2_p < significance:
        verdict = "MARGINALLY_NON_CONFORMING"
    return verdict


def compute_overall_verdict(test_results: dict[str, dict]) -> tuple[str, int]:
    """
    Compute overall verdict (worst across tests) and a 1-10 risk score.
    """
    verdict_rank = {
        "CONFORMING": 0,
        "MARGINALLY_NON_CONFORMING": 1,
        "NON_CONFORMING": 2,
        "ANOMALOUS": 3,
    }
    worst_verdict = "CONFORMING"
    worst_rank = 0
    non_conforming_count = 0
    total_tests = 0

    for result in test_results.values():
        if "error" in result:
            continue
        total_tests += 1
        v = result.get("verdict", "CONFORMING")
        r = verdict_rank.get(v, 0)
        if r > worst_rank:
            worst_rank = r
            worst_verdict = v
        if v in ("NON_CONFORMING", "ANOMALOUS"):
            non_conforming_count += 1

    # Promote to ANOMALOUS if multiple tests fail
    if non_conforming_count >= 2 and total_tests >= 3:
        worst_verdict = "ANOMALOUS"

    # Risk score 1-10
    risk_score = _compute_risk_score(test_results, worst_verdict, non_conforming_count, total_tests)

    return worst_verdict, risk_score


def _compute_risk_score(
    test_results: dict[str, dict],
    worst_verdict: str,
    non_conforming_count: int,
    total_tests: int,
) -> int:
    """
    Compute a 1-10 risk score based on:
    - Number of failing tests
    - Severity of MAD deviations
    - Number of flagged digits
    - Chi-squared p-values
    """
    score = 1.0

    # Base score from worst verdict
    verdict_base = {
        "CONFORMING": 1.0,
        "MARGINALLY_NON_CONFORMING": 4.0,
        "NON_CONFORMING": 6.0,
        "ANOMALOUS": 8.0,
    }
    score = verdict_base.get(worst_verdict, 1.0)

    # Adjust for number of failing tests
    if total_tests > 0:
        fail_ratio = non_conforming_count / total_tests
        score += fail_ratio * 2.0

    # Adjust for total flagged digits
    total_flagged = sum(
        len(r.get("flagged_digits", []))
        for r in test_results.values()
        if "error" not in r
    )
    if total_flagged > 5:
        score += 1.0
    if total_flagged > 10:
        score += 1.0

    # Adjust for extremely low p-values
    for r in test_results.values():
        if "error" in r:
            continue
        p = r.get("p_value", 1.0)
        if p < 0.001:
            score += 0.5

    return max(1, min(10, int(round(score))))


# ---------------------------------------------------------------------------
# Investigation suggestions (purely statistical, no LLM)
# ---------------------------------------------------------------------------

def generate_suggestions(
    test_results: dict[str, dict],
    total_records: int,
    min_records: int,
) -> list[str]:
    """Generate follow-up investigation suggestions based on test results."""
    suggestions: list[str] = []

    fd = test_results.get("first_digit", {})
    f2 = test_results.get("first_two", {})
    sd = test_results.get("second_digit", {})
    lt = test_results.get("last_two", {})
    sm = test_results.get("summation", {})

    # Borderline sample size warning
    if total_records < 200:
        suggestions.append(
            f"Sample size is borderline ({total_records} records). Statistical power is "
            f"reduced. Consider combining periods or data sources to increase sample size "
            f"before drawing firm conclusions. Type I error risk is elevated."
        )

    # First-digit passes but first-two fails
    if (
        fd.get("verdict") == "CONFORMING"
        and f2.get("verdict") in ("NON_CONFORMING", "MARGINALLY_NON_CONFORMING")
    ):
        flagged = f2.get("flagged_digits", [])
        if flagged:
            ranges = ", ".join(d["digit"] for d in flagged[:5])
            suggestions.append(
                f"First-digit test passes but first-two-digit test fails, with excess "
                f"in digit ranges: {ranges}. This suggests manipulation concentrated in "
                f"a specific amount range. Re-run with a filter on amounts starting with "
                f"these digit combinations to identify the transactions involved."
            )

    # First-digit fails -- always follow up with first-two
    if fd.get("verdict") in ("NON_CONFORMING", "MARGINALLY_NON_CONFORMING"):
        if "first_two" not in test_results:
            suggestions.append(
                "First-digit test shows non-conformity. Run the first-two-digit test "
                "to identify which specific digit ranges are driving the deviation."
            )

    # Last-two-digit round-number spike
    if lt and "error" not in lt:
        lt_flagged = lt.get("flagged_digits", [])
        round_digits = [d for d in lt_flagged if d["digit"] in ("00", "50") and d["direction"] == "excess"]
        if round_digits:
            pcts = ", ".join(f"'{d['digit']}' at {d['observed']*100:.1f}%" for d in round_digits)
            suggestions.append(
                f"Last-two-digit test flags round-number excess: {pcts} (expected ~1.0% each). "
                f"This may indicate fabricated round amounts. Cross-reference with round-number "
                f"analysis. Filter by journal type to check if these are manual entries."
            )
        # Check for "99" spike (just-below pricing)
        just_below = [d for d in lt_flagged if d["digit"] == "99" and d["direction"] == "excess"]
        if just_below:
            suggestions.append(
                "Last-two-digit excess at '99' may indicate just-below-threshold pricing "
                "or structuring (e.g., INR 49,999 to avoid INR 50,000 approval limit). "
                "Cross-reference with threshold analysis."
            )

    # Second-digit 0/5 excess
    if sd and "error" not in sd:
        sd_flagged = sd.get("flagged_digits", [])
        zero_five = [d for d in sd_flagged if d["digit"] in ("0", "5") and d["direction"] == "excess"]
        if zero_five:
            suggestions.append(
                "Second-digit excess at 0 and/or 5 suggests rounding or estimation. "
                "Natural transactions should not cluster on these second digits. "
                "Investigate whether these amounts originate from manual entries or estimates."
            )

    # Summation test concentration
    if sm and "error" not in sm:
        sm_flagged = sm.get("flagged_digits", [])
        high_value = [d for d in sm_flagged if d["direction"] == "excess"]
        if high_value:
            top3 = sorted(high_value, key=lambda d: d.get("z_score", 0), reverse=True)[:3]
            ranges = ", ".join(
                f"{d['digit']} ({d.get('observed_value_share', d.get('observed', 0))*100:.1f}% of total value)"
                for d in top3
            )
            suggestions.append(
                f"Summation test shows disproportionate value concentration in digit groups: "
                f"{ranges}. Even if digit frequencies look normal, these groups carry "
                f"excessive monetary weight. Investigate the specific large transactions "
                f"in these amount ranges."
            )

    return suggestions


def generate_flagged_ranges(test_results: dict[str, dict]) -> list[str]:
    """Generate human-readable flagged range descriptions."""
    ranges: list[str] = []
    for test_name, result in test_results.items():
        if "error" in result:
            continue
        for fd in result.get("flagged_digits", []):
            digit = fd["digit"]
            direction = fd.get("direction", "anomalous")
            z = fd.get("z_score", 0)
            if test_name == "first_digit":
                ranges.append(
                    f"First digit '{digit}' shows {direction} (Z={z:.2f}) -- "
                    f"amounts starting with {digit}xxx are {'over' if direction == 'excess' else 'under'}-represented"
                )
            elif test_name == "first_two":
                ranges.append(
                    f"First-two digits '{digit}' shows {direction} (Z={z:.2f}) -- "
                    f"amounts in the {digit}xx range are {'over' if direction == 'excess' else 'under'}-represented"
                )
            elif test_name == "second_digit":
                ranges.append(
                    f"Second digit '{digit}' shows {direction} (Z={z:.2f})"
                )
            elif test_name == "last_two":
                ranges.append(
                    f"Last-two digits '{digit}' shows {direction} (Z={z:.2f}) -- "
                    f"amounts ending in {digit} are {'over' if direction == 'excess' else 'under'}-represented"
                )
            elif test_name == "summation":
                share = fd.get("observed_value_share", fd.get("observed", 0))
                ranges.append(
                    f"Summation: digit group '{digit}' carries {share*100:.1f}% of total value "
                    f"(expected ~1.1%, Z={z:.2f})"
                )
    return ranges


# ---------------------------------------------------------------------------
# Error output helpers
# ---------------------------------------------------------------------------

def _empty_test_result(test_name: str, reason: str) -> dict[str, Any]:
    return {
        "test_name": test_name,
        "error": reason,
        "verdict": "CONFORMING",  # Cannot flag what we cannot test
        "flagged_digits": [],
    }


def write_error_output(
    output_path: str,
    error_type: str,
    error_message: str,
    meta: dict[str, Any],
) -> None:
    """Write a structured error JSON and exit with code 1."""
    result = {
        "meta": meta,
        "error": {
            "type": error_type,
            "message": error_message,
        },
        "tests": {},
        "overall_verdict": "ERROR",
        "overall_risk_score": 0,
        "flagged_ranges": [],
        "investigation_suggestions": [],
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2), file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benford's Law digit-frequency analysis for forensic accounting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pass 1 sweep on GL transactions
  uv run benfords.py --db case.duckdb --table transactions --column total_amount --tests all --output results.json

  # Pass 2 targeted re-run on vendor payments
  uv run benfords.py --db case.duckdb --table transactions --column total_amount \\
      --tests first_two,last_two --filter "journal_type = 'payment'" --output vendor_results.json
        """,
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database file")
    parser.add_argument("--table", default="transactions", help="Table name to analyze (default: transactions)")
    parser.add_argument("--column", default="amount", help="Numeric column to test (default: amount)")
    parser.add_argument(
        "--tests",
        default="all",
        help="Comma-separated tests: first_digit,second_digit,first_two,last_two,summation,all (default: all)",
    )
    parser.add_argument("--filter", default=None, help="SQL WHERE clause to filter data")
    parser.add_argument("--min-records", type=int, default=100, help="Minimum records required (default: 100)")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--significance", type=float, default=0.05, help="Significance level (default: 0.05)")
    parser.add_argument("--case-id", default=None, help="Case identifier for audit trail")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    timestamp = datetime.now(timezone.utc).isoformat()
    run_id = str(uuid.uuid4())

    meta: dict[str, Any] = {
        "case_id": args.case_id or "unspecified",
        "timestamp": timestamp,
        "run_id": run_id,
        "db_path": args.db,
        "table": args.table,
        "column": args.column,
        "filter_applied": args.filter,
        "significance_level": args.significance,
        "min_records_threshold": args.min_records,
        "total_records": 0,
        "records_analyzed": 0,
        "records_excluded": 0,
        "exclusion_reason": "",
    }

    # --- Validate DB path ---
    db_path = Path(args.db)
    if not db_path.exists():
        write_error_output(args.output, "FILE_NOT_FOUND", f"Database file not found: {args.db}", meta)

    # --- Connect and query ---
    print(f"[benfords] Connecting to {args.db}...", file=sys.stderr)
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as e:
        write_error_output(args.output, "DB_CONNECTION_ERROR", str(e), meta)

    # Validate table exists
    try:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    except Exception:
        tables = []
    if args.table not in tables:
        con.close()
        write_error_output(
            args.output,
            "TABLE_NOT_FOUND",
            f"Table '{args.table}' not found in database. Available tables: {tables}",
            meta,
        )

    # Validate column exists
    try:
        columns_info = con.execute(f"DESCRIBE {args.table}").fetchall()
        column_names = [row[0] for row in columns_info]
    except Exception as e:
        con.close()
        write_error_output(args.output, "DESCRIBE_ERROR", str(e), meta)

    if args.column not in column_names:
        con.close()
        write_error_output(
            args.output,
            "COLUMN_NOT_FOUND",
            f"Column '{args.column}' not found in table '{args.table}'. "
            f"Available columns: {column_names}",
            meta,
        )

    # Build query
    query = f"SELECT \"{args.column}\" FROM \"{args.table}\""
    if args.filter:
        query += f" WHERE {args.filter}"

    print(f"[benfords] Executing: {query}", file=sys.stderr)
    try:
        df = con.execute(query).df()
    except Exception as e:
        con.close()
        write_error_output(args.output, "QUERY_ERROR", f"Query failed: {e}", meta)

    con.close()

    total_records = len(df)
    meta["total_records"] = total_records
    print(f"[benfords] Retrieved {total_records} records", file=sys.stderr)

    # --- Data cleaning ---
    values = pd.to_numeric(df[args.column], errors="coerce")
    original_count = len(values)

    # Remove NaN, zero, negative, and infinite values
    valid_mask = values.notna() & values.gt(0) & np.isfinite(values)
    excluded_count = int((~valid_mask).sum())
    values = values[valid_mask].reset_index(drop=True)
    records_analyzed = len(values)

    meta["records_analyzed"] = records_analyzed
    meta["records_excluded"] = excluded_count
    if excluded_count > 0:
        meta["exclusion_reason"] = "zero, negative, NaN, or infinite values removed"

    # --- Check minimum records ---
    if records_analyzed < args.min_records:
        write_error_output(
            args.output,
            "INSUFFICIENT_RECORDS",
            f"Only {records_analyzed} valid records after cleaning (minimum: {args.min_records}). "
            f"Benford's Law requires a sufficient sample size for reliable results. "
            f"Total retrieved: {total_records}, excluded: {excluded_count}.",
            meta,
        )

    # --- Check for all identical values ---
    if values.nunique() <= 1:
        write_error_output(
            args.output,
            "NO_VARIANCE",
            f"All {records_analyzed} values are identical ({values.iloc[0] if len(values) > 0 else 'N/A'}). "
            f"Benford's Law analysis requires variance in the data.",
            meta,
        )

    # --- Determine which tests to run ---
    requested = args.tests.lower().strip()
    if requested == "all":
        test_list = ["first_digit", "second_digit", "first_two", "last_two", "summation"]
    else:
        test_list = [t.strip() for t in requested.split(",")]

    valid_tests = {"first_digit", "second_digit", "first_two", "last_two", "summation"}
    invalid = [t for t in test_list if t not in valid_tests]
    if invalid:
        print(f"[benfords] WARNING: Unknown tests ignored: {invalid}", file=sys.stderr)
        test_list = [t for t in test_list if t in valid_tests]

    if not test_list:
        write_error_output(args.output, "NO_VALID_TESTS", "No valid tests specified", meta)

    # --- Run tests ---
    print(f"[benfords] Running tests: {test_list}", file=sys.stderr)
    test_results: dict[str, dict] = {}

    for test_name in test_list:
        print(f"[benfords]   Running {test_name}...", file=sys.stderr)
        if test_name == "first_digit":
            test_results["first_digit"] = compute_digit_test(
                values, extract_first_digit, benford_expected_first_digit(),
                "first_digit", args.significance,
            )
        elif test_name == "second_digit":
            test_results["second_digit"] = compute_digit_test(
                values, extract_second_digit, benford_expected_second_digit(),
                "second_digit", args.significance,
            )
        elif test_name == "first_two":
            test_results["first_two"] = compute_digit_test(
                values, extract_first_two_digits, benford_expected_first_two(),
                "first_two", args.significance,
            )
        elif test_name == "last_two":
            test_results["last_two"] = compute_digit_test(
                values, extract_last_two_digits, benford_expected_last_two(),
                "last_two", args.significance,
            )
        elif test_name == "summation":
            test_results["summation"] = compute_summation_test(values, args.significance)

    # --- Compute overall verdict and risk score ---
    overall_verdict, risk_score = compute_overall_verdict(test_results)
    flagged_ranges = generate_flagged_ranges(test_results)
    suggestions = generate_suggestions(test_results, records_analyzed, args.min_records)

    # --- Assemble output ---
    output = {
        "meta": meta,
        "tests": test_results,
        "overall_verdict": overall_verdict,
        "overall_risk_score": risk_score,
        "flagged_ranges": flagged_ranges,
        "investigation_suggestions": suggestions,
    }

    # --- Write output ---
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[benfords] Overall verdict: {overall_verdict} (risk score: {risk_score}/10)", file=sys.stderr)
    print(f"[benfords] Results written to {args.output}", file=sys.stderr)
    if flagged_ranges:
        print(f"[benfords] Flagged ranges: {len(flagged_ranges)}", file=sys.stderr)
    if suggestions:
        print(f"[benfords] Investigation suggestions: {len(suggestions)}", file=sys.stderr)


if __name__ == "__main__":
    main()
