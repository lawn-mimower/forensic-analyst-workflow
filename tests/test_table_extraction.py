"""Tests for the context-aware table extractors (openpyxl, CSV, Docling, Mistral OCR)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.mistral_extractor import MistralTableExtractor, _build_page_context
from pipeline.table_extractor import TableExtractor, _detect_unit_annotation

COMPANY = "Acme Widgets Private Limited"


@pytest.mark.parametrize("text,expected", [
    ("(₹ in Lakhs)", "lakhs"),
    ("All amounts in Rs. Crores", "crores"),
    ("Figures in thousands", "thousands"),
    ("(Rs. in Millions)", "millions"),
    ("Statement of Profit and Loss", None),
])
def test_detect_unit_annotation(text, expected):
    assert _detect_unit_annotation(text) == expected


def test_excel_statements_with_merged_title_and_formulas(sample_xlsx):
    tables = TableExtractor().extract_all(sample_xlsx)

    assert [t.sheet_name for t in tables] == ["Profit and Loss", "Balance Sheet"]
    pnl, bs = tables
    assert list(pnl.df.columns) == ["Particulars", "FY 2024-25", "FY 2023-24"]
    assert pnl.df.iloc[0].tolist() == ["Revenue from operations", 850.0, 720.0]
    assert pnl.has_merged_cells and pnl.has_numeric_data
    assert pnl.metadata["formula_count"] == 2
    # merged title cells are filled across the merged range
    assert pnl.metadata["header_metadata"][0].startswith(COMPANY)
    assert pnl.extraction_method == "openpyxl"
    assert list(bs.df.columns) == ["Particulars", "31 Mar 2025", "31 Mar 2024"]
    assert bs.row_count == 8


def test_excel_unit_annotation_above_header(related_parties_xlsx):
    (table,) = TableExtractor().extract_all(related_parties_xlsx)

    assert table.metadata["source_unit"] == "lakhs"
    assert list(table.df.columns) == [
        "Name of Related Party", "Relationship", "Nature of Transaction",
        "FY 2024-25", "FY 2023-24",
    ]
    assert table.row_count == 6
    assert table.df["Name of Related Party"].iloc[0] == "Jane Doe"


def test_excel_sheet_split_into_separate_tables(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Schedules"
    ws.append(["Particulars", "Amount"])
    ws.append(["Trade receivables", 165.0])
    ws.append(["Inventories", 140.0])
    ws.append([])
    ws.append([])
    ws.append(["Borrower", "Balance"])
    ws.append(["Acme Holdings Private Limited", 150.0])
    path = tmp_path / "schedules.xlsx"
    wb.save(path)

    tables = TableExtractor().extract_all(path)

    assert [list(t.df.columns) for t in tables] == [["Particulars", "Amount"], ["Borrower", "Balance"]]
    assert [t.table_index for t in tables] == [0, 1]


def test_csv_extractor(sample_csv):
    (table,) = TableExtractor().extract_all(sample_csv)

    assert table.source_file_type == "csv"
    assert table.extraction_method == "pandas_csv"
    assert table.section_heading == "acme_widgets_trial_balance"
    assert list(table.df.columns) == ["Account", "Group", "Debit", "Credit"]
    assert table.row_count == 16 and table.has_numeric_data


def test_unsupported_and_missing_files(tmp_path):
    note = tmp_path / "notes.txt"
    note.write_text("not a table", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file type"):
        TableExtractor().extract_all(note)
    with pytest.raises(FileNotFoundError):
        TableExtractor().extract_all(tmp_path / "missing.pdf")


def test_serialisable_dict(sample_csv):
    (table,) = TableExtractor().extract_all(sample_csv)
    d = table.to_serializable_dict()
    assert d["columns"] == ["Account", "Group", "Debit", "Credit"]
    assert len(d["data_preview"]) == 5


@pytest.mark.slow
def test_docling_pdf_table(sample_pdf):
    pytest.importorskip("docling")
    tables = TableExtractor().extract_all(sample_pdf)

    assert tables
    table = tables[0]
    assert table.extraction_method == "docling"
    assert table.page_number == 1
    assert "FY 2024-25" in [str(c) for c in table.df.columns]
    assert "Revenue from operations" in table.df.iloc[:, 0].tolist()


# ---------------------------------------------------------------------------
# Mistral OCR extractor (offline: the API response is faked)
# ---------------------------------------------------------------------------
def test_mistral_requires_api_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        MistralTableExtractor()


def test_mistral_page_context():
    ctx = _build_page_context(
        "# Acme Widgets Private Limited\n\nBalance Sheet as at 31 March 2025\n\n"
        "(All amounts in Rs. lakhs)\n\n[tbl-0.html](tbl-0.html)",
        header_text="", footer_text="",
    )
    assert ctx["entity_name"] == COMPANY
    assert ctx["statement_type"] == "balance_sheet"
    assert ctx["unit"] == "lakhs"

    # A bare continuation page inherits the previous page's context
    follow = _build_page_context("[tbl-1.html](tbl-1.html)\n\n4", "", "", prev_context=ctx)
    assert follow["statement_type"] == "balance_sheet"
    assert follow["entity_name"] == COMPANY and follow["unit"] == "lakhs"


def test_mistral_response_to_tables(ocr_response):
    ex = MistralTableExtractor(api_key="test-key-not-used")
    tables = ex._response_to_tables(ocr_response, Path("acme_statements.pdf"))

    assert len(tables) == 2
    pnl, rpt = tables
    assert pnl.page_number == 0 and pnl.extraction_method == "mistral_ocr"
    assert pnl.section_heading.startswith("Statement of Profit and Loss")
    assert pnl.metadata["source_unit"] == "lakhs"
    assert pnl.metadata["statement_type"] == "profit_and_loss"
    assert pnl.metadata["entity_name"] == COMPANY
    assert list(pnl.df.columns) == ["Particulars", "Note", "FY 2024-25", "FY 2023-24"]
    assert pnl.df.iloc[0, 2] == 850.0
    # colspan in the related-party table is detected as a merged cell
    assert rpt.has_merged_cells
    assert rpt.metadata["page_footer"] == "Fictional sample data"
    assert "Related party" in rpt.surrounding_text


def test_mistral_extract_both_caches_the_api_response(offline_mistral, tmp_path):
    pdf = tmp_path / "acme_statements.pdf"
    pdf.write_bytes(b"%PDF-1.4 fictional sample")
    ex = MistralTableExtractor()

    text, tables = ex.extract_both(pdf)
    text_again = ex.extract_text(pdf)
    tables_again = ex.extract(pdf, max_pages=1)

    assert len(offline_mistral) == 1  # one upload, then served from the cache
    assert list((tmp_path / "ocr_cache").glob("*.json"))
    assert text == text_again
    assert text.count("\n\n---\n\n") == 1  # two pages
    assert len(tables) == 2 and len(tables_again) == 1
