"""Tests for DataNormalizer: table tagging, unit/period handling and DuckDB loading."""

from __future__ import annotations

import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from pipeline.data_normalizer import (  # noqa: E402
    DataNormalizer,
    _clean_headers,
    _fiscal_year_to_dates,
    _parse_number,
    _tag_table,
)
from pipeline.table_extractor import ExtractedTable, TableExtractor  # noqa: E402

COMPANY = "Acme Widgets Private Limited"


def _table(df: pd.DataFrame, **kwargs) -> ExtractedTable:
    kwargs.setdefault("source_file", "acme.xlsx")
    kwargs.setdefault("source_file_type", "xlsx")
    return ExtractedTable(df=df, **kwargs)


@pytest.mark.parametrize("text,expected", [
    ("1,23,456.50", (123456.50, False)),
    ("(43.20)", (43.20, True)),
    ("-57.25", (57.25, True)),
    ("₹ 420.30", (420.30, False)),
    ("Rs. 1,000", (1000.0, False)),
    ("nil", (None, False)),
    ("-", (None, False)),
    ("Revenue", (None, False)),
])
def test_parse_number(text, expected):
    assert _parse_number(text) == expected


@pytest.mark.parametrize("label,expected", [
    ("FY 2024-25", ("2024-04-01", "2025-03-31")),
    ("2023-24", ("2023-04-01", "2024-03-31")),
    ("31 Mar 2025", ("2024-04-01", "2025-03-31")),
    ("As at 31.03.2024", ("2023-04-01", "2024-03-31")),
    ("March 31, 2024", ("2023-04-01", "2024-03-31")),
    ("2024-09-30", ("2024-04-01", "2025-03-31")),
    ("2025", ("2025-04-01", "2026-03-31")),
    ("n/a", ("", "")),
])
def test_fiscal_year_to_dates(label, expected):
    assert _fiscal_year_to_dates(label) == expected


def test_clean_headers_promotes_first_row_and_dedupes():
    df = pd.DataFrame([["Particulars", "Amount", "Amount"], ["Rent", 6.0, 6.0]])
    cleaned = _clean_headers(df)
    assert list(cleaned.columns) == ["Particulars", "Amount", "Amount_1"]
    assert cleaned.iloc[0].tolist() == ["Rent", 6.0, 6.0]


def test_tag_profit_and_loss():
    df = pd.DataFrame({
        "Particulars": ["Revenue from operations", "Total income"],
        "Note": ["18", ""],
        "FY 2024-25": [850.0, 862.5],
        "FY 2023-24": [720.0, 729.0],
    })
    tag = _tag_table(_table(df, section_heading="Statement of Profit and Loss (₹ in Crores)"))

    assert tag["table_type"] == "profit_and_loss"
    assert tag["reporting_unit"] == "crores"
    assert tag["reporting_period"] == "FY 2024-25"
    assert tag["column_mapping"] == {
        "Particulars": "account_name", "Note": "note_ref",
        "FY 2024-25": "FY 2024-25", "FY 2023-24": "FY 2023-24",
    }


def test_tag_balance_sheet_keeps_each_date_column():
    df = pd.DataFrame({
        "Particulars": ["Inventories", "Trade receivables"],
        "31 Mar 2025": [140.0, 165.0],
        "31 Mar 2024": [118.0, 140.0],
    })
    tag = _tag_table(_table(df, sheet_name="Balance Sheet", section_heading="Balance Sheet"))

    assert tag["table_type"] == "balance_sheet"
    assert tag["column_mapping"]["31 Mar 2025"] == "31 Mar 2025"
    assert tag["column_mapping"]["31 Mar 2024"] == "31 Mar 2024"
    assert tag["reporting_period"] == "31 Mar 2025"


def test_normalize_statements_and_related_parties(tmp_path, sample_xlsx, related_parties_xlsx):
    extractor = TableExtractor()
    tables = extractor.extract_all(sample_xlsx) + extractor.extract_all(related_parties_xlsx)
    db_path = tmp_path / "acme.duckdb"

    normalizer = DataNormalizer(db_path=db_path)
    result = normalizer.normalize_and_load(tables, entity_name=COMPANY, fiscal_year="2024-25")
    normalizer.close()

    assert result.errors == []
    assert result.source_tables_loaded == result.tables_classified == 3
    # P&L: 8 lines x 2 years (the uncomputed formula row has no values); BS: 8 x 2
    assert result.line_items_loaded == 32
    assert result.related_parties_loaded == 12
    checks = {v["check"]: v for v in result.validation_results}
    assert checks["line_item_count"]["value"] == 32
    assert checks["related_parties_count"]["value"] == 12

    con = duckdb.connect(str(db_path), read_only=True)
    types = dict(con.execute(
        "SELECT sheet_name, table_type FROM source_tables"
    ).fetchall())
    assert types == {
        "Profit and Loss": "profit_and_loss",
        "Balance Sheet": "balance_sheet",
        "Related Party Transactions": "related_party",
    }
    assert con.execute("SELECT DISTINCT entity_name FROM source_tables").fetchall() == [(COMPANY,)]

    revenue = con.execute(
        "SELECT period_label, amount, is_comparative, period_start, period_end "
        "FROM line_items WHERE account_name = 'Revenue from operations' ORDER BY period_label"
    ).fetchall()
    assert revenue == [
        ("FY 2023-24", 720.0, True, "2023-04-01", "2024-03-31"),
        ("FY 2024-25", 850.0, False, "2024-04-01", "2025-03-31"),
    ]

    inventories = con.execute(
        "SELECT period_label, amount, is_comparative, period_end FROM line_items "
        "WHERE account_name = 'Inventories' ORDER BY period_end"
    ).fetchall()
    assert inventories == [
        ("31 Mar 2024", 118.0, True, "2024-03-31"),
        ("31 Mar 2025", 140.0, False, "2025-03-31"),
    ]

    rent = con.execute(
        "SELECT relationship_category, transaction_type, amount, amount_inr, source_unit "
        "FROM related_parties WHERE party_name = 'Jane Doe' AND period_label = 'FY 2024-25'"
    ).fetchone()
    assert rent == ("Director", "Rent paid", 6.0, 600000.0, "lakhs")
    sales = con.execute(
        "SELECT amount FROM related_parties WHERE transaction_type = 'Sales' ORDER BY period_label"
    ).fetchall()
    assert sales == [(-38.0,), (-42.0,)]
    con.close()


def test_units_totals_and_brackets(tmp_path):
    df = pd.DataFrame({
        "Particulars": ["Revenue from operations", "Exceptional items", "Total income"],
        "FY 2024-25": ["8.50", "(0.25)", "8.25"],
    })
    table = _table(df, section_heading="Statement of Profit and Loss (₹ in Crores)")
    db_path = tmp_path / "units.duckdb"

    normalizer = DataNormalizer(db_path=db_path)
    result = normalizer.normalize_and_load([table], entity_name=COMPANY, fiscal_year="2024-25")
    normalizer.close()

    assert result.line_items_loaded == 3
    con = duckdb.connect(str(db_path), read_only=True)
    rows = dict((r[0], r[1:]) for r in con.execute(
        "SELECT account_name, amount, amount_inr, is_total, source_unit FROM line_items"
    ).fetchall())
    con.close()
    assert rows["Revenue from operations"] == (8.5, 85_000_000.0, False, "crores")
    assert rows["Exceptional items"] == (-0.25, -2_500_000.0, False, "crores")
    assert rows["Total income"][2] is True


def test_normalize_nothing(tmp_path):
    result = DataNormalizer(db_path=tmp_path / "empty.duckdb").normalize_and_load([])
    assert result.warnings == ["No tables provided"]
    assert result.line_items_loaded == 0


def test_initialize_schema_is_idempotent(tmp_path):
    normalizer = DataNormalizer(db_path=tmp_path / "schema.duckdb")
    normalizer.initialize_schema()
    normalizer.initialize_schema()
    tables = {r[0] for r in normalizer._get_conn().execute("SHOW TABLES").fetchall()}
    normalizer.close()
    assert tables == {"source_tables", "line_items", "related_parties", "analysis_results"}


def test_amounts_keep_full_precision(tmp_path):
    df = pd.DataFrame({
        "Particulars": ["Freight outward", "Consultancy fees"],
        "Amount": ["12,417.28", "12,34,56,789.12"],
    })
    table = _table(
        df, source_file="acme_general_ledger_fy2024-25.csv", source_file_type="csv",
        section_heading="acme_general_ledger_fy2024-25",
    )
    db_path = tmp_path / "precision.duckdb"
    normalizer = DataNormalizer(db_path=db_path)
    normalizer.normalize_and_load([table], entity_name=COMPANY, fiscal_year="2024-25")
    normalizer.close()

    con = duckdb.connect(str(db_path), read_only=True)
    amounts = dict(con.execute("SELECT account_name, amount FROM line_items").fetchall())
    periods = {r[0] for r in con.execute("SELECT period_label FROM line_items").fetchall()}
    con.close()
    assert amounts == {"Freight outward": 12417.28, "Consultancy fees": 123456789.12}
    assert periods == {"FY 2024-25"}
