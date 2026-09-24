"""
Data Normalizer v2 -- 4-table forensic workbench schema.

Transforms ExtractedTable objects into DuckDB relational rows across four
tables: source_tables, line_items, related_parties, analysis_results.

Usage:
    from pipeline.data_normalizer import DataNormalizer

    normalizer = DataNormalizer(db_path="forensic_case.duckdb")
    normalizer.initialize_schema()
    result = normalizer.normalize_and_load(
        extracted_tables, entity_name="EXCO", fiscal_year="2023-24"
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("pipeline.data_normalizer")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_handler)

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# ExtractedTable import / fallback
# ---------------------------------------------------------------------------
try:
    from pipeline.table_extractor import ExtractedTable
except ImportError:
    @dataclass
    class ExtractedTable:  # type: ignore[no-redef]
        df: pd.DataFrame
        source_file: str = ""
        source_file_type: str = ""
        page_number: int | None = None
        sheet_name: str = ""
        section_heading: str = ""
        section_hierarchy: list[str] = field(default_factory=list)
        table_index: int = 0
        bbox: str | None = None
        surrounding_text: str = ""
        raw_cell_text: str | None = None
        extraction_method: str = "unknown"
        extraction_confidence: float = 0.0
        row_count: int = 0
        col_count: int = 0
        has_merged_cells: bool = False
        has_numeric_data: bool = False
        metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# NormalizationResult
# ---------------------------------------------------------------------------

@dataclass
class NormalizationResult:
    """Outcome of a normalize_and_load run."""

    db_path: str
    source_tables_loaded: int = 0
    tables_classified: int = 0
    line_items_loaded: int = 0
    related_parties_loaded: int = 0
    classification_results: list[dict] = field(default_factory=list)
    validation_results: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

UNIT_MULTIPLIERS: dict[str, float] = {
    "absolute": 1.0,
    "thousands": 1_000.0,
    "lakhs": 1_00_000.0,
    "crores": 1_00_00_000.0,
    "millions": 1_000_000.0,
    "billions": 1_000_000_000.0,
}

_VALID_TABLE_TYPES = {
    "profit_and_loss",
    "balance_sheet",
    "cash_flow",
    "notes_schedule",
    "trial_balance",
    "general_ledger",
    "bank_statement",
    "aging_schedule",
    "ratio_schedule",
    "related_party",
    "other",
}


def _normalize_amount(value: float, source_unit: str) -> float:
    """Convert *value* from *source_unit* to absolute INR."""
    multiplier = UNIT_MULTIPLIERS.get(source_unit, 1.0)
    return value * multiplier


def _parse_number(text: str) -> tuple[float | None, bool]:
    """Best-effort parse of an Indian-format number string.

    Returns (value, is_negative).  Returns (None, False) on failure.
    """
    if not isinstance(text, str):
        try:
            return (float(text), float(text) < 0)
        except (TypeError, ValueError):
            return (None, False)

    cleaned = text.strip()
    for sym in ("₹", "Rs.", "Rs", "INR", "%"):
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.strip()
    if not cleaned or cleaned == "-" or cleaned.lower() in ("nil", "n/a", "na", "—", "–"):
        return (None, False)

    is_negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        is_negative = True
        cleaned = cleaned[1:-1]
    elif cleaned.startswith("-"):
        is_negative = True
        cleaned = cleaned[1:]

    cleaned = cleaned.replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return (None, False)

    return (value, is_negative)


def _generate_id() -> str:
    return str(uuid.uuid4())


def _compute_file_hash(file_path: str | Path) -> str:
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
    except OSError:
        return ""
    return sha256.hexdigest()


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_RX = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


def _label_year_month(label: str) -> tuple[int, int] | None:
    """Return (year, month) for date-style labels.

    Handles '2024-03-31', '31.03.2024', '31/03/2024', '31-03-2024',
    '31 Mar 2025', '31st March, 2025' and 'March 31, 2024'.
    """
    text = label.strip().lower()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\b\d{1,2}[./-](\d{1,2})[./-](\d{4})\b", text)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH_RX + r",?\s+(\d{4})\b", text)
    if m:
        return int(m.group(2)), _MONTHS.index(m.group(1)) + 1
    m = re.search(r"\b" + _MONTH_RX + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(\d{4})\b", text)
    if m:
        return int(m.group(2)), _MONTHS.index(m.group(1)) + 1
    return None


def _fiscal_year_to_dates(fy: str) -> tuple[str, str]:
    """Convert 'FY 2023-24' or '2023-24' to ('2023-04-01', '2024-03-31').

    Date-style labels ('31 Mar 2024', 'As at 31.03.2024') map to the Indian
    fiscal year (April-March) that contains the date.
    """
    ym = _label_year_month(fy)
    if ym:
        year, month = ym
        start_year = year if month >= 4 else year - 1
        return (f"{start_year}-04-01", f"{start_year + 1}-03-31")

    match = re.search(r"(\d{4})\s*[-–]\s*(\d{2,4})", fy)
    if match:
        start_year = int(match.group(1))
        end_part = match.group(2)
        if len(end_part) == 2:
            end_year = int(str(start_year)[:2] + end_part)
        else:
            end_year = int(end_part)
        return (f"{start_year}-04-01", f"{end_year}-03-31")
    # fallback: try single year
    match2 = re.search(r"(\d{4})", fy)
    if match2:
        year = int(match2.group(1))
        return (f"{year}-04-01", f"{year + 1}-03-31")
    return ("", "")


# ---------------------------------------------------------------------------
# Header cleaning
# ---------------------------------------------------------------------------

def _clean_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Sanitise DataFrame column names.

    - Cast all column names to str.
    - If every column name looks like a sequential integer (0, 1, 2, ...),
      promote row 0 as headers and drop that row.
    - Deduplicate column names by appending _1, _2, etc.
    """
    cols = [str(c) for c in df.columns]

    # Detect auto-integer headers (pandas default when no header found)
    try:
        int_cols = [int(c) for c in cols]
        if int_cols == list(range(len(int_cols))) and len(df) > 0:
            new_headers = [str(v).strip() if pd.notna(v) else f"col_{i}"
                           for i, v in enumerate(df.iloc[0])]
            df = df.iloc[1:].reset_index(drop=True)
            df.columns = new_headers
            cols = list(df.columns)
    except (ValueError, TypeError):
        pass

    df.columns = cols

    # Deduplicate
    seen: dict[str, int] = {}
    deduped: list[str] = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            deduped.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            deduped.append(c)
    df.columns = deduped
    return df


# ---------------------------------------------------------------------------
# Unit detection (from metadata, NOT filename)
# ---------------------------------------------------------------------------

def _detect_unit(table: ExtractedTable) -> str:
    """Extract reporting unit from metadata, section_heading, and surrounding_text.

    Priority: metadata["source_unit"] (set by extractor) > regex on headings.
    """
    # Primary: extractor already detected the unit
    meta_unit = (getattr(table, "metadata", None) or {}).get("source_unit")
    if meta_unit and meta_unit in UNIT_MULTIPLIERS:
        return meta_unit

    # Fallback: regex on heading + surrounding text
    text = " ".join([
        (getattr(table, "section_heading", None) or ""),
        (getattr(table, "surrounding_text", None) or ""),
    ]).lower()

    if "crore" in text:
        return "crores"
    if "lakh" in text:
        return "lakhs"
    if "thousand" in text:
        return "thousands"
    if "million" in text:
        return "millions"
    if "billion" in text:
        return "billions"
    return "absolute"


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _detect_is_total(label: str) -> bool:
    """Return True if *label* looks like a total / subtotal row."""
    if not label:
        return False
    return bool(re.match(r"^\s*total\b", label, re.IGNORECASE) or
                re.match(r"^\s*sub[\s-]*total\b", label, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Column identification
# ---------------------------------------------------------------------------

def _is_period_header(name: str) -> bool:
    """True if a column header names a reporting period.

    Matches fiscal-year ranges ('FY 2023-24', '2023-24'), 'As at ...',
    date-style headers ('31 Mar 2025', '31.03.2024') and bare years, so
    that each year column keeps its own period label.
    """
    cl = str(name).strip().lower()
    return bool(
        re.search(r"fy\s*\d{4}", cl)
        or re.search(r"\d{4}\s*[-–]\s*\d{2,4}", cl)
        or re.search(r"as\s*at", cl)
        or _label_year_month(cl) is not None
        or re.search(r"\b(19|20)\d{2}\b", cl)
    )


def _identify_columns(
    df: pd.DataFrame,
    col_map: dict[str, str | None],
    reporting_period: str,
    fiscal_year: str,
) -> tuple[str | None, list[tuple[str, str]], str | None]:
    """Determine (account_col, [(amount_col, period_label)], note_col).

    Uses the column_mapping from LLM / heuristic classification. Falls back
    to positional detection when the mapping is incomplete.
    """
    acct_col: str | None = None
    note_col: str | None = None
    amount_cols: list[tuple[str, str]] = []

    for col_name, mapping in col_map.items():
        if col_name not in df.columns:
            continue
        if mapping == "account_name":
            acct_col = col_name
        elif mapping == "note_ref":
            note_col = col_name
        elif mapping == "amount":
            amount_cols.append((col_name, reporting_period or fiscal_year))
        elif mapping == "ignore" or mapping is None:
            continue
        else:
            # Treat as period-label column (wide-format)
            amount_cols.append((col_name, mapping))

    # Fallback: first column that is mostly text -> account_name
    if acct_col is None and len(df.columns) > 0:
        first_col = str(df.columns[0])
        try:
            text_ratio = df[first_col].apply(lambda x: isinstance(x, str)).mean()
            if text_ratio > 0.3:
                acct_col = first_col
        except Exception:
            acct_col = first_col

    # Fallback: numeric columns -> amount
    # Uses _parse_number so Indian-format strings like "1,23,456" are counted.
    if not amount_cols:
        for col_name in df.columns:
            if col_name == acct_col or col_name == note_col:
                continue
            mapping_val = col_map.get(str(col_name))
            if mapping_val == "note_ref" or mapping_val == "ignore":
                continue
            try:
                # First try pandas native numeric detection
                numeric_count = pd.to_numeric(df[col_name], errors="coerce").notna().sum()
                if numeric_count == 0:
                    # Fall back to _parse_number for Indian-format strings
                    numeric_count = sum(
                        1 for v in df[col_name]
                        if pd.notna(v) and _parse_number(str(v))[0] is not None
                    )
                if numeric_count > 0:
                    # If the column name itself looks like a period label, use it
                    cn = str(col_name).strip()
                    if _is_period_header(cn):
                        period = cn
                    else:
                        period = reporting_period or fiscal_year
                    amount_cols.append((cn, period))
            except Exception:
                continue

    return acct_col, amount_cols, note_col


# ---------------------------------------------------------------------------
# Table tagging (pure heuristic — no LLM)
# ---------------------------------------------------------------------------

def _tag_table(table: ExtractedTable) -> dict:
    """Heuristic table tagging from headings, sheet names, and column names."""
    columns = [str(c) for c in table.df.columns]
    col_text = " ".join(c.lower() for c in columns)
    heading = (getattr(table, "section_heading", None) or "").lower()
    sheet = (getattr(table, "sheet_name", None) or "").lower()
    surr = (getattr(table, "surrounding_text", None) or "").lower()
    all_text = f"{col_text} {heading} {sheet} {surr}"

    # --- table_type ---
    table_type = "other"
    if any(k in all_text for k in ("profit and loss", "p&l", "pnl", "income statement", "profit & loss")):
        table_type = "profit_and_loss"
    elif any(k in all_text for k in ("balance sheet", "financial position")):
        table_type = "balance_sheet"
    elif any(k in all_text for k in ("cash flow",)):
        table_type = "cash_flow"
    elif any(k in all_text for k in ("trial balance",)):
        table_type = "trial_balance"
    elif any(k in all_text for k in ("general ledger",)):
        table_type = "general_ledger"
    elif any(k in all_text for k in ("bank statement",)):
        table_type = "bank_statement"
    elif any(k in all_text for k in ("ageing", "aging")):
        table_type = "aging_schedule"
    elif any(k in all_text for k in ("ratio",)):
        table_type = "ratio_schedule"
    elif any(k in all_text for k in ("related party",)):
        table_type = "related_party"
    elif any(k in all_text for k in ("note", "schedule")):
        table_type = "notes_schedule"

    # --- reporting_unit (metadata first, then regex fallback) ---
    meta_unit = (getattr(table, "metadata", None) or {}).get("source_unit")
    if meta_unit and meta_unit in UNIT_MULTIPLIERS:
        reporting_unit = meta_unit
    elif "crore" in all_text:
        reporting_unit = "crores"
    elif "lakh" in all_text:
        reporting_unit = "lakhs"
    elif "thousand" in all_text:
        reporting_unit = "thousands"
    elif "million" in all_text:
        reporting_unit = "millions"
    elif "billion" in all_text:
        reporting_unit = "billions"
    else:
        reporting_unit = "absolute"

    # --- reporting_period ---
    reporting_period = ""
    fy_match = re.search(r"(?:FY\s*)?(\d{4})\s*[-–]\s*(\d{2,4})", all_text, re.IGNORECASE)
    if fy_match:
        y1 = fy_match.group(1)
        y2 = fy_match.group(2)
        reporting_period = f"FY {y1}-{y2}"
    else:
        year_match = re.search(r"20\d{2}", all_text)
        if year_match:
            reporting_period = year_match.group(0)

    # --- column_mapping ---
    column_mapping: dict[str, str | None] = {}
    for col in columns:
        cl = col.strip().lower()
        if cl in ("particulars", "description", "account", "account name",
                   "item", "items", "line item", "head", "heads"):
            column_mapping[col] = "account_name"
        elif cl in ("note", "note no", "note no.", "notes", "ref", "note ref"):
            column_mapping[col] = "note_ref"
        elif _is_period_header(col):
            # Period column: use the column name as period label
            column_mapping[col] = col.strip()
        elif cl in ("amount", "debit", "credit", "balance", "total", "value"):
            column_mapping[col] = "amount"
        else:
            # check if this column has mostly numeric data (including "Unnamed:" cols)
            try:
                numeric_count = pd.to_numeric(table.df[col], errors="coerce").notna().sum()
                if numeric_count == 0:
                    numeric_count = sum(
                        1 for v in table.df[col]
                        if pd.notna(v) and _parse_number(str(v))[0] is not None
                    )
                if numeric_count > len(table.df) * 0.4:
                    column_mapping[col] = "amount"
                elif re.search(r"unnamed|^\s*$", cl):
                    column_mapping[col] = "ignore"
                else:
                    column_mapping[col] = None
            except Exception:
                column_mapping[col] = None

    # Statements list the current period first, so the first period column is
    # the reporting period and later ones are comparatives.
    period_columns = [
        label for label in column_mapping.values()
        if label not in (None, "account_name", "note_ref", "amount", "ignore")
    ]
    if period_columns:
        reporting_period = period_columns[0]

    return {
        "table_type": table_type,
        "reporting_unit": reporting_unit,
        "reporting_period": reporting_period,
        "column_mapping": column_mapping,
    }


# ---------------------------------------------------------------------------
# Related-party detection
# ---------------------------------------------------------------------------

def _is_related_party_table(table: ExtractedTable, classification: dict) -> bool:
    """Return True if this table should be loaded into related_parties."""
    if classification.get("table_type") == "related_party":
        return True
    heading = (getattr(table, "section_heading", None) or "").lower()
    sheet = (getattr(table, "sheet_name", None) or "").lower()
    return "related party" in heading or "related party" in sheet


# ---------------------------------------------------------------------------
# Schema DDL (embedded -- no external SQL file)
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS source_tables (
    table_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    source_file_type TEXT,
    page_number INTEGER,
    sheet_name TEXT,
    section_heading TEXT,
    section_hierarchy TEXT,
    table_type TEXT,
    source_unit TEXT DEFAULT 'absolute',
    extraction_method TEXT,
    extraction_confidence DOUBLE,
    row_count INTEGER,
    col_count INTEGER,
    entity_name TEXT,
    fiscal_year TEXT,
    created_at TEXT DEFAULT (CAST(current_timestamp AS TEXT))
);

CREATE TABLE IF NOT EXISTS line_items (
    line_item_id TEXT PRIMARY KEY,
    table_id TEXT,
    account_name TEXT,
    amount DOUBLE,
    amount_inr DOUBLE,
    period_label TEXT,
    period_start TEXT,
    period_end TEXT,
    source_unit TEXT,
    source_page INTEGER,
    source_row INTEGER,
    source_col INTEGER,
    raw_cell_text TEXT,
    is_total BOOLEAN DEFAULT FALSE,
    is_comparative BOOLEAN DEFAULT FALSE,
    note_ref TEXT,
    tags TEXT,
    created_at TEXT DEFAULT (CAST(current_timestamp AS TEXT))
);

CREATE TABLE IF NOT EXISTS related_parties (
    rp_id TEXT PRIMARY KEY,
    table_id TEXT,
    party_name TEXT,
    relationship_category TEXT,
    transaction_type TEXT,
    amount DOUBLE,
    amount_inr DOUBLE,
    period_label TEXT,
    source_unit TEXT,
    tags TEXT,
    created_at TEXT DEFAULT (CAST(current_timestamp AS TEXT))
);

CREATE TABLE IF NOT EXISTS analysis_results (
    result_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    run_timestamp TEXT DEFAULT (CAST(current_timestamp AS TEXT)),
    input_table TEXT,
    input_column TEXT,
    input_filter TEXT,
    result_json TEXT,
    verdict TEXT,
    risk_score DOUBLE,
    metadata_json TEXT
);
"""


# ---------------------------------------------------------------------------
# DataNormalizer
# ---------------------------------------------------------------------------

class DataNormalizer:
    """Orchestrates table classification, normalization, and loading into DuckDB."""

    def __init__(self, db_path: str | Path = "forensic_case.duckdb"):
        self.db_path = str(db_path)
        self._conn = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self):
        if self._conn is None:
            import duckdb
            self._conn = duckdb.connect(self.db_path)
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def initialize_schema(self) -> None:
        """Create all 4 tables from the embedded DDL.  Idempotent."""
        conn = self._get_conn()
        statements = _SCHEMA_DDL.split(";")
        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except Exception as exc:
                msg = str(exc).lower()
                if "duplicate" in msg or "already exists" in msg:
                    continue
                logger.debug("Schema statement warning: %s", exc)
        logger.info("Schema initialized (4 tables: source_tables, line_items, "
                     "related_parties, analysis_results)")

    # ------------------------------------------------------------------
    # source_tables INSERT
    # ------------------------------------------------------------------

    def _insert_source_table(
        self,
        conn,
        table: ExtractedTable,
        classification: dict,
        entity_name: str,
        fiscal_year: str,
    ) -> str:
        """Insert one row into source_tables. Returns table_id."""
        table_id = _generate_id()
        df = table.df

        # Safely read ExtractedTable fields (real vs. fallback dataclass)
        source_file = getattr(table, "source_file", "") or ""
        source_file_type = getattr(table, "source_file_type", None)
        page_number = getattr(table, "page_number", None)
        sheet_name = getattr(table, "sheet_name", None) or None
        section_heading = getattr(table, "section_heading", None) or None
        section_hierarchy = getattr(table, "section_hierarchy", None)
        extraction_method = getattr(table, "extraction_method", None) or None
        extraction_confidence = getattr(table, "extraction_confidence", None)

        hierarchy_json = json.dumps(section_hierarchy) if section_hierarchy else None

        table_type = classification.get("table_type", "other")
        source_unit = classification.get("reporting_unit", "absolute")

        conn.execute(
            """INSERT INTO source_tables
               (table_id, source_file, source_file_type, page_number, sheet_name,
                section_heading, section_hierarchy, table_type, source_unit,
                extraction_method, extraction_confidence, row_count, col_count,
                entity_name, fiscal_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                table_id,
                source_file,
                source_file_type,
                page_number,
                sheet_name,
                section_heading,
                hierarchy_json,
                table_type,
                source_unit,
                extraction_method,
                extraction_confidence,
                len(df),
                len(df.columns),
                entity_name,
                fiscal_year,
            ],
        )
        return table_id

    # ------------------------------------------------------------------
    # line_items loading
    # ------------------------------------------------------------------

    def _load_line_items(
        self,
        conn,
        table: ExtractedTable,
        classification: dict,
        table_id: str,
        source_unit: str,
        fiscal_year: str,
        reporting_period: str,
    ) -> tuple[int, list[str]]:
        """Parse rows and INSERT into line_items. Returns (count, warnings)."""
        df = table.df
        col_map = classification.get("column_mapping", {})

        acct_col, amount_cols, note_col = _identify_columns(
            df, col_map, reporting_period, fiscal_year,
        )

        if not acct_col and not amount_cols:
            return 0, [f"Table from {table.source_file} has no identifiable columns"]

        warnings: list[str] = []
        batch: list[tuple] = []
        row_count = 0

        for row_idx, row in df.iterrows():
            # Account label
            label = ""
            if acct_col and acct_col in row.index:
                label = str(row[acct_col]).strip() if pd.notna(row[acct_col]) else ""
            if not label or label.lower() in ("nan", "none", ""):
                continue

            is_total = _detect_is_total(label)

            # Note reference
            note_ref_val = None
            if note_col and note_col in row.index and pd.notna(row[note_col]):
                note_ref_val = str(row[note_col]).strip() or None

            for col_name, period_label in amount_cols:
                if col_name not in row.index:
                    continue
                cell_raw = row[col_name]
                if pd.isna(cell_raw):
                    continue

                cell_text = str(cell_raw).strip()
                parsed_val, is_neg = _parse_number(cell_text)
                if parsed_val is None:
                    continue

                amount_original = -parsed_val if is_neg else parsed_val
                amount_inr = _normalize_amount(amount_original, source_unit)

                # Period dates
                p_start, p_end = _fiscal_year_to_dates(period_label)
                if not p_start:
                    p_start, p_end = _fiscal_year_to_dates(fiscal_year)

                # Comparative flag
                is_comparative = False
                if reporting_period and period_label and period_label != reporting_period:
                    is_comparative = True

                col_idx = list(df.columns).index(col_name) if col_name in df.columns else None

                batch.append((
                    _generate_id(),       # line_item_id
                    table_id,             # table_id
                    label,                # account_name
                    amount_original,      # amount
                    amount_inr,           # amount_inr
                    period_label or None, # period_label
                    p_start or None,      # period_start
                    p_end or None,        # period_end
                    source_unit,          # source_unit
                    getattr(table, "page_number", None),  # source_page
                    int(row_idx) if isinstance(row_idx, (int, np.integer)) else None,  # source_row
                    col_idx,              # source_col
                    cell_text,            # raw_cell_text
                    is_total,             # is_total
                    is_comparative,       # is_comparative
                    note_ref_val,         # note_ref
                    None,                 # tags (JSON)
                ))
                row_count += 1

        if batch:
            conn.executemany(
                """INSERT INTO line_items
                   (line_item_id, table_id, account_name, amount, amount_inr,
                    period_label, period_start, period_end, source_unit,
                    source_page, source_row, source_col, raw_cell_text,
                    is_total, is_comparative, note_ref, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )

        return row_count, warnings

    # ------------------------------------------------------------------
    # related_parties loading
    # ------------------------------------------------------------------

    def _load_related_parties(
        self,
        conn,
        table: ExtractedTable,
        classification: dict,
        table_id: str,
        source_unit: str,
        fiscal_year: str,
    ) -> int:
        """Extract rows from a related-party table into related_parties.

        Attempts to identify party_name, relationship_category,
        transaction_type, and amount columns from the classification
        column_mapping and heuristic detection.

        Returns the number of rows loaded.
        """
        df = table.df
        col_map = classification.get("column_mapping", {})
        reporting_period = classification.get("reporting_period", "") or fiscal_year

        # Identify columns by role
        party_col: str | None = None
        relationship_col: str | None = None
        transaction_col: str | None = None
        amount_cols: list[tuple[str, str]] = []

        for col_name, mapping in col_map.items():
            if col_name not in df.columns:
                continue
            cl = col_name.strip().lower()
            if mapping == "account_name" or "party" in cl or "name" in cl:
                if party_col is None:
                    party_col = col_name
            elif "relation" in cl:
                relationship_col = col_name
            elif "transaction" in cl or "nature" in cl:
                transaction_col = col_name
            elif mapping == "amount":
                amount_cols.append((col_name, reporting_period))
            elif mapping not in ("ignore", "note_ref", None):
                amount_cols.append((col_name, mapping))

        # Fallback: detect columns by name heuristic when col_map is sparse
        if party_col is None or relationship_col is None or transaction_col is None:
            for col_name in df.columns:
                cl = str(col_name).strip().lower()
                if party_col is None and ("party" in cl or "name" in cl):
                    party_col = str(col_name)
                elif relationship_col is None and "relation" in cl:
                    relationship_col = str(col_name)
                elif transaction_col is None and ("transaction" in cl or "nature" in cl):
                    transaction_col = str(col_name)

        # Fallback: first text column is party name
        if party_col is None and len(df.columns) > 0:
            party_col = str(df.columns[0])

        # Fallback: numeric columns are amounts
        if not amount_cols:
            for col_name in df.columns:
                if col_name in (party_col, relationship_col, transaction_col):
                    continue
                try:
                    nc = pd.to_numeric(df[col_name], errors="coerce").notna().sum()
                    if nc == 0:
                        nc = sum(
                            1 for v in df[col_name]
                            if pd.notna(v) and _parse_number(str(v))[0] is not None
                        )
                    if nc > 0:
                        amount_cols.append((str(col_name), reporting_period))
                except Exception:
                    continue

        batch: list[tuple] = []
        for _, row in df.iterrows():
            party_name = ""
            if party_col and party_col in row.index and pd.notna(row[party_col]):
                party_name = str(row[party_col]).strip()
            if not party_name or party_name.lower() in ("nan", "none", ""):
                continue

            rel_cat = None
            if relationship_col and relationship_col in row.index and pd.notna(row[relationship_col]):
                rel_cat = str(row[relationship_col]).strip() or None

            txn_type = None
            if transaction_col and transaction_col in row.index and pd.notna(row[transaction_col]):
                txn_type = str(row[transaction_col]).strip() or None

            for col_name, period_label in amount_cols:
                if col_name not in row.index:
                    continue
                cell_raw = row[col_name]
                if pd.isna(cell_raw):
                    continue
                parsed_val, is_neg = _parse_number(str(cell_raw))
                if parsed_val is None:
                    continue
                amount_original = -parsed_val if is_neg else parsed_val
                amount_inr = _normalize_amount(amount_original, source_unit)

                batch.append((
                    _generate_id(),
                    table_id,
                    party_name,
                    rel_cat,
                    txn_type,
                    amount_original,
                    amount_inr,
                    period_label or None,
                    source_unit,
                    None,  # tags
                ))

        if batch:
            conn.executemany(
                """INSERT INTO related_parties
                   (rp_id, table_id, party_name, relationship_category,
                    transaction_type, amount, amount_inr, period_label,
                    source_unit, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )
        return len(batch)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> list[dict]:
        """Run integrity checks on the loaded workbench. Returns check results."""
        conn = self._get_conn()
        results: list[dict] = []

        # 1. Line-item count
        try:
            count = conn.execute("SELECT COUNT(*) FROM line_items").fetchone()[0]
            results.append({
                "check": "line_item_count",
                "status": "info",
                "value": count,
                "detail": "Total line items in workbench",
            })
        except Exception as exc:
            logger.debug("line_item_count check skipped: %s", exc)

        # 2. Unit consistency across source_tables
        try:
            units = conn.execute(
                "SELECT DISTINCT source_unit FROM source_tables WHERE source_unit IS NOT NULL"
            ).fetchall()
            unit_set = {r[0] for r in units}
            if len(unit_set) > 1:
                results.append({
                    "check": "unit_consistency",
                    "status": "warning",
                    "value": list(unit_set),
                    "detail": "Multiple reporting units detected across source tables",
                })
            else:
                results.append({
                    "check": "unit_consistency",
                    "status": "pass",
                    "value": list(unit_set),
                    "detail": "All source tables use consistent reporting unit",
                })
        except Exception as exc:
            logger.debug("unit_consistency check skipped: %s", exc)

        # 3. Related parties count
        try:
            rp_count = conn.execute("SELECT COUNT(*) FROM related_parties").fetchone()[0]
            results.append({
                "check": "related_parties_count",
                "status": "info",
                "value": rp_count,
                "detail": "Total related-party rows in workbench",
            })
        except Exception as exc:
            logger.debug("related_parties_count check skipped: %s", exc)

        # 4. Benford's readiness: count line items suitable for Benford analysis
        try:
            benford_count = conn.execute(
                "SELECT COUNT(*) FROM line_items WHERE amount_inr > 0 AND NOT is_total"
            ).fetchone()[0]
            results.append({
                "check": "benford_readiness",
                "status": "pass" if benford_count >= 30 else "warning",
                "value": benford_count,
                "detail": (
                    f"{benford_count} non-total positive line items available "
                    f"for Benford's analysis (minimum ~30 recommended)"
                ),
            })
        except Exception as exc:
            logger.debug("benford_readiness check skipped: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def normalize_and_load(
        self,
        extracted_tables: list[ExtractedTable],
        entity_name: str = "Unknown Entity",
        fiscal_year: str = "",
    ) -> NormalizationResult:
        """Classify, normalize, and load extracted tables into DuckDB.

        Args:
            extracted_tables: list of ExtractedTable objects from the extractor.
            entity_name: company/entity short name (e.g., "EXCO").
            fiscal_year: primary fiscal year label (e.g., "2023-24").

        Returns:
            NormalizationResult with statistics and validation results.
        """
        result = NormalizationResult(db_path=self.db_path)

        if not extracted_tables:
            result.warnings.append("No tables provided")
            return result

        try:
            self.initialize_schema()
        except Exception as exc:
            result.errors.append(f"Schema initialization failed: {exc}")
            return result

        conn = self._get_conn()
        total_line_items = 0
        total_rp = 0
        all_warnings: list[str] = []
        all_classification_results: list[dict] = []

        for table in extracted_tables:
            try:
                # Clean headers
                df = _clean_headers(table.df.copy())
                table.df = df

                # Tag (pure heuristic, no LLM)
                classification = _tag_table(table)

                result.tables_classified += 1
                source_unit = classification.get("reporting_unit", "absolute")
                reporting_period = classification.get("reporting_period", "")

                # Insert source table row
                table_id = self._insert_source_table(
                    conn, table, classification, entity_name, fiscal_year,
                )
                result.source_tables_loaded += 1

                cls_detail = {
                    "source_file": getattr(table, "source_file", ""),
                    "sheet_name": getattr(table, "sheet_name", None),
                    "table_index": getattr(table, "table_index", 0),
                    "classification": classification,
                    "table_id": table_id,
                }
                all_classification_results.append(cls_detail)

                # Load into related_parties or line_items
                if _is_related_party_table(table, classification):
                    rp_count = self._load_related_parties(
                        conn, table, classification, table_id,
                        source_unit, fiscal_year,
                    )
                    total_rp += rp_count
                else:
                    count, warns = self._load_line_items(
                        conn, table, classification, table_id,
                        source_unit, fiscal_year, reporting_period,
                    )
                    total_line_items += count
                    all_warnings.extend(warns)

            except Exception as exc:
                msg = (
                    f"Failed to process table {getattr(table, 'table_index', '?')} "
                    f"from {getattr(table, 'source_file', '?')}: {exc}"
                )
                logger.error(msg)
                result.errors.append(msg)

        # Validate
        try:
            validation_results = self._validate()
        except Exception as exc:
            logger.warning("Validation failed: %s", exc)
            validation_results = []

        result.line_items_loaded = total_line_items
        result.related_parties_loaded = total_rp
        result.classification_results = all_classification_results
        result.validation_results = validation_results
        result.warnings = all_warnings

        logger.info(
            "Normalization complete: %d source tables, %d classified, "
            "%d line items, %d related-party rows, %d warnings, %d errors",
            result.source_tables_loaded,
            result.tables_classified,
            result.line_items_loaded,
            result.related_parties_loaded,
            len(result.warnings),
            len(result.errors),
        )

        return result
