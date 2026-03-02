# /// script
# dependencies = ["pandas", "duckdb", "numpy"]
# ///
"""Unsupervised Anomaly Detection for Forensic Accounting.

Three methods: IQR fence, Z-score (both per table_type), Isolation Forest (PyOD).
Consensus = flagged by >=2 methods (or both when PyOD absent).
No LLM -- pure deterministic.  Output is structured JSON.
"""
from __future__ import annotations

import argparse, sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.forensic_utils import load_db, build_meta, write_output  # noqa: E402

_HAS_PYOD = False
try:
    from pyod.models.iforest import IForest  # type: ignore[import-untyped]
    _HAS_PYOD = True
except ImportError:
    IForest = None  # type: ignore[assignment,misc]

_MIN_IF = 10   # min rows for IForest
_MIN_ST = 3    # min rows for IQR / Z-score per group

# ── IQR (per table_type) ─────────────────────────────────────────────────
def _run_iqr(df: pd.DataFrame, col: str) -> pd.Series:
    flagged = pd.Series(False, index=df.index)
    for _, grp in df.groupby("table_type", sort=False):
        v = grp[col].dropna()
        if len(v) < _MIN_ST:
            continue
        q1, q3 = v.quantile(0.25), v.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        mask = (grp[col] < q1 - 1.5 * iqr) | (grp[col] > q3 + 1.5 * iqr)
        flagged.loc[mask[mask].index] = True
    return flagged

# ── Z-score (per table_type) ─────────────────────────────────────────────
def _run_zscore(df: pd.DataFrame, col: str, threshold: float = 3.0) -> pd.Series:
    flagged = pd.Series(False, index=df.index)
    for _, grp in df.groupby("table_type", sort=False):
        v = grp[col].dropna()
        if len(v) < _MIN_ST:
            continue
        mu, sigma = v.mean(), v.std(ddof=1)
        if sigma == 0 or np.isnan(sigma):
            continue
        mask = ((grp[col] - mu) / sigma).abs() > threshold
        flagged.loc[mask[mask].index] = True
    return flagged

# ── Isolation Forest (PyOD, full dataset) ─────────────────────────────────
def _run_iforest(df: pd.DataFrame, col: str, contamination: float
                 ) -> tuple[pd.Series, pd.Series]:
    flagged = pd.Series(False, index=df.index)
    scores = pd.Series(np.nan, index=df.index)
    if not _HAS_PYOD:
        return flagged, scores
    valid = df[col].notna()
    vdf = df.loc[valid]
    if len(vdf) < _MIN_IF:
        return flagged, scores
    amt = vdf[col].values.astype(float)
    X = np.column_stack([
        amt, np.log10(np.abs(amt) + 1.0),
        (amt < 0).astype(float),
        vdf["source_row"].fillna(0).values.astype(float),
    ])
    if np.all(X == X[0, :], axis=0).all():
        return flagged, scores
    c = max(1.0 / len(X), min(contamination, 0.5))
    model = IForest(contamination=c, random_state=42, n_estimators=100)
    model.fit(X)
    flagged.loc[vdf.index] = model.labels_.astype(bool)
    scores.loc[vdf.index] = model.decision_scores_
    return flagged, scores

# ── Consensus ─────────────────────────────────────────────────────────────
def _consensus(iqr: pd.Series, zs: pd.Series, ifs: pd.Series, has_pyod: bool) -> pd.Series:
    if has_pyod:
        return (iqr.astype(int) + zs.astype(int) + ifs.astype(int)) >= 2
    return iqr & zs

# ── Risk score 1-10 ──────────────────────────────────────────────────────
def _risk_score(total: int, n_con: int, max_if_score: float,
                tt_counts: dict[str, int]) -> int:
    if total == 0:
        return 1
    s = 1.0
    pct = n_con / total
    s += 4.0 if pct > 0.20 else 3.0 if pct > 0.10 else 2.0 if pct > 0.05 else 1.0 if pct > 0.02 else 0.0
    if not np.isnan(max_if_score):
        s += 3.0 if max_if_score > 0.8 else 2.0 if max_if_score > 0.5 else 1.0 if max_if_score > 0.3 else 0.0
    nz = [v for v in tt_counts.values() if v > 0]
    if len(nz) == 1 and n_con > 0:
        s += 2.0
    elif len(nz) > 1 and n_con > 3:
        s += 1.0
    return max(1, min(10, int(round(s))))

# ── Per-item anomaly records ─────────────────────────────────────────────
def _safe_round(val: Any, d: int = 4) -> float | None:
    if val is None:
        return None
    try:
        if np.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(val), d)

def _build_records(df: pd.DataFrame, col: str, iqr_m: pd.Series,
                   z_m: pd.Series, if_m: pd.Series, if_scores: pd.Series,
                   has_pyod: bool) -> list[dict[str, Any]]:
    any_flag = iqr_m | z_m | if_m
    recs: list[dict[str, Any]] = []
    for idx in df.index[any_flag]:
        row = df.loc[idx]
        methods = (["iqr"] if iqr_m.at[idx] else []) + \
                  (["zscore"] if z_m.at[idx] else []) + \
                  (["iforest"] if if_m.at[idx] else [])
        n = len(methods)
        sv = if_scores.at[idx]
        recs.append({
            "line_item_id": row["line_item_id"],
            "account_name": row["account_name"],
            "amount": _safe_round(row[col]),
            "table_type": row["table_type"],
            "period_label": row.get("period_label"),
            "anomaly_score": round(float(sv), 6) if not np.isnan(sv) else None,
            "methods_flagged": methods,
            "n_methods": n,
            "is_consensus_anomaly": n >= 2,
        })
    recs.sort(key=lambda r: (-int(r["is_consensus_anomaly"]), -r["n_methods"],
                              -(r["anomaly_score"] or 0)))
    return recs

# ── Investigation suggestions ─────────────────────────────────────────────
def _suggestions(df: pd.DataFrame, col: str, con_mask: pd.Series,
                 iqr_m: pd.Series, z_m: pd.Series, if_m: pd.Series,
                 has_pyod: bool) -> list[str]:
    sug: list[str] = []
    anom = df.loc[con_mask]
    if anom.empty:
        sug.append("No consensus anomalies detected. Consider Benford's Law analysis for complementary coverage.")
        return sug
    # sign mix
    pos, neg = int((anom[col] > 0).sum()), int((anom[col] < 0).sum())
    if neg > 0 and pos > 0:
        sug.append(f"Anomalies include {pos} positive and {neg} negative amounts. "
                   f"Investigate negatives for reversals or contra-entries masking fraud.")
    elif neg > 0:
        sug.append(f"All {neg} anomalies are negative. Review for suspicious credit adjustments.")
    # table_type concentration
    tc = anom["table_type"].value_counts()
    if len(tc) == 1:
        sug.append(f"All consensus anomalies in table_type='{tc.index[0]}'. Run targeted analysis on this subset.")
    elif len(tc) > 1 and tc.iloc[0] / len(anom) > 0.70:
        sug.append(f"{tc.iloc[0]/len(anom)*100:.0f}% of anomalies from table_type='{tc.index[0]}'. "
                   f"Investigate concentration for data quality vs. genuine unusual activity.")
    # large outlier
    med = df[col].abs().median()
    if med > 0 and len(anom) > 0:
        ix = anom[col].abs().idxmax()
        ratio = anom[col].abs().max() / med
        if ratio > 100:
            r = anom.loc[ix]
            sug.append(f"Largest anomaly ('{r['account_name']}', {r[col]:,.2f}) is {ratio:,.0f}x median. "
                       f"Verify it is not a data entry error or material misstatement.")
    # method disagreement
    if (iqr_m & ~z_m).sum() > 5 and (z_m & ~iqr_m).sum() < 2:
        sug.append("IQR flags many items Z-score misses -- heavy-tailed distribution. "
                   "Consider log-transforming amounts for re-analysis.")
    if has_pyod:
        ifo = int((if_m & ~iqr_m & ~z_m).sum())
        if ifo > 0:
            sug.append(f"IForest flagged {ifo} item(s) missed by IQR/Z-score -- possible "
                       f"multivariate anomalies. Review individually.")
    else:
        sug.append("PyOD not installed -- IForest skipped. pip install pyod for multivariate detection.")
    sug.append("Cross-reference with Benford's and duplicate detection to triangulate suspicious entries.")
    return sug

# ── Summary & method results ─────────────────────────────────────────────
def _build_summary(total: int, ic: int, zc: int, fc: int, cc: int,
                   hp: bool, tb: dict) -> dict[str, Any]:
    mc: dict[str, int] = {"iqr": ic, "zscore": zc}
    if hp:
        mc["iforest"] = fc
    return {"total_items_analyzed": total, "methods_used": list(mc.keys()),
            "anomalies_per_method": mc, "consensus_anomalies": cc,
            "consensus_threshold": ">=2 of 3 methods" if hp else "both methods agree",
            "breakdown_by_table_type": tb}

def _method_results(ic: int, zc: int, fc: int, cont: float,
                    if_scores: pd.Series, hp: bool) -> dict[str, Any]:
    mr: dict[str, Any] = {
        "iqr": {"description": "IQR fence (Q1-1.5*IQR, Q3+1.5*IQR), per table_type", "flagged_count": ic},
        "zscore": {"description": "Z-score > 3 SD from mean, per table_type", "flagged_count": zc},
    }
    if hp:
        vs = if_scores.dropna()
        mr["iforest"] = {"description": "Isolation Forest (PyOD)", "contamination": cont,
                         "flagged_count": fc,
                         "score_min": _safe_round(vs.min()) if len(vs) else None,
                         "score_max": _safe_round(vs.max()) if len(vs) else None,
                         "score_mean": _safe_round(vs.mean()) if len(vs) else None}
    else:
        mr["iforest"] = {"description": "IForest SKIPPED (pyod not installed)", "flagged_count": 0}
    return mr

# ── Error helper ──────────────────────────────────────────────────────────
def _die(out: str, meta: dict, etype: str, msg: str) -> None:
    write_output({"meta": meta, "error": {"type": etype, "message": msg},
                  "method_results": {}, "anomalies": [], "summary": {},
                  "risk_score": 0, "investigation_suggestions": []}, out)
    print(f"[anomaly-detector] ERROR ({etype}): {msg}", file=sys.stderr)
    sys.exit(1)

# ── CLI ───────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unsupervised anomaly detection on forensic line-item amounts")
    p.add_argument("--db", required=True, help="Path to DuckDB database")
    p.add_argument("--output", required=True, help="Output JSON path")
    p.add_argument("--table", default="line_items")
    p.add_argument("--column", default="amount")
    p.add_argument("--filter", default=None, help="SQL WHERE clause")
    p.add_argument("--contamination", type=float, default=0.05, help="IForest contamination (default 0.05)")
    p.add_argument("--case-id", default=None)
    return p.parse_args()

# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()
    meta = build_meta(skill_name="anomaly-detector", db_path=args.db, table=args.table,
                      column=args.column, filter_sql=args.filter, case_id=args.case_id,
                      extra={"contamination": args.contamination, "pyod_available": _HAS_PYOD})

    con = load_db(args.db)

    # validate tables
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()] if True else []
    if args.table not in tables:
        con.close(); _die(args.output, meta, "TABLE_NOT_FOUND", f"'{args.table}' not found. Available: {tables}")
    if "source_tables" not in tables:
        con.close(); _die(args.output, meta, "TABLE_NOT_FOUND", "'source_tables' not found in database.")

    # validate column
    cols = [r[0] for r in con.execute(f'DESCRIBE "{args.table}"').fetchall()]
    if args.column not in cols:
        con.close(); _die(args.output, meta, "COLUMN_NOT_FOUND", f"'{args.column}' not in '{args.table}'. Available: {cols}")

    # query with join
    q = (f'SELECT li.line_item_id, li.account_name, li."{args.column}" AS value, '
         f"COALESCE(st.table_type,'unknown') AS table_type, li.period_label, li.source_row "
         f'FROM "{args.table}" li LEFT JOIN source_tables st ON li.table_id=st.table_id')
    if args.filter:
        q += f" WHERE {args.filter}"
    print(f"[anomaly-detector] {q}", file=sys.stderr)

    try:
        df = con.execute(q).df()
    except Exception as exc:
        con.close(); _die(args.output, meta, "QUERY_ERROR", str(exc))
    con.close()

    raw = len(df)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).reset_index(drop=True)
    total = len(df)
    meta["total_items_queried"] = raw
    meta["total_items_analyzed"] = total
    print(f"[anomaly-detector] {raw} rows queried, {total} after cleaning", file=sys.stderr)

    if total == 0:
        _die(args.output, meta, "NO_DATA", "No non-null numeric values after cleaning.")
    if df["value"].nunique() <= 1:
        _die(args.output, meta, "NO_VARIANCE",
             f"All {total} values identical ({df['value'].iloc[0]}). Need variance.")

    col = "value"

    # run methods
    iqr_m = _run_iqr(df, col);       ic = int(iqr_m.sum())
    z_m = _run_zscore(df, col);      zc = int(z_m.sum())
    if_m, if_s = _run_iforest(df, col, args.contamination); fc = int(if_m.sum())
    con_m = _consensus(iqr_m, z_m, if_m, _HAS_PYOD); cc = int(con_m.sum())

    for lbl, cnt in [("IQR", ic), ("Z-score", zc), ("IForest", fc if _HAS_PYOD else "skipped"), ("Consensus", cc)]:
        print(f"[anomaly-detector]   {lbl}: {cnt}", file=sys.stderr)

    # output records
    df_out = df.rename(columns={"value": "amount"})
    recs = _build_records(df_out, "amount", iqr_m, z_m, if_m, if_s, _HAS_PYOD)

    # breakdown by table_type
    tb: dict[str, dict[str, int]] = {}
    for tt in df["table_type"].unique():
        tm = df["table_type"] == tt
        entry = {"total": int(tm.sum()), "iqr": int((iqr_m & tm).sum()),
                 "zscore": int((z_m & tm).sum()), "consensus": int((con_m & tm).sum())}
        if _HAS_PYOD:
            entry["iforest"] = int((if_m & tm).sum())
        tb[str(tt)] = entry

    max_sc = float(if_s.max()) if _HAS_PYOD and len(if_s.dropna()) > 0 else float("nan")
    tt_cc = {tt: int((con_m & (df["table_type"] == tt)).sum()) for tt in df["table_type"].unique()}
    rs = _risk_score(total, cc, max_sc, tt_cc)
    sugs = _suggestions(df_out, "amount", con_m, iqr_m, z_m, if_m, _HAS_PYOD)

    result = {
        "meta": meta,
        "method_results": _method_results(ic, zc, fc, args.contamination, if_s, _HAS_PYOD),
        "anomalies": recs,
        "summary": _build_summary(total, ic, zc, fc, cc, _HAS_PYOD, tb),
        "risk_score": rs,
        "investigation_suggestions": sugs,
    }
    write_output(result, args.output)
    print(f"[anomaly-detector] Done. Risk {rs}/10 | Consensus {cc}/{total}", file=sys.stderr)

if __name__ == "__main__":
    main()
