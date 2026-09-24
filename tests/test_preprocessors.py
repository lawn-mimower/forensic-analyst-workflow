"""Tests for the file-type-aware document preprocessors."""

from __future__ import annotations

import pytest

from skills.shared.preprocessors import (
    CSVPreprocessor,
    ExcelPreprocessor,
    PreprocessingRouter,
)


async def test_csv_preprocessor(sample_csv):
    result = await CSVPreprocessor().process(str(sample_csv))

    assert result["row_count"] == 16
    text = result["text"]
    assert text.startswith("# acme_widgets_trial_balance.csv")
    assert "Debit: sum=1,517.50" in text
    assert "Credit: sum=1,517.50" in text
    assert "| Revenue from operations" in text


async def test_excel_preprocessor(sample_xlsx):
    result = await ExcelPreprocessor().process(str(sample_xlsx))

    assert result["sheet_count"] == 2
    text = result["text"]
    assert "**Company:** Acme Widgets Private Limited" in text
    assert "Sheet: Profit and Loss" in text
    assert "Sheet: Balance Sheet" in text
    assert "Revenue from operations" in text
    assert "Cash and cash equivalents" in text
    # Formula cells are listed so the knowledge graph can see how totals are derived
    assert "- Cell B13: `=B5+B6-SUM(B7:B12)`" in text
    assert "No formulas detected." in text  # balance sheet has none


async def test_router_routes_by_extension(monkeypatch, sample_csv, sample_xlsx, tmp_path):
    router = PreprocessingRouter()
    seen = []

    async def fake_docling(path):
        seen.append(path)
        return {"text": "docling", "tables": [], "pages": 1}

    monkeypatch.setattr(router._docling, "process", fake_docling)

    assert (await router.process(str(sample_csv)))["row_count"] == 16
    assert (await router.process(str(sample_xlsx)))["sheet_count"] == 2
    for name in ("statement.pdf", "notes.docx", "scan.PNG", "page.html", "readme.md"):
        assert (await router.process(str(tmp_path / name)))["text"] == "docling"
    assert len(seen) == 5

    # override forces the Excel path regardless of extension
    assert (await router.process(str(sample_xlsx), override="pandas"))["sheet_count"] == 2


async def test_router_plaintext_fallback(monkeypatch, tmp_path):
    router = PreprocessingRouter()

    async def failing_docling(path):
        raise ValueError("unsupported format")

    monkeypatch.setattr(router._docling, "process", failing_docling)

    txt = tmp_path / "ledger.txt"
    txt.write_text("Acme Widgets cash book", encoding="utf-8")
    result = await router.process(str(txt))
    assert result == {"text": "Acme Widgets cash book", "method": "plaintext"}

    missing = await router.process(str(tmp_path / "missing.xyz"))
    assert missing["text"] == "" and "unsupported format" in missing["error"]


@pytest.mark.slow
async def test_docling_markdown(sample_md):
    pytest.importorskip("docling")
    result = await PreprocessingRouter().process(str(sample_md))

    assert "Acme Widgets Private Limited" in result["text"]
    assert len(result["tables"]) == 2
    assert "Revenue from operations" in result["text"]


@pytest.mark.slow
async def test_docling_pdf(sample_pdf):
    pytest.importorskip("docling")
    result = await PreprocessingRouter().process(str(sample_pdf))

    assert result["pages"] == 1
    assert "Acme Widgets Private Limited" in result["text"]
    assert "Revenue from operations" in result["text"]
    assert "850" in result["text"]
