"""
Document preprocessing layer — auto-routes files to the best preprocessor.

Tiered architecture:
  PDF           → MistralPreprocessor (primary) or Docling (fallback)
  DOCX/PPTX/images → Docling (with OCR fallback)
  XLSX/XLSM     → openpyxl + pandas (complex workbook support)
  CSV           → pandas (fast, direct)
  HTML/MD       → Docling (native support)

Usage:
    from skills.shared.preprocessors import PreprocessingRouter
    router = PreprocessingRouter()
    result = await router.process("document.pdf")
    # result["text"] → markdown text ready for RAG indexing
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docling Preprocessor (PDF, DOCX, PPTX, images, HTML, MD, CSV)
# ---------------------------------------------------------------------------
class DoclingPreprocessor:
    """Primary preprocessor for PDF, DOCX, PPTX, images using Docling.

    Configures OCR and table structure recognition for financial documents.
    Falls back to RapidOCR if Docling output is too short (likely a pure scan).
    """

    _converter = None

    def _get_converter(self):
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            try:
                from docling.datamodel.pipeline_options import (
                    PdfPipelineOptions,
                    EasyOcrOptions,
                    TableStructureOptions,
                    TableFormerMode,
                )
                from docling.datamodel.base_models import InputFormat
                from docling.document_converter import PdfFormatOption

                pipeline_options = PdfPipelineOptions(
                    do_ocr=True,
                    do_table_structure=True,
                    ocr_options=EasyOcrOptions(
                        lang=["en", "hi"],
                        force_full_page_ocr=False,
                    ),
                    table_structure_options=TableStructureOptions(
                        mode=TableFormerMode.ACCURATE,
                    ),
                )
                self.__class__._converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=pipeline_options,
                        ),
                    }
                )
            except (ImportError, AttributeError):
                # Docling version without pipeline options — use bare converter
                logger.info("Docling pipeline options not available, using default converter")
                self.__class__._converter = DocumentConverter()

        return self._converter

    async def process(self, file_path: str) -> dict:
        """Convert document to markdown using Docling.

        Returns:
            dict with keys: text, tables (list of DataFrames), pages (int)
        """
        converter = self._get_converter()
        result = converter.convert(file_path)
        markdown = result.document.export_to_markdown()

        # Extract tables as DataFrames if available
        tables = []
        try:
            for table in result.document.tables:
                df = table.export_to_dataframe(doc=result.document)
                tables.append(df)
        except (AttributeError, TypeError):
            pass

        # Quality gate: if output is too short, likely a pure scan that failed
        if len(markdown.strip()) < 50:
            fallback_text = await self._fallback_ocr(file_path)
            if fallback_text:
                markdown = fallback_text

        page_count = len(result.pages) if hasattr(result, "pages") else 0

        return {"text": markdown, "tables": tables, "pages": page_count}

    async def _fallback_ocr(self, file_path: str) -> str | None:
        """Tier 2: RapidOCR fallback for failed Docling extractions."""
        try:
            from rapidocr_onnxruntime import RapidOCR

            ocr = RapidOCR()
            result, _ = ocr(file_path)
            if result:
                return "\n".join(line[1] for line in result)
        except ImportError:
            logger.debug("RapidOCR not installed, skipping OCR fallback")
        except Exception as e:
            logger.warning(f"RapidOCR fallback failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Mistral OCR Preprocessor (primary for PDFs)
# ---------------------------------------------------------------------------
class MistralPreprocessor:
    """PDF preprocessor using Mistral OCR.

    Uses ``MistralTableExtractor.extract_text()`` for full-page markdown and
    ``extract()`` for structured table DataFrames — same single API call
    (cached) produces both outputs.
    """

    _extractor = None

    def _get_extractor(self):
        if self._extractor is None:
            from pipeline.mistral_extractor import MistralTableExtractor
            self.__class__._extractor = MistralTableExtractor()
        return self._extractor

    async def process(self, file_path: str) -> dict:
        """Convert PDF to markdown using Mistral OCR.

        Returns:
            dict with keys: text (str), tables (list of DataFrames), pages (int)
        """
        ext = self._get_extractor()

        # Single API call / cache hit produces both text and tables
        text, extracted_tables = ext.extract_both(file_path)

        tables = [et.df for et in extracted_tables]
        # Count pages from the text (pages separated by ---)
        page_count = text.count("\n\n---\n\n") + 1 if text.strip() else 0

        return {"text": text, "tables": tables, "pages": page_count}


# ---------------------------------------------------------------------------
# Excel Preprocessor (openpyxl + pandas)
# ---------------------------------------------------------------------------
class ExcelPreprocessor:
    """Complex workbook preprocessor using openpyxl + pandas.

    Produces hybrid text: metadata header + NL summary + markdown table.
    This format is optimized for LightRAG's entity extraction (1200 token chunks).
    """

    async def process(self, file_path: str) -> dict:
        """Extract all sheets with metadata, summaries, and formula info.

        Returns:
            dict with keys: text (str), sheet_count (int)
        """
        from openpyxl import load_workbook
        import pandas as pd

        wb = load_workbook(file_path, data_only=True)
        sheets_text: list[str] = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]

            # 1. Extract metadata (company name, period from top rows)
            metadata = self._extract_metadata(ws)

            # 2. Handle merged cells → DataFrame
            df = self._sheet_to_dataframe(ws)
            if df.empty:
                continue

            # 3. Generate NL summary for entity extraction
            summary = self._generate_summary(df, metadata)

            # 4. Markdown table for precise retrieval
            table_md = df.to_markdown(index=False)

            # 5. Detect and describe formulas
            formulas = self._extract_formulas(file_path, sheet_name)

            sheets_text.append(
                f"# {metadata.get('doc_type', sheet_name)}\n"
                f"**Source:** {Path(file_path).name}, Sheet: {sheet_name}\n"
                f"**Company:** {metadata.get('company', 'Unknown')}\n\n"
                f"## Summary\n{summary}\n\n"
                f"## Data\n{table_md}\n\n"
                f"## Formulas\n{formulas}\n"
            )

        wb.close()
        return {
            "text": "\n\n---\n\n".join(sheets_text),
            "sheet_count": len(wb.sheetnames),
        }

    def _extract_metadata(self, ws) -> dict:
        """Read company name, period, doc type from top rows."""
        metadata: dict[str, str] = {}
        # Scan first 5 rows for metadata clues
        for row in ws.iter_rows(min_row=1, max_row=min(5, ws.max_row or 1), values_only=True):
            for cell_val in row:
                if cell_val is None:
                    continue
                text = str(cell_val).strip()
                if not text:
                    continue
                text_lower = text.lower()

                # Detect company name (typically the longest string in first rows)
                if len(text) > 10 and "company" not in metadata:
                    if any(kw in text_lower for kw in ("pvt", "ltd", "private", "limited", "llp", "inc")):
                        metadata["company"] = text

                # Detect period (FY, year, quarter references)
                if any(kw in text_lower for kw in ("fy", "year", "quarter", "period", "20")):
                    if "period" not in metadata:
                        metadata["period"] = text

                # Detect document type
                if any(kw in text_lower for kw in (
                    "profit", "loss", "balance sheet", "cash flow",
                    "trial balance", "ledger", "journal",
                )):
                    metadata["doc_type"] = text

        return metadata

    def _sheet_to_dataframe(self, ws) -> "Any":
        """Convert sheet to DataFrame, resolving merged cells."""
        import pandas as pd

        data: list[list] = []
        merged_ranges = list(ws.merged_cells.ranges)

        for row in ws.iter_rows():
            row_data: list = []
            for cell in row:
                value = cell.value
                # Check if this cell is part of a merged range
                if value is None:
                    for mr in merged_ranges:
                        if cell.coordinate in mr:
                            # Get value from the top-left cell of the merged range
                            value = ws.cell(row=mr.min_row, column=mr.min_col).value
                            break
                row_data.append(value)
            data.append(row_data)

        if not data:
            return pd.DataFrame()

        # Use first non-empty row as headers
        header_idx = 0
        for i, row in enumerate(data):
            if any(v is not None for v in row):
                header_idx = i
                break

        headers = [str(v) if v is not None else f"Col_{j}" for j, v in enumerate(data[header_idx])]
        rows = data[header_idx + 1:]

        df = pd.DataFrame(rows, columns=headers)
        # Drop fully empty rows
        df = df.dropna(how="all")
        return df

    def _generate_summary(self, df: "Any", metadata: dict) -> str:
        """Generate a natural language summary for entity extraction."""
        import pandas as pd

        lines: list[str] = []
        company = metadata.get("company", "The entity")
        period = metadata.get("period", "")
        doc_type = metadata.get("doc_type", "financial statement")

        lines.append(f"This is the {doc_type} of {company}")
        if period:
            lines.append(f"for the period {period}.")
        else:
            lines.append(".")

        lines.append(f"The document contains {len(df)} rows and {len(df.columns)} columns.")

        # Identify numeric columns and summarize
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            for col in numeric_cols[:5]:  # Limit to first 5
                total = df[col].sum()
                if total != 0:
                    lines.append(f"Total {col}: {total:,.2f}")

        return " ".join(lines)

    def _extract_formulas(self, file_path: str, sheet_name: str) -> str:
        """Load with data_only=False, describe formulas as NL text."""
        from openpyxl import load_workbook

        wb_f = load_workbook(file_path, data_only=False)
        ws_f = wb_f[sheet_name]
        formulas: list[str] = []

        for row in ws_f.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formulas.append(f"- Cell {cell.coordinate}: `{cell.value}`")

        wb_f.close()
        return "\n".join(formulas) if formulas else "No formulas detected."


# ---------------------------------------------------------------------------
# CSV Preprocessor
# ---------------------------------------------------------------------------
class CSVPreprocessor:
    """Fast CSV preprocessor using pandas."""

    async def process(self, file_path: str) -> dict:
        import pandas as pd

        try:
            df = pd.read_csv(file_path, engine="pyarrow")
        except (ImportError, Exception):
            df = pd.read_csv(file_path)

        text_parts: list[str] = []
        text_parts.append(f"# {Path(file_path).name}\n")
        text_parts.append(f"**Rows:** {len(df)}, **Columns:** {len(df.columns)}\n")

        # Summary of numeric columns
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            text_parts.append("## Summary")
            for col in numeric_cols[:10]:
                text_parts.append(f"- {col}: sum={df[col].sum():,.2f}, mean={df[col].mean():,.2f}")
            text_parts.append("")

        # Full markdown table (truncate large files)
        if len(df) > 500:
            text_parts.append("## Data (first 500 rows)")
            text_parts.append(df.head(500).to_markdown(index=False))
        else:
            text_parts.append("## Data")
            text_parts.append(df.to_markdown(index=False))

        return {"text": "\n".join(text_parts), "row_count": len(df)}


# ---------------------------------------------------------------------------
# Preprocessing Router
# ---------------------------------------------------------------------------
class PreprocessingRouter:
    """Routes files to the appropriate preprocessor based on type.

    Parameters
    ----------
    pdf_backend : str
        "mistral" (default, uses Mistral OCR) or "docling".
    """

    DOCLING_EXTENSIONS = {".docx", ".pptx", ".html", ".md"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
    EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
    CSV_EXTENSIONS = {".csv", ".tsv"}

    def __init__(self, pdf_backend: str = "mistral"):
        self._pdf_backend = pdf_backend
        self._mistral: MistralPreprocessor | None = None
        self._docling: DoclingPreprocessor | None = None
        self._excel = ExcelPreprocessor()
        self._csv = CSVPreprocessor()

    def _get_pdf_processor(self):
        """Lazy-init the PDF processor based on configured backend."""
        if self._pdf_backend == "mistral":
            if self._mistral is None:
                self._mistral = MistralPreprocessor()
            return self._mistral
        else:
            if self._docling is None:
                self._docling = DoclingPreprocessor()
            return self._docling

    def _get_docling(self):
        """Lazy-init Docling for non-PDF document types."""
        if self._docling is None:
            self._docling = DoclingPreprocessor()
        return self._docling

    async def process(self, file_path: str, *, override: str | None = None) -> dict:
        """Route file to the best preprocessor.

        Args:
            file_path: Path to the document.
            override: Force a specific preprocessor ('docling', 'mistral', 'pandas', 'paddleocr').

        Returns:
            dict with at minimum a "text" key containing extracted content.
        """
        ext = Path(file_path).suffix.lower()

        if override == "pandas":
            return await self._excel.process(file_path)
        if override == "docling":
            return await self._get_docling().process(file_path)
        if override == "mistral":
            if self._mistral is None:
                self._mistral = MistralPreprocessor()
            return await self._mistral.process(file_path)
        if override == "paddleocr":
            text = await self._get_docling()._fallback_ocr(file_path)
            return {"text": text or "", "method": "paddleocr"}

        if ext in self.EXCEL_EXTENSIONS:
            return await self._excel.process(file_path)
        elif ext in self.CSV_EXTENSIONS:
            return await self._csv.process(file_path)
        elif ext == ".pdf":
            # PDFs go through configured backend (Mistral by default)
            return await self._get_pdf_processor().process(file_path)
        elif ext in self.DOCLING_EXTENSIONS | self.IMAGE_EXTENSIONS:
            return await self._get_docling().process(file_path)
        else:
            # Fallback: try Docling (it handles many formats)
            try:
                return await self._get_docling().process(file_path)
            except Exception as e:
                logger.warning(f"Docling failed for {file_path}: {e}")
                # Last resort: read as plain text
                try:
                    text = Path(file_path).read_text(encoding="utf-8")
                    return {"text": text, "method": "plaintext"}
                except Exception:
                    return {"text": "", "error": str(e)}
