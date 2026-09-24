"""
Test script for the DataNormalizer pipeline.

Extracts tables from test documents, classifies them, normalizes amounts,
loads them into DuckDB, and runs validation queries.

Run with:
    python -m pipeline.test_normalization                          # full extract + normalize (docling)
    python -m pipeline.test_normalization --from-cache             # skip extraction, use cached tables
    python -m pipeline.test_normalization --extractor mistral      # extract via Mistral OCR
    python -m pipeline.test_normalization --extractor mistral --from-cache  # use Mistral cache
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_USER_DOCS = _PROJECT_ROOT / "user_documents"
_TEST_OUTPUT = Path(__file__).resolve().parent / "test_output"

# Extractor-specific paths (set in main() based on --extractor flag)
_TEST_DB = _TEST_OUTPUT / "test_forensic.duckdb"
_TABLE_CACHE = _TEST_OUTPUT / "extracted_tables.pkl"

_TEST_FILES = [
   # _USER_DOCS / "sample_docs/sample_statement.xlsx",
    _USER_DOCS / "sample_docs/sample_statement.pdf"
]

# ---------------------------------------------------------------------------
# Ensure dotenv loaded
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass


def _ensure_output_dir():
    _TEST_OUTPUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# ExtractedTable compatibility shim
# ---------------------------------------------------------------------------
# Try importing from pipeline.table_extractor first.
# If it doesn't exist, use the shim from data_normalizer.

try:
    from pipeline.table_extractor import TableExtractor, ExtractedTable
    _HAS_TABLE_EXTRACTOR = True
except ImportError:
    _HAS_TABLE_EXTRACTOR = False
    from pipeline.data_normalizer import ExtractedTable


# ---------------------------------------------------------------------------
# Fallback extraction when TableExtractor is not available
# ---------------------------------------------------------------------------

def _extract_excel_tables(file_path: Path) -> list[ExtractedTable]:
    """Extract tables from an Excel workbook using openpyxl/pandas."""
    tables: list[ExtractedTable] = []
    try:
        xl = pd.ExcelFile(file_path)
    except Exception as exc:
        print(f"  [WARN] Cannot open Excel file {file_path}: {exc}")
        return tables

    for idx, sheet_name in enumerate(xl.sheet_names):
        try:
            df = xl.parse(sheet_name, header=0)
        except Exception as exc:
            print(f"  [WARN] Cannot parse sheet '{sheet_name}': {exc}")
            continue

        if df.empty:
            continue

        # Drop fully-empty rows/cols
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            continue

        # Clean column names
        df.columns = [
            str(c).strip() if pd.notna(c) else f"Column_{i}"
            for i, c in enumerate(df.columns)
        ]

        # Build surrounding text from header-area for unit detection
        surrounding = f"Sheet: {sheet_name}, File: {file_path.name}"
        # Look for unit clue in sheet name or first few cell values
        for val in df.iloc[:3].values.flatten():
            if isinstance(val, str) and any(
                k in val.lower() for k in ("lakh", "crore", "thousand", "million")
            ):
                surrounding += f" | {val}"

        tbl = ExtractedTable(
            df=df,
            source_file=str(file_path),
            source_file_type=file_path.suffix.lower().lstrip("."),
            sheet_name=sheet_name,
            table_index=idx,
            page_number=None,
            section_heading=sheet_name,
            surrounding_text=surrounding,
            extraction_method="pandas_excel",
            extraction_confidence=0.85,
        )
        tables.append(tbl)

    return tables


def _extract_pdf_tables(file_path: Path) -> list[ExtractedTable]:
    """Extract tables from a PDF using available libraries."""
    tables: list[ExtractedTable] = []

    # Try tabula-py first
    try:
        import tabula
        dfs = tabula.read_pdf(str(file_path), pages="all", multiple_tables=True)
        for idx, df in enumerate(dfs):
            if df.empty:
                continue
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue
            df.columns = [
                str(c).strip() if pd.notna(c) else f"Column_{i}"
                for i, c in enumerate(df.columns)
            ]
            tbl = ExtractedTable(
                df=df,
                source_file=str(file_path),
                source_file_type=file_path.suffix.lower().lstrip("."),
                sheet_name="",
                table_index=idx,
                page_number=None,
                section_heading="",
                surrounding_text=f"File: {file_path.name}",
                extraction_method="tabula",
                extraction_confidence=0.75,
            )
            tables.append(tbl)
        if tables:
            return tables
    except ImportError:
        pass
    except Exception as exc:
        print(f"  [WARN] tabula extraction failed: {exc}")

    # Try camelot
    try:
        import camelot
        camelot_tables = camelot.read_pdf(str(file_path), pages="all")
        for idx, ct in enumerate(camelot_tables):
            df = ct.df
            if df.empty:
                continue
            # Use first row as header
            df.columns = [str(c).strip() for c in df.iloc[0]]
            df = df[1:]
            df = df.dropna(how="all")
            if df.empty:
                continue
            tbl = ExtractedTable(
                df=df,
                source_file=str(file_path),
                source_file_type=file_path.suffix.lower().lstrip("."),
                sheet_name="",
                table_index=idx,
                page_number=ct.page if hasattr(ct, "page") else None,
                section_heading="",
                surrounding_text=f"File: {file_path.name}",
                extraction_method="camelot",
                extraction_confidence=0.70,
            )
            tables.append(tbl)
        if tables:
            return tables
    except ImportError:
        pass
    except Exception as exc:
        print(f"  [WARN] camelot extraction failed: {exc}")

    # Minimal fallback: read text and try to parse
    print(f"  [INFO] No PDF table extractor available for {file_path.name}; creating stub table")
    # Create a minimal stub so the normalizer can still be tested
    stub_df = pd.DataFrame({
        "Particulars": [
            "Revenue from Operations",
            "Other Income",
            "Total Income",
            "Cost of Materials Consumed",
            "Employee Benefits Expense",
            "Depreciation and Amortisation Expense",
            "Other Expenses",
            "Total Expenses",
            "Profit Before Tax",
            "Tax Expense",
            "Profit After Tax",
        ],
        "FY 2023-24": [
            1250.00, 45.50, 1295.50, 610.25, 180.40,
            62.15, 215.70, 1068.50, 227.00, 57.15, 169.85,
        ],
        "FY 2022-23": [
            1120.00, 38.20, 1158.20, 548.90, 165.30,
            58.40, 198.60, 971.20, 187.00, 47.10, 139.90,
        ],
    })
    tbl = ExtractedTable(
        df=stub_df,
        source_file=str(file_path),
        source_file_type=file_path.suffix.lower().lstrip("."),
        sheet_name="",
        table_index=0,
        page_number=1,
        section_heading="Statement of Profit and Loss (₹ in Crores)",
        surrounding_text=(
            "sample_docs/sample_statement.pdf | "
            "Statement of Profit and Loss for the year ended March 31, 2024 | "
            "All amounts in Crores"
        ),
        extraction_method="stub_fallback",
        extraction_confidence=0.50,
    )
    tables.append(tbl)
    return tables


def extract_tables(file_path: Path) -> list[ExtractedTable]:
    """Extract tables from a file using the best available method."""
    if _HAS_TABLE_EXTRACTOR:
        try:
            extractor = TableExtractor()
            return extractor.extract_all(str(file_path))
        except Exception as exc:
            print(f"  [WARN] TableExtractor failed: {exc}; falling back")

    ext = file_path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return _extract_excel_tables(file_path)
    elif ext == ".pdf":
        return _extract_pdf_tables(file_path)
    elif ext == ".csv":
        try:
            df = pd.read_csv(file_path)
            return [
                ExtractedTable(
                    df=df,
                    source_file=str(file_path),
                    source_file_type=file_path.suffix.lower().lstrip("."),
                    extraction_method="pandas_csv",
                    extraction_confidence=0.90,
                )
            ]
        except Exception as exc:
            print(f"  [WARN] CSV read failed: {exc}")
            return []
    else:
        print(f"  [WARN] Unsupported file type: {ext}")
        return []


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Data Normalizer integration test")
    parser.add_argument(
        "--from-cache", action="store_true",
        help="Skip extraction, load tables from pickle cache",
    )
    parser.add_argument(
        "--extractor", choices=["docling", "mistral"], default="docling",
        help="Which extraction backend to use (default: docling)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Only process the first N pages (Mistral extractor only)",
    )
    parser.add_argument(
        "--files", nargs="+", default=None,
        help="Only process files whose names contain these substrings (e.g. --files sample_statement)",
    )
    parser.add_argument(
        "--run-skills", action="store_true",
        help="After normalization, run all available forensic skills with default params",
    )
    return parser.parse_args()


def _extract_with_mistral(
    file_paths: list[Path],
    *,
    max_pages: int | None = None,
) -> list[ExtractedTable]:
    """Extract tables from PDF files using the Mistral OCR backend."""
    from pipeline.mistral_extractor import MistralTableExtractor

    extractor = MistralTableExtractor()
    all_tables: list[ExtractedTable] = []
    for fpath in file_paths:
        if not fpath.exists():
            print(f"  [SKIP] File not found: {fpath}")
            continue
        ext = fpath.suffix.lower()
        if ext == ".pdf":
            print(f"\n--- Extracting (Mistral OCR): {fpath.name} ---")
            tables = extractor.extract(fpath, max_pages=max_pages)
            print(f"  Extracted {len(tables)} table(s)")
            for t in tables:
                unit = t.metadata.get("source_unit", "?")
                print(
                    f"    Page: {t.page_number}, "
                    f"Rows: {len(t.df)}, Cols: {len(t.df.columns)}, "
                    f"Unit: {unit}, "
                    f"Heading: {(t.section_heading or '(none)')[:60]}"
                )
            all_tables.extend(tables)
        else:
            # Non-PDF files fall back to the default extractor
            print(f"\n--- Extracting (fallback): {fpath.name} ---")
            tables = extract_tables(fpath)
            print(f"  Extracted {len(tables)} table(s)")
            all_tables.extend(tables)
    return all_tables


def main():
    args = _parse_args()
    use_cache = args.from_cache
    extractor_name = args.extractor

    # Set extractor-specific DB and cache paths
    if extractor_name == "mistral":
        test_db = _TEST_OUTPUT / "test_forensic_mistral.duckdb"
        table_cache = _TEST_OUTPUT / "extracted_tables_mistral.pkl"
    else:
        test_db = _TEST_DB
        table_cache = _TABLE_CACHE

    print("=" * 70)
    print("DATA NORMALIZER — Integration Test")
    print(f"  Extractor: {extractor_name}")
    print(f"  Mode: {'from cache' if use_cache else 'full extraction'}")
    print("=" * 70)

    _ensure_output_dir()
    # Remove stale extractor-specific DB
    if test_db.exists():
        test_db.unlink()

    # ---- Step 1: Extract tables (or load from cache) ----
    all_tables: list[ExtractedTable] = []

    if use_cache and table_cache.exists():
        print(f"\n--- Loading cached tables from {table_cache.name} ---")
        with open(table_cache, "rb") as f:
            all_tables = pickle.load(f)
        print(f"  Loaded {len(all_tables)} table(s) from cache")
        for t in all_tables:
            print(f"    Source: {Path(t.source_file).name}, "
                  f"Sheet: {t.sheet_name or '(none)'}, "
                  f"Rows: {len(t.df)}, Cols: {len(t.df.columns)}")
    else:
        if use_cache:
            print(f"\n  [WARN] Cache not found at {table_cache}, falling back to extraction")

        if extractor_name == "mistral":
            all_tables = _extract_with_mistral(
                _TEST_FILES, max_pages=args.max_pages,
            )
        else:
            for fpath in _TEST_FILES:
                print(f"\n--- Extracting from: {fpath.name} ---")
                if not fpath.exists():
                    print(f"  [SKIP] File not found: {fpath}")
                    continue
                tables = extract_tables(fpath)
                print(f"  Extracted {len(tables)} table(s)")
                for t in tables:
                    print(f"    Sheet: {t.sheet_name or '(none)'}, "
                          f"Rows: {len(t.df)}, Cols: {len(t.df.columns)}, "
                          f"Heading: {t.section_heading[:60] if t.section_heading else '(none)'}")
                all_tables.extend(tables)

        # Cache for next time
        with open(table_cache, "wb") as f:
            pickle.dump(all_tables, f)
        print(f"\n  [INFO] Cached {len(all_tables)} tables to {table_cache.name}")

    if not all_tables:
        print("\n[ERROR] No tables extracted. Cannot proceed.")
        sys.exit(1)

    print(f"\nTotal tables: {len(all_tables)}")

    # ---- Step 2: Initialize normalizer ----
    from pipeline.data_normalizer import DataNormalizer

    normalizer = DataNormalizer(db_path=str(test_db))
    print(f"\nDuckDB path: {test_db}")

    try:
        normalizer.initialize_schema()
        print("[OK] Schema initialized")
    except Exception as exc:
        print(f"[ERROR] Schema init failed: {exc}")
        sys.exit(1)

    # ---- Step 3: Normalize and load ----
    print("\n--- Running normalization ---")
    result = normalizer.normalize_and_load(
        all_tables,
        entity_name="EXCO",
        fiscal_year="2023-24",
    )

    print(f"\n{'=' * 50}")
    print("NORMALIZATION RESULT")
    print(f"{'=' * 50}")
    print(f"  Source tables loaded: {result.source_tables_loaded}")
    print(f"  Tables classified:   {result.tables_classified}")
    print(f"  Line items loaded:   {result.line_items_loaded}")
    print(f"  Related parties:     {result.related_parties_loaded}")
    print(f"  Warnings:            {len(result.warnings)}")
    print(f"  Errors:              {len(result.errors)}")

    if result.errors:
        print("\n--- ERRORS ---")
        for err in result.errors:
            print(f"  [ERROR] {err}")

    if result.warnings:
        print(f"\n--- WARNINGS (first 20 of {len(result.warnings)}) ---")
        for w in result.warnings[:20]:
            print(f"  [WARN] {w}")

    print("\n--- CLASSIFICATION RESULTS ---")
    for cls in result.classification_results:
        c = cls["classification"]
        print(f"  File: {Path(cls['source_file']).name}")
        print(f"    Sheet:   {cls['sheet_name'] or '(none)'}")
        print(f"    Type:    {c.get('table_type', '?')}")
        print(f"    Unit:    {c.get('reporting_unit', '?')}")
        print(f"    Period:  {c.get('reporting_period', '?')}")
        col_map = c.get("column_mapping", {})
        if col_map:
            print(f"    Columns: {json.dumps(col_map, indent=None)}")
        print()

    print("--- VALIDATION RESULTS ---")
    for v in result.validation_results:
        status = v.get("status", "?")
        marker = {"pass": "PASS", "fail": "FAIL", "warning": "WARN", "info": "INFO"}.get(
            status, status.upper()
        )
        print(f"  [{marker}] {v['check']}: {v.get('detail', '')}")
        if isinstance(v.get("value"), dict):
            for k2, v2 in v["value"].items():
                if isinstance(v2, float):
                    print(f"          {k2}: {v2:,.2f}")
                else:
                    print(f"          {k2}: {v2}")
        elif isinstance(v.get("value"), list) and len(v["value"]) <= 10:
            for item in v["value"]:
                print(f"          {item}")
        else:
            print(f"          Value: {v.get('value')}")

    # ---- Step 4: Verification queries ----
    normalizer.close()  # Release write connection before read-only verification

    print(f"\n{'=' * 50}")
    print("VERIFICATION QUERIES")
    print(f"{'=' * 50}")

    import duckdb
    conn = duckdb.connect(str(test_db), read_only=True)

    # Query 1: Total line items
    count = conn.execute("SELECT COUNT(*) FROM line_items").fetchone()[0]
    print(f"\n1. SELECT COUNT(*) FROM line_items -> {count}")

    # Query 2: P&L line items sample (v2 schema: line_items JOIN source_tables)
    print("\n2. P&L line items (up to 10):")
    try:
        rows = conn.execute(
            """SELECT li.account_name, li.amount, li.amount_inr,
                      li.source_unit, li.period_label, li.is_total
               FROM line_items li
               JOIN source_tables st ON li.table_id = st.table_id
               WHERE st.table_type = 'profit_and_loss'
                 AND NOT li.is_comparative
               LIMIT 10"""
        ).fetchall()
        if rows:
            print(f"   {'Account Name':<35} {'Amount':>12} {'Amount INR':>18} {'Unit':<10} {'Period':<15} {'Total?'}")
            print(f"   {'-'*35} {'-'*12} {'-'*18} {'-'*10} {'-'*15} {'-'*6}")
            for r in rows:
                acct_name = (str(r[0]) or "")[:34]
                amt = r[1] if r[1] is not None else 0
                amt_inr = r[2] if r[2] is not None else 0
                print(f"   {acct_name:<35} {amt:>12,.2f} {amt_inr:>18,.2f} {r[3] or '':<10} {r[4] or '':<15} {r[5]}")
        else:
            print("   (no P&L line items found)")
    except Exception as exc:
        print(f"   [ERROR] {exc}")

    # Query 3: Source tables
    print("\n3. Source tables:")
    try:
        docs = conn.execute(
            "SELECT table_id, source_file, table_type, source_unit, sheet_name FROM source_tables"
        ).fetchall()
        for d in docs:
            tid = str(d[0])[:12] if d[0] else "?"
            src = Path(d[1]).name if d[1] else "(none)"
            print(f"   ID: {tid:<14} File: {src:<50} Type: {d[2] or '':<25} Unit: {d[3] or '':<10} Sheet: {d[4] or ''}")
    except Exception as exc:
        print(f"   [ERROR] {exc}")

    # Query 4: Related parties
    print("\n4. Related parties:")
    try:
        rps = conn.execute(
            "SELECT rp_id, party_name, relationship_category, amount_inr FROM related_parties"
        ).fetchall()
        if rps:
            for rp in rps:
                amt = rp[3] if rp[3] is not None else 0
                print(f"   {rp[0]:<20} {rp[1] or '':<40} {rp[2] or '':<20} {amt:>18,.2f}")
        else:
            print("   (no related parties found)")
    except Exception as exc:
        print(f"   [ERROR] {exc}")

    # Query 5: Source tables summary
    print("\n5. Source tables summary:")
    try:
        tbls = conn.execute(
            "SELECT table_type, source_unit, row_count, col_count, section_heading FROM source_tables"
        ).fetchall()
        for t in tbls:
            heading = (str(t[4]) or "")[:50] if t[4] else "(none)"
            print(f"   Type: {t[0] or '':<20} Unit: {t[1] or '':<10} Rows: {t[2] or 0:>4} Cols: {t[3] or 0:>3}  Heading: {heading}")
    except Exception as exc:
        print(f"   [ERROR] {exc}")

    # Query 6: Line items per account
    print("\n6. Line items per account (top 15):")
    try:
        accts = conn.execute(
            """SELECT account_name, COUNT(*) as cnt, SUM(amount_inr) as total_inr
               FROM line_items
               GROUP BY account_name
               ORDER BY cnt DESC
               LIMIT 15"""
        ).fetchall()
        for a in accts:
            name = (str(a[0]) or "")[:50]
            total = a[2] if a[2] is not None else 0
            print(f"   {name:<50} Count: {a[1]:>4}  Total INR: {total:>18,.2f}")
    except Exception as exc:
        print(f"   [ERROR] {exc}")

    # Query 7: Benford's readiness check
    print("\n7. Benford's readiness check:")
    try:
        benford_count = conn.execute(
            "SELECT COUNT(*) FROM line_items WHERE amount_inr > 0 AND NOT is_total"
        ).fetchone()[0]
        print(f"   Non-total line items with amount_inr > 0: {benford_count}")
        if benford_count > 50:
            print(f"   READY for Benford's analysis ({benford_count} records, minimum 50)")
        else:
            print(f"   NOT READY for Benford's analysis ({benford_count} records, need > 50)")
    except Exception as exc:
        print(f"   [ERROR] {exc}")

    conn.close()

    print(f"\n{'=' * 70}")
    print(f"Test database saved to: {test_db}")
    print(f"{'=' * 70}")

    # ---- Step 5 (optional): Run forensic skills ----
    if args.run_skills:
        _run_skills(str(test_db))


def _run_skills(db_path: str) -> None:
    """Run all available forensic skills with default parameters."""
    import subprocess

    print(f"\n{'=' * 70}")
    print("FORENSIC SKILLS — Pass 1 Sweep")
    print(f"{'=' * 70}")

    skills = [
        {
            "name": "benfords-analysis",
            "script": "skills/benfords-analysis/scripts/benfords.py",
            "args": [
                "--db", db_path,
                "--table", "line_items",
                "--column", "amount",
                "--tests", "all",
                "--output", "skills/benfords-analysis/outputs/sweep.json",
            ],
        },
        {
            "name": "duplicate-detector",
            "script": "skills/duplicate-detector/scripts/duplicate_detector.py",
            "args": [
                "--db", db_path,
                "--output", "skills/duplicate-detector/outputs/sweep.json",
            ],
        },
        {
            "name": "ratio-analyzer",
            "script": "skills/ratio-analyzer/scripts/ratio_analyzer.py",
            "args": [
                "--db", db_path,
                "--output", "skills/ratio-analyzer/outputs/sweep.json",
            ],
        },
        {
            "name": "anomaly-detector",
            "script": "skills/anomaly-detector/scripts/anomaly_detector.py",
            "args": [
                "--db", db_path,
                "--table", "line_items",
                "--column", "amount",
                "--output", "skills/anomaly-detector/outputs/sweep.json",
            ],
        },
        {
            "name": "network-analyzer",
            "script": "skills/network-analyzer/scripts/network_analyzer.py",
            "args": [
                "--db", db_path,
                "--output", "skills/network-analyzer/outputs/sweep.json",
            ],
        },
    ]

    results = []
    for skill in skills:
        script_path = _PROJECT_ROOT / skill["script"]
        if not script_path.exists():
            print(f"\n  [{skill['name']}] SKIP — script not found: {script_path}")
            continue

        print(f"\n  [{skill['name']}] Running...")
        cmd = [sys.executable, str(script_path)] + skill["args"]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                cwd=str(_PROJECT_ROOT),
            )
            if proc.returncode == 0:
                print(f"  [{skill['name']}] OK")
                results.append((skill["name"], "OK"))
            else:
                print(f"  [{skill['name']}] FAILED (exit {proc.returncode})")
                if proc.stderr:
                    for line in proc.stderr.strip().split("\n")[-5:]:
                        print(f"    {line}")
                results.append((skill["name"], f"FAILED (exit {proc.returncode})"))
        except subprocess.TimeoutExpired:
            print(f"  [{skill['name']}] TIMEOUT (120s)")
            results.append((skill["name"], "TIMEOUT"))
        except Exception as exc:
            print(f"  [{skill['name']}] ERROR: {exc}")
            results.append((skill["name"], f"ERROR: {exc}"))

    print(f"\n{'=' * 50}")
    print("SKILL SWEEP SUMMARY")
    print(f"{'=' * 50}")
    for name, status in results:
        print(f"  {name:<25} {status}")


if __name__ == "__main__":
    main()
