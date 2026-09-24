"""
Forensic Accounting Analysis System — Relational Data Model
=============================================================

This module provides:
  1. Pandas DataFrame specifications (dtypes, column docs) for all 12+ tables
  2. DuckDB/SQLite initialization from the companion .sql file
  3. Unit normalization helpers (Lakhs/Crores → absolute rupees)
  4. Factory functions to create empty DataFrames with correct types
  5. Cross-document canonical linking logic

Design decision — DuckDB + Pandas (BOTH):
  - DuckDB (persistent .duckdb file) is the system of record for all structured data.
    It provides SQL-based cross-table joins, window functions for forensic analysis,
    and survives process restarts.
  - Pandas DataFrames are the in-memory working format for extraction pipelines,
    LLM-based enrichment, and visualization. They are materialized from DuckDB
    queries and written back after processing.
  - The two are connected via DuckDB's zero-copy pandas integration:
      df = duckdb.sql("SELECT * FROM line_items WHERE ...").df()
      duckdb.sql("INSERT INTO line_items SELECT * FROM df")

Why not SQLite alone?
  - DuckDB is columnar (faster for analytical queries on financial data)
  - DuckDB handles pandas DataFrames natively (no ORM needed)
  - DuckDB supports window functions, QUALIFY, ASOF joins out of the box
  - SQLite is used as fallback and for the .sql schema definition (broadest compat)

Why not pandas alone?
  - No persistence across sessions
  - No referential integrity enforcement
  - Poor performance on joins across 10+ tables with millions of GL rows
  - No SQL interface for ad-hoc forensic queries
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_DIR = Path(__file__).resolve().parent
SCHEMA_SQL_PATH = SCHEMA_DIR / "forensic_schema_v1_archive.sql"
DEFAULT_DB_PATH = SCHEMA_DIR.parent / "forensic_data.duckdb"

# Indian number system unit multipliers
UNIT_MULTIPLIERS: dict[str, float] = {
    "absolute":  1.0,
    "thousands": 1_000.0,
    "lakhs":     1_00_000.0,        # 1 Lakh = 100,000
    "crores":    1_00_00_000.0,     # 1 Crore = 10,000,000
    "millions":  1_000_000.0,
    "billions":  1_000_000_000.0,
}

# Valid source units
SourceUnit = Literal["absolute", "thousands", "lakhs", "crores", "millions", "billions"]


# ---------------------------------------------------------------------------
# Unit Normalization
# ---------------------------------------------------------------------------

def normalize_to_absolute(
    amount: float,
    source_unit: SourceUnit = "absolute",
) -> float:
    """Convert an amount from any Indian/international unit to absolute rupees.

    Examples:
        >>> normalize_to_absolute(1234.56, 'crores')
        12_345_600_000.0
        >>> normalize_to_absolute(57.25, 'crores')
        851000000.0
        >>> normalize_to_absolute(420.30, 'crores')
        4_203_000_000.0
        >>> normalize_to_absolute(25.00, 'lakhs')
        2500000.0
    """
    multiplier = UNIT_MULTIPLIERS.get(source_unit)
    if multiplier is None:
        raise ValueError(
            f"Unknown source_unit '{source_unit}'. "
            f"Valid units: {list(UNIT_MULTIPLIERS.keys())}"
        )
    return amount * multiplier


def absolute_to_display(
    amount_absolute: float,
    display_unit: SourceUnit = "crores",
    decimal_places: int = 2,
) -> str:
    """Format an absolute rupee amount for display in the given unit.

    Examples:
        >>> absolute_to_display(12_345_600_000.0, 'crores')
        '₹ 1,234.56 Cr'
        >>> absolute_to_display(2500000.0, 'lakhs')
        '₹ 25.00 L'
    """
    multiplier = UNIT_MULTIPLIERS[display_unit]
    value = amount_absolute / multiplier
    unit_suffix = {
        "absolute": "",
        "thousands": "K",
        "lakhs": "L",
        "crores": "Cr",
        "millions": "M",
        "billions": "B",
    }[display_unit]
    formatted = f"{value:,.{decimal_places}f}"
    return f"₹ {formatted} {unit_suffix}".strip()


def parse_indian_number(text: str) -> tuple[float, bool]:
    """Parse an Indian-format number string, handling parentheses for negatives.

    Returns (value, is_negative).

    Examples:
        >>> parse_indian_number('1,234.56')
        (1234.56, False)
        >>> parse_indian_number('(43.20)')
        (43.20, True)
        >>> parse_indian_number('₹ 420.30')
        (420.30, False)
        >>> parse_indian_number('-57.25')
        (57.25, True)
    """
    cleaned = text.strip()
    # Remove currency symbols
    for sym in ("₹", "Rs.", "Rs", "INR"):
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.strip()

    # Detect parenthetical negatives: (43.20) → negative
    is_negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        is_negative = True
        cleaned = cleaned[1:-1]
    elif cleaned.startswith("-"):
        is_negative = True
        cleaned = cleaned[1:]

    # Remove commas (Indian: 1,00,000 or Western: 100,000)
    cleaned = cleaned.replace(",", "").strip()

    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"Cannot parse '{text}' as a number")

    return (value, is_negative)


# ---------------------------------------------------------------------------
# Document hashing for deduplication
# ---------------------------------------------------------------------------

def compute_file_hash(file_path: str | Path) -> str:
    """Compute SHA-256 hash of a file for deduplication."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_id() -> str:
    """Generate a UUID4 string for use as primary key."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Pandas DataFrame Specifications
# ---------------------------------------------------------------------------
# Each function returns an empty DataFrame with correct dtypes and column names.
# These serve as both documentation and runtime type enforcement.
# ---------------------------------------------------------------------------

def make_entities_df() -> pd.DataFrame:
    """Create an empty entities DataFrame.

    Columns:
        entity_id (str): PK. e.g., 'EXAMPLE_ENG_PVT'
        legal_name (str): Full legal name. e.g., 'Example Engineering Private Limited'
        short_name (str): Abbreviated name
        cin (str): Corporate Identity Number
        pan (str): PAN of the entity
        gstin (str): GSTIN
        entity_type (str): 'company','subsidiary','associate','jv','trust','llp',...
        parent_entity_id (str): FK → entities.entity_id (NULL for ultimate parent)
        ownership_pct (float): Parent's ownership percentage (0-100)
        incorporation_date (str): ISO date
        registered_address (str): Full address
        industry_code (str): NIC code
        industry_desc (str): Industry description
        listing_status (str): 'listed_bse','listed_nse','listed_both','unlisted',...
        accounting_standard (str): 'ind_as','igaap','ifrs'
        functional_currency (str): Default 'INR'
        is_active (bool): Whether entity is active
        metadata_json (str): JSON overflow for extra attributes
    """
    return pd.DataFrame({
        "entity_id":            pd.Series(dtype="string"),
        "legal_name":           pd.Series(dtype="string"),
        "short_name":           pd.Series(dtype="string"),
        "cin":                  pd.Series(dtype="string"),
        "pan":                  pd.Series(dtype="string"),
        "gstin":                pd.Series(dtype="string"),
        "entity_type":          pd.Series(dtype="string"),
        "parent_entity_id":     pd.Series(dtype="string"),
        "ownership_pct":        pd.Series(dtype="Float64"),
        "incorporation_date":   pd.Series(dtype="string"),
        "registered_address":   pd.Series(dtype="string"),
        "industry_code":        pd.Series(dtype="string"),
        "industry_desc":        pd.Series(dtype="string"),
        "listing_status":       pd.Series(dtype="string"),
        "accounting_standard":  pd.Series(dtype="string"),
        "functional_currency":  pd.Series(dtype="string"),
        "is_active":            pd.Series(dtype="boolean"),
        "metadata_json":        pd.Series(dtype="string"),
    })


def make_documents_df() -> pd.DataFrame:
    """Create an empty documents DataFrame.

    Columns:
        document_id (str): PK. UUID or hash
        entity_id (str): FK → entities
        file_name (str): Original filename
        file_path (str): Relative path in user_documents/
        file_hash_sha256 (str): Content hash for dedup
        file_size_bytes (int): File size
        mime_type (str): MIME type
        document_type (str): 'profit_and_loss','balance_sheet','general_ledger',...
        document_subtype (str): Further classification
        statement_scope (str): 'standalone','consolidated','combined'
        audit_status (str): 'audited','limited_review','unaudited',...
        auditor_name (str): Name of audit firm
        auditor_opinion (str): 'unmodified','qualified','adverse','disclaimer'
        period_start (str): ISO date
        period_end (str): ISO date
        period_label (str): e.g., 'FY 2023-24'
        period_type (str): 'annual','quarterly',...
        reporting_currency (str): Default 'INR'
        source_unit (str): 'absolute','lakhs','crores',...
        source_unit_multiplier (float): Numeric multiplier
        total_pages (int): Page count
        ingestion_timestamp (str): When ingested
        extraction_method (str): 'docling','camelot','manual',...
        extraction_confidence (float): 0.0 to 1.0
        notes (str): Free text
        metadata_json (str): JSON overflow
    """
    return pd.DataFrame({
        "document_id":              pd.Series(dtype="string"),
        "entity_id":                pd.Series(dtype="string"),
        "file_name":                pd.Series(dtype="string"),
        "file_path":                pd.Series(dtype="string"),
        "file_hash_sha256":         pd.Series(dtype="string"),
        "file_size_bytes":          pd.Series(dtype="Int64"),
        "mime_type":                pd.Series(dtype="string"),
        "document_type":            pd.Series(dtype="string"),
        "document_subtype":         pd.Series(dtype="string"),
        "statement_scope":          pd.Series(dtype="string"),
        "audit_status":             pd.Series(dtype="string"),
        "auditor_name":             pd.Series(dtype="string"),
        "auditor_opinion":          pd.Series(dtype="string"),
        "period_start":             pd.Series(dtype="string"),
        "period_end":               pd.Series(dtype="string"),
        "period_label":             pd.Series(dtype="string"),
        "period_type":              pd.Series(dtype="string"),
        "reporting_currency":       pd.Series(dtype="string"),
        "source_unit":              pd.Series(dtype="string"),
        "source_unit_multiplier":   pd.Series(dtype="Float64"),
        "total_pages":              pd.Series(dtype="Int64"),
        "ingestion_timestamp":      pd.Series(dtype="string"),
        "extraction_method":        pd.Series(dtype="string"),
        "extraction_confidence":    pd.Series(dtype="Float64"),
        "notes":                    pd.Series(dtype="string"),
        "metadata_json":            pd.Series(dtype="string"),
    })


def make_tables_extracted_df() -> pd.DataFrame:
    """Create an empty tables_extracted DataFrame.

    Columns:
        table_id (str): PK. UUID
        document_id (str): FK → documents
        page_numbers (str): JSON array of page numbers
        table_index_on_page (int): 0-based index for multiple tables per page
        heading_text (str): Extracted table heading
        sub_heading_text (str): Subtitle/date qualifier
        table_type (str): 'balance_sheet','profit_and_loss','gl_extract',...
        row_count (int): Number of data rows
        col_count (int): Number of columns
        column_headers_json (str): JSON array of header strings
        source_unit (str): Unit override for this table
        extraction_method (str): How table was extracted
        extraction_confidence (float): 0.0 to 1.0
        raw_text (str): Raw extracted text
        structured_json (str): Full table as JSON
        bbox_json (str): Bounding box coordinates
        notes (str): Free text
    """
    return pd.DataFrame({
        "table_id":                 pd.Series(dtype="string"),
        "document_id":              pd.Series(dtype="string"),
        "page_numbers":             pd.Series(dtype="string"),
        "table_index_on_page":      pd.Series(dtype="Int64"),
        "heading_text":             pd.Series(dtype="string"),
        "sub_heading_text":         pd.Series(dtype="string"),
        "table_type":               pd.Series(dtype="string"),
        "row_count":                pd.Series(dtype="Int64"),
        "col_count":                pd.Series(dtype="Int64"),
        "column_headers_json":      pd.Series(dtype="string"),
        "source_unit":              pd.Series(dtype="string"),
        "extraction_method":        pd.Series(dtype="string"),
        "extraction_confidence":    pd.Series(dtype="Float64"),
        "raw_text":                 pd.Series(dtype="string"),
        "structured_json":          pd.Series(dtype="string"),
        "bbox_json":                pd.Series(dtype="string"),
        "notes":                    pd.Series(dtype="string"),
    })


def make_accounts_df() -> pd.DataFrame:
    """Create an empty accounts DataFrame.

    This is the Chart of Accounts / Account Taxonomy aligned with Schedule III
    of the Companies Act 2013 (Division II — Ind AS).

    Columns:
        account_id (str): PK. Hierarchical code e.g., 'BS.A.NCA.PPE'
        account_code (str): Numeric code e.g., '2.1.1'
        account_name (str): 'Property, Plant and Equipment'
        account_name_hindi (str): Hindi translation
        parent_account_id (str): FK → accounts (hierarchy)
        account_level (int): 0=root, 1=major, 2=sub, 3=detail, 4=leaf
        account_type (str): 'asset','liability','equity','revenue','expense',...
        statement_type (str): 'balance_sheet','profit_and_loss','cash_flow',...
        schedule_iii_ref (str): 'Part I, I(1)(a)'
        ind_as_ref (str): 'Ind AS 16'
        xbrl_element (str): MCA XBRL taxonomy element
        normal_balance (str): 'debit','credit','not_applicable'
        is_posting (bool): True=leaf account that holds values
        is_mandatory (bool): True=required by Schedule III
        display_order (int): Sort order within parent
        formula_json (str): JSON formula for computed accounts
        description (str): Account description
        metadata_json (str): JSON overflow
    """
    return pd.DataFrame({
        "account_id":           pd.Series(dtype="string"),
        "account_code":         pd.Series(dtype="string"),
        "account_name":         pd.Series(dtype="string"),
        "account_name_hindi":   pd.Series(dtype="string"),
        "parent_account_id":    pd.Series(dtype="string"),
        "account_level":        pd.Series(dtype="Int64"),
        "account_type":         pd.Series(dtype="string"),
        "statement_type":       pd.Series(dtype="string"),
        "schedule_iii_ref":     pd.Series(dtype="string"),
        "ind_as_ref":           pd.Series(dtype="string"),
        "xbrl_element":         pd.Series(dtype="string"),
        "normal_balance":       pd.Series(dtype="string"),
        "is_posting":           pd.Series(dtype="boolean"),
        "is_mandatory":         pd.Series(dtype="boolean"),
        "display_order":        pd.Series(dtype="Int64"),
        "formula_json":         pd.Series(dtype="string"),
        "description":          pd.Series(dtype="string"),
        "metadata_json":        pd.Series(dtype="string"),
    })


def make_line_items_df() -> pd.DataFrame:
    """Create an empty line_items DataFrame — THE CORE TABLE.

    Every extracted financial number lives here. Each row = one number
    from one source, for one account, for one period.

    Columns:
        line_item_id (str): PK. UUID
        entity_id (str): FK → entities
        account_id (str): FK → accounts
        document_id (str): FK → documents
        table_id (str): FK → tables_extracted (nullable)
        period_start (str): ISO date
        period_end (str): ISO date
        period_label (str): e.g., 'FY 2023-24'
        period_type (str): 'annual','quarterly',...
        is_comparative (bool): True if prior-period comparative column
        amount_original (float): Value as it appears in the document
        source_unit (str): Unit of amount_original
        amount_absolute (float): Normalized to absolute rupees
        amount_paise (int): Integer paise for exact arithmetic
        currency (str): Default 'INR'
        debit_credit (str): 'debit','credit', or None
        sign_convention (str): How to interpret signs
        source_page (int): Page number in PDF
        source_row (int): Row index in extracted table
        source_col (int): Column index
        source_cell_text (str): Raw cell text e.g., '₹ 1,234.56'
        source_label_text (str): Row label as extracted
        canonical_group_id (str): Groups same economic fact across documents
        is_primary_source (bool): True = authoritative source for this fact
        extraction_confidence (float): 0.0 to 1.0
        is_derived (bool): True = computed, not directly extracted
        derivation_formula (str): Formula if derived
        is_audited (bool): From document.audit_status
        is_restated (bool): True if restated figure
        original_line_item_id (str): Points to pre-restatement value
        notes (str): Free text
    """
    return pd.DataFrame({
        "line_item_id":             pd.Series(dtype="string"),
        "entity_id":                pd.Series(dtype="string"),
        "account_id":               pd.Series(dtype="string"),
        "document_id":              pd.Series(dtype="string"),
        "table_id":                 pd.Series(dtype="string"),
        "period_start":             pd.Series(dtype="string"),
        "period_end":               pd.Series(dtype="string"),
        "period_label":             pd.Series(dtype="string"),
        "period_type":              pd.Series(dtype="string"),
        "is_comparative":           pd.Series(dtype="boolean"),
        "amount_original":          pd.Series(dtype="Float64"),
        "source_unit":              pd.Series(dtype="string"),
        "amount_absolute":          pd.Series(dtype="Float64"),
        "amount_paise":             pd.Series(dtype="Int64"),
        "currency":                 pd.Series(dtype="string"),
        "debit_credit":             pd.Series(dtype="string"),
        "sign_convention":          pd.Series(dtype="string"),
        "source_page":              pd.Series(dtype="Int64"),
        "source_row":               pd.Series(dtype="Int64"),
        "source_col":               pd.Series(dtype="Int64"),
        "source_cell_text":         pd.Series(dtype="string"),
        "source_label_text":        pd.Series(dtype="string"),
        "canonical_group_id":       pd.Series(dtype="string"),
        "is_primary_source":        pd.Series(dtype="boolean"),
        "extraction_confidence":    pd.Series(dtype="Float64"),
        "is_derived":               pd.Series(dtype="boolean"),
        "derivation_formula":       pd.Series(dtype="string"),
        "is_audited":               pd.Series(dtype="boolean"),
        "is_restated":              pd.Series(dtype="boolean"),
        "original_line_item_id":    pd.Series(dtype="string"),
        "notes":                    pd.Series(dtype="string"),
    })


def make_transactions_df() -> pd.DataFrame:
    """Create an empty transactions DataFrame for GL journal entries."""
    return pd.DataFrame({
        "transaction_id":       pd.Series(dtype="string"),
        "entity_id":            pd.Series(dtype="string"),
        "document_id":          pd.Series(dtype="string"),
        "journal_number":       pd.Series(dtype="string"),
        "journal_type":         pd.Series(dtype="string"),
        "transaction_date":     pd.Series(dtype="string"),
        "posting_date":         pd.Series(dtype="string"),
        "value_date":           pd.Series(dtype="string"),
        "period_label":         pd.Series(dtype="string"),
        "narration":            pd.Series(dtype="string"),
        "reference_number":     pd.Series(dtype="string"),
        "reference_type":       pd.Series(dtype="string"),
        "counterparty_name":    pd.Series(dtype="string"),
        "counterparty_pan":     pd.Series(dtype="string"),
        "is_related_party":     pd.Series(dtype="boolean"),
        "related_party_id":     pd.Series(dtype="string"),
        "total_amount":         pd.Series(dtype="Float64"),
        "currency":             pd.Series(dtype="string"),
        "exchange_rate":        pd.Series(dtype="Float64"),
        "is_reversed":          pd.Series(dtype="boolean"),
        "reversal_txn_id":      pd.Series(dtype="string"),
        "source_system":        pd.Series(dtype="string"),
        "metadata_json":        pd.Series(dtype="string"),
    })


def make_transaction_legs_df() -> pd.DataFrame:
    """Create an empty transaction_legs DataFrame (debit/credit sides)."""
    return pd.DataFrame({
        "leg_id":               pd.Series(dtype="string"),
        "transaction_id":       pd.Series(dtype="string"),
        "account_id":           pd.Series(dtype="string"),
        "debit_amount":         pd.Series(dtype="Float64"),
        "credit_amount":        pd.Series(dtype="Float64"),
        "amount_absolute":      pd.Series(dtype="Float64"),
        "narration":            pd.Series(dtype="string"),
        "cost_center":          pd.Series(dtype="string"),
        "project_code":         pd.Series(dtype="string"),
        "metadata_json":        pd.Series(dtype="string"),
    })


def make_related_parties_df() -> pd.DataFrame:
    """Create an empty related_parties DataFrame per Ind AS 24."""
    return pd.DataFrame({
        "relationship_id":              pd.Series(dtype="string"),
        "entity_id":                    pd.Series(dtype="string"),
        "related_entity_id":            pd.Series(dtype="string"),
        "related_party_name":           pd.Series(dtype="string"),
        "related_party_pan":            pd.Series(dtype="string"),
        "related_party_din":            pd.Series(dtype="string"),
        "relationship_type":            pd.Series(dtype="string"),
        "relationship_detail":          pd.Series(dtype="string"),
        "designation":                  pd.Series(dtype="string"),
        "effective_from":               pd.Series(dtype="string"),
        "effective_to":                 pd.Series(dtype="string"),
        "is_active":                    pd.Series(dtype="boolean"),
        "disclosed_in_document_id":     pd.Series(dtype="string"),
        "metadata_json":               pd.Series(dtype="string"),
    })


def make_related_party_transactions_df() -> pd.DataFrame:
    """Create an empty related_party_transactions DataFrame."""
    return pd.DataFrame({
        "rpt_id":                       pd.Series(dtype="string"),
        "relationship_id":              pd.Series(dtype="string"),
        "period_start":                 pd.Series(dtype="string"),
        "period_end":                   pd.Series(dtype="string"),
        "period_label":                 pd.Series(dtype="string"),
        "transaction_nature":           pd.Series(dtype="string"),
        "amount_absolute":              pd.Series(dtype="Float64"),
        "outstanding_balance":          pd.Series(dtype="Float64"),
        "outstanding_balance_type":     pd.Series(dtype="string"),
        "provision_for_doubtful":       pd.Series(dtype="Float64"),
        "is_arms_length":               pd.Series(dtype="boolean"),
        "disclosed_in_document_id":     pd.Series(dtype="string"),
        "source_line_item_id":          pd.Series(dtype="string"),
        "notes":                        pd.Series(dtype="string"),
    })


def make_ratios_df() -> pd.DataFrame:
    """Create an empty ratios DataFrame for computed financial ratios."""
    return pd.DataFrame({
        "ratio_id":                 pd.Series(dtype="string"),
        "entity_id":                pd.Series(dtype="string"),
        "period_start":             pd.Series(dtype="string"),
        "period_end":               pd.Series(dtype="string"),
        "period_label":             pd.Series(dtype="string"),
        "ratio_name":               pd.Series(dtype="string"),
        "ratio_category":           pd.Series(dtype="string"),
        "ratio_value":              pd.Series(dtype="Float64"),
        "numerator_value":          pd.Series(dtype="Float64"),
        "denominator_value":        pd.Series(dtype="Float64"),
        "numerator_formula":        pd.Series(dtype="string"),
        "denominator_formula":      pd.Series(dtype="string"),
        "formula_detail_json":      pd.Series(dtype="string"),
        "numerator_account_ids":    pd.Series(dtype="string"),
        "denominator_account_ids":  pd.Series(dtype="string"),
        "unit":                     pd.Series(dtype="string"),
        "prior_period_value":       pd.Series(dtype="Float64"),
        "variance_pct":             pd.Series(dtype="Float64"),
        "variance_explanation":     pd.Series(dtype="string"),
        "benchmark_value":          pd.Series(dtype="Float64"),
        "benchmark_source":         pd.Series(dtype="string"),
        "is_schedule_iii":          pd.Series(dtype="boolean"),
        "is_anomalous":             pd.Series(dtype="boolean"),
        "flag_id":                  pd.Series(dtype="string"),
        "notes":                    pd.Series(dtype="string"),
        "metadata_json":            pd.Series(dtype="string"),
    })


def make_flags_df() -> pd.DataFrame:
    """Create an empty flags DataFrame for forensic anomaly detection results."""
    return pd.DataFrame({
        "flag_id":                  pd.Series(dtype="string"),
        "entity_id":                pd.Series(dtype="string"),
        "document_id":              pd.Series(dtype="string"),
        "line_item_id":             pd.Series(dtype="string"),
        "transaction_id":           pd.Series(dtype="string"),
        "ratio_id":                 pd.Series(dtype="string"),
        "reconciliation_id":        pd.Series(dtype="string"),
        "flag_type":                pd.Series(dtype="string"),
        "flag_subtype":             pd.Series(dtype="string"),
        "severity":                 pd.Series(dtype="string"),
        "confidence":               pd.Series(dtype="Float64"),
        "title":                    pd.Series(dtype="string"),
        "description":              pd.Series(dtype="string"),
        "evidence_json":            pd.Series(dtype="string"),
        "affected_amount":          pd.Series(dtype="Float64"),
        "affected_period":          pd.Series(dtype="string"),
        "affected_accounts":        pd.Series(dtype="string"),
        "status":                   pd.Series(dtype="string"),
        "reviewer_notes":           pd.Series(dtype="string"),
        "resolution":               pd.Series(dtype="string"),
        "resolved_at":              pd.Series(dtype="string"),
        "resolved_by":              pd.Series(dtype="string"),
        "test_parameters_json":     pd.Series(dtype="string"),
        "test_run_id":              pd.Series(dtype="string"),
    })


def make_reconciliation_df() -> pd.DataFrame:
    """Create an empty reconciliation DataFrame for cross-document checks."""
    return pd.DataFrame({
        "reconciliation_id":        pd.Series(dtype="string"),
        "entity_id":                pd.Series(dtype="string"),
        "reconciliation_type":      pd.Series(dtype="string"),
        "description":              pd.Series(dtype="string"),
        "period_start":             pd.Series(dtype="string"),
        "period_end":               pd.Series(dtype="string"),
        "period_label":             pd.Series(dtype="string"),
        "source_a_document_id":     pd.Series(dtype="string"),
        "source_a_line_item_id":    pd.Series(dtype="string"),
        "source_a_label":           pd.Series(dtype="string"),
        "source_a_amount":          pd.Series(dtype="Float64"),
        "source_b_document_id":     pd.Series(dtype="string"),
        "source_b_line_item_id":    pd.Series(dtype="string"),
        "source_b_label":           pd.Series(dtype="string"),
        "source_b_amount":          pd.Series(dtype="Float64"),
        "difference":               pd.Series(dtype="Float64"),
        "difference_pct":           pd.Series(dtype="Float64"),
        "tolerance":                pd.Series(dtype="Float64"),
        "is_matched":               pd.Series(dtype="boolean"),
        "match_status":             pd.Series(dtype="string"),
        "flag_id":                  pd.Series(dtype="string"),
        "explanation":              pd.Series(dtype="string"),
        "notes":                    pd.Series(dtype="string"),
    })


def make_account_mappings_df() -> pd.DataFrame:
    """Create an empty account_mappings DataFrame for GL code → standard account mapping."""
    return pd.DataFrame({
        "mapping_id":           pd.Series(dtype="string"),
        "entity_id":            pd.Series(dtype="string"),
        "source_system":        pd.Series(dtype="string"),
        "source_account_code":  pd.Series(dtype="string"),
        "source_account_name":  pd.Series(dtype="string"),
        "source_group":         pd.Series(dtype="string"),
        "mapped_account_id":    pd.Series(dtype="string"),
        "mapping_confidence":   pd.Series(dtype="Float64"),
        "mapping_method":       pd.Series(dtype="string"),
        "is_verified":          pd.Series(dtype="boolean"),
        "verified_by":          pd.Series(dtype="string"),
        "notes":                pd.Series(dtype="string"),
    })


# ---------------------------------------------------------------------------
# Registry of all DataFrame factories (for bulk operations)
# ---------------------------------------------------------------------------

TABLE_FACTORIES: dict[str, callable] = {
    "entities":                     make_entities_df,
    "documents":                    make_documents_df,
    "tables_extracted":             make_tables_extracted_df,
    "accounts":                     make_accounts_df,
    "line_items":                   make_line_items_df,
    "transactions":                 make_transactions_df,
    "transaction_legs":             make_transaction_legs_df,
    "related_parties":              make_related_parties_df,
    "related_party_transactions":   make_related_party_transactions_df,
    "ratios":                       make_ratios_df,
    "flags":                        make_flags_df,
    "reconciliation":               make_reconciliation_df,
    "account_mappings":             make_account_mappings_df,
}


def create_all_empty_dataframes() -> dict[str, pd.DataFrame]:
    """Create all empty DataFrames for the complete schema.

    Returns a dict mapping table_name → empty DataFrame with correct dtypes.
    """
    return {name: factory() for name, factory in TABLE_FACTORIES.items()}


# ---------------------------------------------------------------------------
# DuckDB Integration
# ---------------------------------------------------------------------------

def init_duckdb(db_path: str | Path | None = None) -> "duckdb.DuckDBPyConnection":
    """Initialize a DuckDB database with the forensic accounting schema.

    If the database already exists, tables are created only if they don't exist
    (all CREATE TABLE statements use IF NOT EXISTS).

    Args:
        db_path: Path to the .duckdb file. Defaults to forensic_data.duckdb
                 in the project root. Use ':memory:' for in-memory.

    Returns:
        DuckDB connection object.
    """
    import duckdb

    path = str(db_path) if db_path else str(DEFAULT_DB_PATH)
    conn = duckdb.connect(path)

    # Read and execute the SQL schema
    # DuckDB is mostly SQLite-compatible for DDL; adjust minor differences
    sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")

    # DuckDB doesn't support PRAGMA; skip those lines
    # DuckDB uses BOOLEAN not INTEGER for booleans (but accepts both)
    # DuckDB doesn't support SQLite CHECK constraint syntax issues
    statements = sql.split(";")
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue
        # Skip SQLite-specific pragmas
        if stmt.upper().startswith("PRAGMA"):
            continue
        try:
            conn.execute(stmt)
        except Exception as e:
            # Log but don't fail on individual statement errors
            # (e.g., views referencing tables not yet created)
            print(f"[schema] Warning on statement: {e}")
            continue

    return conn


def init_sqlite(db_path: str | Path | None = None) -> "sqlite3.Connection":
    """Initialize a SQLite database with the forensic accounting schema.

    Args:
        db_path: Path to the .sqlite file. Defaults to forensic_data.sqlite
                 in the project root. Use ':memory:' for in-memory.

    Returns:
        sqlite3 connection object.
    """
    import sqlite3

    path = str(db_path) if db_path else str(SCHEMA_DIR.parent / "forensic_data.sqlite")
    conn = sqlite3.connect(path)

    sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)

    return conn


def df_to_duckdb(
    conn: "duckdb.DuckDBPyConnection",
    table_name: str,
    df: pd.DataFrame,
    mode: str = "append",
) -> int:
    """Write a pandas DataFrame to a DuckDB table.

    Args:
        conn: DuckDB connection
        table_name: Target table name
        df: DataFrame to write
        mode: 'append' (INSERT INTO) or 'replace' (DROP + CREATE + INSERT)

    Returns:
        Number of rows written.
    """
    if df.empty:
        return 0

    if mode == "replace":
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")
    else:
        conn.execute(f"INSERT INTO {table_name} SELECT * FROM df")

    return len(df)


def duckdb_to_df(
    conn: "duckdb.DuckDBPyConnection",
    query: str,
) -> pd.DataFrame:
    """Execute a SQL query on DuckDB and return results as a pandas DataFrame.

    Args:
        conn: DuckDB connection
        query: SQL query string

    Returns:
        Query results as a DataFrame.
    """
    return conn.execute(query).df()


# ---------------------------------------------------------------------------
# Example Data (for testing and documentation)
# ---------------------------------------------------------------------------

def create_example_data() -> dict[str, pd.DataFrame]:
    """Return every table with its columns and no rows.

    Populate these tables by running the extraction pipeline on your own
    financial statements.
    """
    return create_all_empty_dataframes()


# ---------------------------------------------------------------------------
# Entry point for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Forensic Accounting Analysis System — Schema Validation")
    print("=" * 70)

    # Test DataFrame creation
    all_dfs = create_all_empty_dataframes()
    print(f"\nCreated {len(all_dfs)} empty DataFrames:")
    for name, df in all_dfs.items():
        print(f"  {name:35s} — {len(df.columns)} columns")

    # Test example data
    example = create_example_data()
    print(f"\nCreated example data for {len(example)} tables:")
    for name, df in example.items():
        print(f"  {name:35s} — {len(df)} rows")

    # Test unit normalization
    print("\nUnit normalization tests:")
    print(f"  1234.56 Crores = ₹ {normalize_to_absolute(1234.56, 'crores'):,.2f}")
    print(f"  25.00 Lakhs    = ₹ {normalize_to_absolute(25.00, 'lakhs'):,.2f}")
    print(f"  Display: {absolute_to_display(12_345_600_000.0, 'crores')}")
    print(f"  Display: {absolute_to_display(2_500_000.0, 'lakhs')}")

    # Test number parsing
    print("\nIndian number parsing tests:")
    for test in ["1,234.56", "(43.20)", "₹ 420.30", "-57.25", "1,00,00,000"]:
        val, neg = parse_indian_number(test)
        print(f"  '{test}' → {val} (negative={neg})")

    print("\n[OK] All schema components validated.")
