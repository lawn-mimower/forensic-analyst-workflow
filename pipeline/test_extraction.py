"""
Test script for the TableExtractor module.

Processes test documents from user_documents/ and prints extraction summaries.
Saves a JSON manifest of all results to pipeline/test_output/extraction_manifest.json.

Usage:
    python -m pipeline.test_extraction
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_DOCS = PROJECT_ROOT / "user_documents"
OUTPUT_DIR = PROJECT_ROOT / "pipeline" / "test_output"


def _safe_value(val):
    """Convert a value to something JSON-serializable."""
    if val is None:
        return None
    if isinstance(val, float):
        if val != val:  # NaN check
            return None
        return val
    if isinstance(val, (int, bool, str)):
        return val
    return str(val)


def _df_preview(df, n: int = 3) -> list[dict]:
    """Get first n rows of a DataFrame as a list of dicts, JSON-safe."""
    rows = []
    for _, row in df.head(n).iterrows():
        rows.append({str(k): _safe_value(v) for k, v in row.items()})
    return rows


def print_table_summary(table, idx: int) -> None:
    """Print a human-readable summary of an ExtractedTable."""
    print(f"\n{'='*70}")
    print(f"TABLE {idx + 1}")
    print(f"{'='*70}")
    print(f"  Source:           {Path(table.source_file).name}")
    print(f"  File type:        {table.source_file_type}")
    print(f"  Page/Sheet:       {table.page_number} / {table.sheet_name or 'N/A'}")
    print(f"  Section heading:  {table.section_heading or 'N/A'}")
    print(f"  Section path:     {' > '.join(table.section_hierarchy) if table.section_hierarchy else 'N/A'}")
    print(f"  Shape:            {table.row_count} rows x {table.col_count} cols")
    print(f"  Extraction:       {table.extraction_method}")
    print(f"  Has numeric data: {table.has_numeric_data}")
    print(f"  Has merged cells: {table.has_merged_cells}")

    if table.metadata.get("source_unit"):
        print(f"  Source unit:      {table.metadata['source_unit']}")

    print(f"\n  Columns: {list(table.df.columns)}")

    if not table.df.empty:
        print(f"\n  First {min(3, len(table.df))} rows:")
        preview = table.df.head(3).to_string(index=False, max_cols=8, max_colwidth=30)
        for line in preview.split("\n"):
            print(f"    {line}")

    if table.metadata.get("footnotes"):
        print(f"\n  Footnotes: {table.metadata['footnotes'][:2]}")
    if table.metadata.get("formula_count"):
        print(f"  Formulas detected: {table.metadata['formula_count']}")


def build_manifest_entry(table, idx: int) -> dict:
    """Build a JSON-serializable manifest entry for one table."""
    return {
        "table_index": idx,
        "source_file": table.source_file,
        "source_file_type": table.source_file_type,
        "page_number": table.page_number,
        "sheet_name": table.sheet_name,
        "section_heading": table.section_heading,
        "section_hierarchy": table.section_hierarchy,
        "original_table_index": table.table_index,
        "bbox": table.bbox,
        "surrounding_text": table.surrounding_text,
        "raw_cell_text": table.raw_cell_text,
        "extraction_method": table.extraction_method,
        "extraction_confidence": table.extraction_confidence,
        "row_count": table.row_count,
        "col_count": table.col_count,
        "has_merged_cells": table.has_merged_cells,
        "has_numeric_data": table.has_numeric_data,
        "metadata": {
            k: v for k, v in table.metadata.items()
            if isinstance(v, (str, int, float, bool, list, dict, type(None)))
        },
        "columns": [str(c) for c in table.df.columns],
        "data_preview": _df_preview(table.df, n=3),
    }


def process_file(extractor, file_path: Path) -> list[dict]:
    """Process a single file and return manifest entries."""
    print(f"\n{'#'*70}")
    print(f"# PROCESSING: {file_path.name}")
    print(f"{'#'*70}")

    start = time.time()
    try:
        results = extractor.extract_all(file_path)
    except Exception as exc:
        logger.error("FAILED to process %s: %s", file_path.name, exc, exc_info=True)
        print(f"\n  ERROR: {exc}")
        return []
    elapsed = time.time() - start

    print(f"\n  Extracted {len(results)} table(s) in {elapsed:.1f}s")

    manifest_entries = []
    for idx, table in enumerate(results):
        print_table_summary(table, idx)
        manifest_entries.append(build_manifest_entry(table, idx))

    return manifest_entries


def main() -> None:
    """Run the test extraction on all test documents."""
    from pipeline.table_extractor import TableExtractor

    extractor = TableExtractor()

    # Test files
    test_files = [
        USER_DOCS / "sample_docs/sample_statement.xlsx",
        USER_DOCS / "sample_docs/sample_statement.pdf",
    ]

    # Filter to files that actually exist
    existing_files = []
    for f in test_files:
        if f.exists():
            existing_files.append(f)
        else:
            logger.warning("Test file not found: %s", f)
            print(f"WARNING: Test file not found: {f}")

    if not existing_files:
        print("No test files found. Exiting.")
        sys.exit(1)

    # Process all files
    manifest = {
        "extraction_timestamp": datetime.now().isoformat(),
        "extractor_version": "1.0.0",
        "files_processed": len(existing_files),
        "tables": [],
    }

    total_tables = 0
    for file_path in existing_files:
        entries = process_file(extractor, file_path)
        manifest["tables"].extend(entries)
        total_tables += len(entries)

    manifest["total_tables_extracted"] = total_tables

    # Save manifest
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT_DIR / "extraction_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"  Files processed:  {len(existing_files)}")
    print(f"  Tables extracted: {total_tables}")
    print(f"  Manifest saved:   {manifest_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
