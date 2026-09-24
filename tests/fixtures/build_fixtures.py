#!/usr/bin/env python3
"""
Build small sample documents (XLSX and PDF) for a fictional company,
Acme Widgets Private Limited, used by the test suite.

Usage:
    python tests/fixtures/build_fixtures.py [output_dir]

With no argument the files are written to user_documents/.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMPANY = "Acme Widgets Private Limited"

PNL_ROWS = [
    ("Revenue from operations", 850.00, 720.00),
    ("Other income", 12.50, 9.00),
    ("Cost of materials consumed", 410.00, 355.00),
    ("Employee benefits expense", 145.00, 128.00),
    ("Finance costs", 18.00, 21.00),
    ("Depreciation and amortisation", 32.00, 30.00),
    ("Other expenses", 120.50, 104.00),
    ("Tax expense", 34.50, 23.00),
]

BALANCE_SHEET_ROWS = [
    ("Equity share capital", 100.00, 100.00),
    ("Other equity", 412.50, 310.00),
    ("Long-term borrowings", 150.00, 180.00),
    ("Trade payables", 95.00, 88.00),
    ("Property, plant and equipment", 380.00, 365.00),
    ("Inventories", 140.00, 118.00),
    ("Trade receivables", 165.00, 140.00),
    ("Cash and cash equivalents", 72.50, 55.00),
]


def build_xlsx(path: str | Path) -> Path:
    """Write a two-sheet workbook (P&L with formulas, balance sheet)."""
    from openpyxl import Workbook

    path = Path(path)
    wb = Workbook()

    ws = wb.active
    ws.title = "Profit and Loss"
    ws["A1"] = COMPANY
    ws.merge_cells("A1:C1")
    ws["A2"] = "Statement of Profit and Loss for FY 2024-25 (Rs. lakhs)"
    ws.append([])
    ws.append(["Particulars", "FY 2024-25", "FY 2023-24"])
    first = ws.max_row + 1
    for row in PNL_ROWS:
        ws.append(list(row))
    last = ws.max_row
    ws.append([
        "Profit for the year",
        f"=B{first}+B{first + 1}-SUM(B{first + 2}:B{last})",
        f"=C{first}+C{first + 1}-SUM(C{first + 2}:C{last})",
    ])

    ws2 = wb.create_sheet("Balance Sheet")
    ws2["A1"] = COMPANY
    ws2["A2"] = "Balance Sheet as at 31 March 2025 (Rs. lakhs)"
    ws2.append([])
    ws2.append(["Particulars", "31 Mar 2025", "31 Mar 2024"])
    for row in BALANCE_SHEET_ROWS:
        ws2.append(list(row))

    wb.properties.creator = "Acme Widgets test fixtures"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_pdf(path: str | Path) -> Path:
    """Write a one-page text PDF with the P&L table."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"{COMPANY} - Profit and Loss FY 2024-25")
    c.setAuthor("Acme Widgets test fixtures")
    c.setCreator("Acme Widgets test fixtures")
    c.setSubject("Fictional sample data for testing")

    y = 800
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, COMPANY)
    y -= 20
    c.setFont("Helvetica", 11)
    c.drawString(50, y, "Statement of Profit and Loss for the year ended 31 March 2025")
    y -= 16
    c.drawString(50, y, "Fictional sample data for testing only. All amounts in Rs. lakhs.")
    y -= 30

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Particulars")
    c.drawRightString(400, y, "FY 2024-25")
    c.drawRightString(520, y, "FY 2023-24")
    y -= 18
    c.setFont("Helvetica", 11)
    for name, cur, prev in PNL_ROWS:
        c.drawString(50, y, name)
        c.drawRightString(400, y, f"{cur:,.2f}")
        c.drawRightString(520, y, f"{prev:,.2f}")
        y -= 16
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Profit for the year")
    c.drawRightString(400, y, "102.50")
    c.drawRightString(520, y, "68.00")

    c.showPage()
    c.save()
    return path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "user_documents"
    xlsx = build_xlsx(out_dir / "acme_widgets_fy2025.xlsx")
    pdf = build_pdf(out_dir / "acme_widgets_pnl_fy2025.pdf")
    print(f"Wrote {xlsx}")
    print(f"Wrote {pdf}")


if __name__ == "__main__":
    main()
