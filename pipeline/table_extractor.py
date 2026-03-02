"""
Context-aware table extraction for forensic accounting documents.

Extracts numeric tables from PDF, DOCX, Excel (XLSX/XLS), and CSV files,
preserving surrounding context (section headings, page numbers, bounding boxes)
as metadata on each extracted DataFrame.

Usage:
    from pipeline.table_extractor import TableExtractor

    extractor = TableExtractor()
    results = extractor.extract_all("path/to/document.pdf")
    for table in results:
        print(table.section_heading, table.df.shape)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Regex patterns for detecting Indian currency unit annotations in headers
# ---------------------------------------------------------------------------
_UNIT_PATTERN = re.compile(
    r"in\s+(?:Rs\.?\s*)?(?:₹\s*)?(Lakhs?|Crores?|Thousands?|Millions?|Billions?|Absolute)",
    re.IGNORECASE,
)

# Pattern for footnote markers at the bottom of a table row
_FOOTNOTE_PATTERN = re.compile(
    r"^\s*[\*†‡§\d]+[\.\)]\s*|^\s*\(\s*[a-z]\s*\)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# ExtractedTable data class
# ---------------------------------------------------------------------------
@dataclass
class ExtractedTable:
    """A single table extracted from a document, with full provenance metadata."""

    df: pd.DataFrame
    source_file: str
    source_file_type: str              # "pdf", "docx", "xlsx", "csv"
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    section_heading: Optional[str] = None
    section_hierarchy: list[str] = field(default_factory=list)
    table_index: int = 0
    bbox: Optional[str] = None
    surrounding_text: Optional[str] = None
    raw_cell_text: Optional[str] = None
    extraction_method: str = ""
    extraction_confidence: Optional[float] = None
    row_count: int = 0
    col_count: int = 0
    has_merged_cells: bool = False
    has_numeric_data: bool = False
    metadata: dict = field(default_factory=dict)

    def to_serializable_dict(self) -> dict:
        """Return a JSON-serializable dictionary (DataFrame becomes records list)."""
        d = {
            "source_file": self.source_file,
            "source_file_type": self.source_file_type,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "section_heading": self.section_heading,
            "section_hierarchy": self.section_hierarchy,
            "table_index": self.table_index,
            "bbox": self.bbox,
            "surrounding_text": self.surrounding_text,
            "raw_cell_text": self.raw_cell_text,
            "extraction_method": self.extraction_method,
            "extraction_confidence": self.extraction_confidence,
            "row_count": self.row_count,
            "col_count": self.col_count,
            "has_merged_cells": self.has_merged_cells,
            "has_numeric_data": self.has_numeric_data,
            "metadata": self.metadata,
            "columns": list(self.df.columns),
            "data_preview": self.df.head(5).to_dict(orient="records"),
        }
        return d


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _detect_unit_annotation(text: str) -> Optional[str]:
    """Extract unit annotation like '(in Lakhs)' or '(Rs. in Crores)' from text.

    Returns the normalized unit string (e.g. 'lakhs', 'crores') or None.
    """
    match = _UNIT_PATTERN.search(text)
    if match:
        raw = match.group(1).lower().rstrip("s")
        # Normalize
        mapping = {
            "lakh": "lakhs",
            "crore": "crores",
            "thousand": "thousands",
            "million": "millions",
            "billion": "billions",
            "absolute": "absolute",
        }
        return mapping.get(raw, raw + "s")
    return None


def _is_footnote_row(row_values: list) -> bool:
    """Check whether a row looks like a footnote (starts with *, number superscript, etc.)."""
    first_val = str(row_values[0]).strip() if row_values and row_values[0] is not None else ""
    if not first_val:
        return False
    return bool(_FOOTNOTE_PATTERN.match(first_val))


def _check_has_numeric(df: pd.DataFrame) -> bool:
    """Return True if any column in the DataFrame contains numeric values."""
    for col in df.columns:
        try:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().any():
                return True
        except (ValueError, TypeError):
            continue
    return False


def _detect_merged_cells_in_df(df: pd.DataFrame) -> bool:
    """Heuristic: detect merged cells by looking for NaN runs in leftmost columns.

    If the first column has stretches of NaN followed by data, it's likely
    the result of merged cells that weren't properly filled.
    """
    if df.empty or len(df) < 3:
        return False
    first_col = df.iloc[:, 0]
    # Check for runs of consecutive NaNs longer than 1
    is_null = first_col.isna()
    run_lengths = []
    current_run = 0
    for v in is_null:
        if v:
            current_run += 1
        else:
            if current_run > 0:
                run_lengths.append(current_run)
            current_run = 0
    if current_run > 0:
        run_lengths.append(current_run)
    return any(r >= 2 for r in run_lengths)


# ---------------------------------------------------------------------------
# Docling-based extractor (PDF, DOCX)
# ---------------------------------------------------------------------------

class _DoclingExtractor:
    """Extract tables from PDF and DOCX using Docling with OCR support."""

    _converter = None

    def _get_converter(self):
        """Lazy-init the Docling converter (shared across calls)."""
        if _DoclingExtractor._converter is not None:
            return _DoclingExtractor._converter

        from docling.document_converter import DocumentConverter

        try:
            from docling.datamodel.pipeline_options import (
                PdfPipelineOptions,
                RapidOcrOptions,
                TableStructureOptions,
                TableFormerMode,
            )
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import PdfFormatOption

            pipeline_options = PdfPipelineOptions(
                do_ocr=True,
                do_table_structure=True,
                ocr_options=RapidOcrOptions(
                    lang=["english"],
                    force_full_page_ocr=False,
                ),
                table_structure_options=TableStructureOptions(
                    mode=TableFormerMode.ACCURATE,
                ),
                images_scale=2.0,
            )
            _DoclingExtractor._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options,
                    ),
                }
            )
        except (ImportError, AttributeError) as exc:
            logger.info(
                "Docling pipeline options not fully available (%s), using default converter",
                exc,
            )
            _DoclingExtractor._converter = DocumentConverter()

        return _DoclingExtractor._converter

    def extract(self, file_path: Path) -> list[ExtractedTable]:
        """Extract all tables from a PDF or DOCX file.

        Returns a list of ExtractedTable objects with full provenance metadata.
        """
        converter = self._get_converter()
        file_str = str(file_path)
        source_type = file_path.suffix.lower().lstrip(".")

        logger.info("Docling converting: %s", file_path.name)
        result = converter.convert(file_str)
        doc = result.document

        # ---------------------------------------------------------------
        # Build a text index for surrounding-text lookup:
        # Collect all text items with their provenance positions.
        # ---------------------------------------------------------------
        text_items = self._collect_text_items(doc)

        # Build section hierarchy map from the document structure
        section_map = self._build_section_map(doc)

        # ---------------------------------------------------------------
        # Extract each table
        # ---------------------------------------------------------------
        extracted: list[ExtractedTable] = []
        tables = list(getattr(doc, "tables", []) or [])
        logger.info("Found %d tables in %s", len(tables), file_path.name)

        for idx, table in enumerate(tables):
            try:
                et = self._process_one_table(
                    table, doc, idx, file_path, source_type,
                    text_items, section_map,
                )
                if et is not None:
                    extracted.append(et)
            except Exception as exc:
                logger.warning(
                    "Failed to extract table %d from %s: %s",
                    idx, file_path.name, exc,
                    exc_info=True,
                )

        # ---------------------------------------------------------------
        # Cross-page table merging: if consecutive tables have matching
        # column counts and the second lacks a proper header row, merge.
        # ---------------------------------------------------------------
        extracted = self._merge_cross_page_tables(extracted)

        return extracted

    # -- internal helpers --------------------------------------------------

    def _process_one_table(
        self,
        table,
        doc,
        idx: int,
        file_path: Path,
        source_type: str,
        text_items: list[dict],
        section_map: dict,
    ) -> Optional[ExtractedTable]:
        """Process a single Docling table element into an ExtractedTable."""

        # Export to DataFrame
        try:
            df = table.export_to_dataframe(doc=doc)
        except Exception:
            # Fallback: some Docling versions use different API
            try:
                df = table.export_to_dataframe()
            except Exception as exc:
                logger.warning("Cannot export table %d to DataFrame: %s", idx, exc)
                return None

        if df is None or df.empty:
            logger.debug("Table %d is empty, skipping", idx)
            return None

        # Page number and bounding box
        page_no = None
        bbox_str = None
        try:
            prov = table.prov
            if prov and len(prov) > 0:
                page_no = getattr(prov[0], "page_no", None)
                bbox_obj = getattr(prov[0], "bbox", None)
                if bbox_obj is not None:
                    # bbox might be an object with l, t, r, b or a tuple
                    if hasattr(bbox_obj, "l"):
                        bbox_str = json.dumps({
                            "l": bbox_obj.l, "t": bbox_obj.t,
                            "r": bbox_obj.r, "b": bbox_obj.b,
                        })
                    elif hasattr(bbox_obj, "__iter__"):
                        bbox_str = json.dumps(list(bbox_obj))
                    else:
                        bbox_str = str(bbox_obj)
        except (AttributeError, IndexError, TypeError):
            pass

        # Section heading — walk the section_map
        section_heading, section_hierarchy = self._find_section_for_table(
            table, doc, section_map, page_no
        )

        # Surrounding text
        surrounding = self._get_surrounding_text(text_items, page_no, idx)

        # Raw header text (first row of the raw table for audit trail)
        raw_cell_text = " | ".join(str(c) for c in df.columns)

        # Detect unit annotation in heading or column headers
        unit_annotation = None
        search_texts = [raw_cell_text, section_heading or ""]
        for st in search_texts:
            unit_annotation = _detect_unit_annotation(st)
            if unit_annotation:
                break

        # Detect footnote rows and separate them
        footnote_rows = []
        data_mask = []
        for row_idx in range(len(df)):
            row_vals = df.iloc[row_idx].tolist()
            if _is_footnote_row(row_vals):
                footnote_rows.append(" | ".join(str(v) for v in row_vals if v is not None))
                data_mask.append(False)
            else:
                data_mask.append(True)
        if footnote_rows and not all(data_mask):
            df = df.loc[data_mask].reset_index(drop=True)

        has_merged = _detect_merged_cells_in_df(df)
        has_numeric = _check_has_numeric(df)

        metadata = {}
        if unit_annotation:
            metadata["source_unit"] = unit_annotation
        if footnote_rows:
            metadata["footnotes"] = footnote_rows

        return ExtractedTable(
            df=df,
            source_file=str(file_path),
            source_file_type=source_type,
            page_number=page_no,
            sheet_name=None,
            section_heading=section_heading,
            section_hierarchy=section_hierarchy,
            table_index=idx,
            bbox=bbox_str,
            surrounding_text=surrounding,
            raw_cell_text=raw_cell_text,
            extraction_method="docling",
            extraction_confidence=None,
            row_count=len(df),
            col_count=len(df.columns),
            has_merged_cells=has_merged,
            has_numeric_data=has_numeric,
            metadata=metadata,
        )

    def _collect_text_items(self, doc) -> list[dict]:
        """Collect all text elements with page numbers from a DoclingDocument.

        Returns a list of dicts: {"text": ..., "page_no": ..., "type": ...}
        """
        items = []
        # Try different Docling API surfaces for iterating text elements
        try:
            # Docling v2 API: iterate over all document elements
            if hasattr(doc, "texts"):
                for text_item in doc.texts:
                    text = getattr(text_item, "text", None) or str(text_item)
                    page_no = None
                    prov = getattr(text_item, "prov", None)
                    if prov and len(prov) > 0:
                        page_no = getattr(prov[0], "page_no", None)
                    item_type = type(text_item).__name__
                    items.append({"text": text, "page_no": page_no, "type": item_type})
        except Exception as exc:
            logger.debug("Could not collect text items: %s", exc)

        # Fallback: try body / main_text
        if not items:
            try:
                main_text = getattr(doc, "body", None) or getattr(doc, "main_text", None)
                if main_text and hasattr(main_text, "__iter__"):
                    for elem in main_text:
                        text = getattr(elem, "text", None) or str(elem)
                        page_no = None
                        prov = getattr(elem, "prov", None)
                        if prov and len(prov) > 0:
                            page_no = getattr(prov[0], "page_no", None)
                        items.append({
                            "text": text,
                            "page_no": page_no,
                            "type": type(elem).__name__,
                        })
            except Exception as exc:
                logger.debug("Fallback text collection failed: %s", exc)

        return items

    def _build_section_map(self, doc) -> dict:
        """Build a mapping of page_no -> list of section headings on that page.

        Also keeps a global ordered list of (page_no, heading_text, level) for
        hierarchy reconstruction.
        """
        sections: dict = {"by_page": {}, "ordered": []}
        try:
            # Docling v2: doc.texts includes SectionHeaderItem
            if hasattr(doc, "texts"):
                for item in doc.texts:
                    type_name = type(item).__name__
                    if "header" in type_name.lower() or "heading" in type_name.lower():
                        text = getattr(item, "text", str(item))
                        page_no = None
                        level = getattr(item, "level", 1)
                        prov = getattr(item, "prov", None)
                        if prov and len(prov) > 0:
                            page_no = getattr(prov[0], "page_no", None)
                        entry = {"text": text, "page_no": page_no, "level": level}
                        sections["ordered"].append(entry)
                        if page_no is not None:
                            sections["by_page"].setdefault(page_no, []).append(entry)
        except Exception as exc:
            logger.debug("Could not build section map: %s", exc)

        # Fallback: extract headings from main_text / body
        if not sections["ordered"]:
            try:
                main_text = getattr(doc, "body", None) or getattr(doc, "main_text", None)
                if main_text and hasattr(main_text, "__iter__"):
                    for elem in main_text:
                        type_name = type(elem).__name__
                        if "header" in type_name.lower() or "heading" in type_name.lower():
                            text = getattr(elem, "text", str(elem))
                            page_no = None
                            level = getattr(elem, "level", 1)
                            prov = getattr(elem, "prov", None)
                            if prov and len(prov) > 0:
                                page_no = getattr(prov[0], "page_no", None)
                            entry = {"text": text, "page_no": page_no, "level": level}
                            sections["ordered"].append(entry)
                            if page_no is not None:
                                sections["by_page"].setdefault(page_no, []).append(entry)
            except Exception as exc:
                logger.debug("Fallback section map build failed: %s", exc)

        return sections

    def _find_section_for_table(
        self, table, doc, section_map: dict, page_no: Optional[int]
    ) -> tuple[Optional[str], list[str]]:
        """Find the nearest section heading for a table.

        Walks backward through the ordered section list to find the most recent
        heading that appears on or before the table's page.

        Returns (heading_text, [hierarchy_list]).
        """
        ordered = section_map.get("ordered", [])
        if not ordered:
            return None, []

        # Find the last heading that is on a page <= table's page
        nearest = None
        if page_no is not None:
            for entry in reversed(ordered):
                entry_page = entry.get("page_no")
                if entry_page is not None and entry_page <= page_no:
                    nearest = entry
                    break

        if nearest is None and ordered:
            # Fallback: use the very first heading
            nearest = ordered[0]

        if nearest is None:
            return None, []

        heading_text = nearest["text"]

        # Build hierarchy: collect all headings up to this point,
        # keeping only the most recent heading at each level.
        hierarchy: dict[int, str] = {}
        target_page = nearest.get("page_no", 0) or 0
        for entry in ordered:
            ep = entry.get("page_no", 0) or 0
            if ep > target_page:
                break
            level = entry.get("level", 1)
            # When we see a heading at level N, clear all levels > N
            keys_to_remove = [k for k in hierarchy if k > level]
            for k in keys_to_remove:
                del hierarchy[k]
            hierarchy[level] = entry["text"]

        # Sort by level and return as a list
        hierarchy_list = [hierarchy[k] for k in sorted(hierarchy.keys())]

        return heading_text, hierarchy_list

    def _get_surrounding_text(
        self, text_items: list[dict], page_no: Optional[int], table_idx: int
    ) -> Optional[str]:
        """Get ~100 characters of text before and after the table position.

        Uses page number to locate relevant text items.
        """
        if not text_items or page_no is None:
            return None

        # Collect text on the same page
        page_texts = [
            item["text"]
            for item in text_items
            if item.get("page_no") == page_no and item.get("text")
        ]

        if not page_texts:
            return None

        combined = " ".join(page_texts)
        # Return first and last 100 chars as "surrounding context"
        before = combined[:100].strip()
        after = combined[-100:].strip() if len(combined) > 100 else ""
        parts = []
        if before:
            parts.append(f"[BEFORE] {before}")
        if after:
            parts.append(f"[AFTER] {after}")
        return " ... ".join(parts) if parts else None

    def _merge_cross_page_tables(
        self, tables: list[ExtractedTable]
    ) -> list[ExtractedTable]:
        """Merge consecutive tables that appear to span across pages.

        Heuristic: two consecutive tables are candidates for merging if:
        1. They are on consecutive pages
        2. They have the same number of columns
        3. The second table's first data row does NOT look like a header
           (i.e., it contains numeric values, not just text labels)
        """
        if len(tables) < 2:
            return tables

        merged: list[ExtractedTable] = []
        skip_next = False

        for i in range(len(tables)):
            if skip_next:
                skip_next = False
                continue

            current = tables[i]

            if i + 1 < len(tables):
                nxt = tables[i + 1]
                if self._should_merge(current, nxt):
                    logger.info(
                        "Merging cross-page tables: table %d (page %s) + table %d (page %s)",
                        current.table_index, current.page_number,
                        nxt.table_index, nxt.page_number,
                    )
                    merged_et = self._do_merge(current, nxt)
                    merged.append(merged_et)
                    skip_next = True
                    continue

            merged.append(current)

        return merged

    def _should_merge(self, t1: ExtractedTable, t2: ExtractedTable) -> bool:
        """Decide whether two tables should be merged as a cross-page continuation."""
        # Must be on consecutive pages
        if t1.page_number is None or t2.page_number is None:
            return False
        if t2.page_number != t1.page_number + 1:
            return False

        # Must have the same number of columns
        if t1.col_count != t2.col_count:
            return False

        # The second table's header row should look like data, not labels
        # Check if the column names of t2 contain numeric-like values
        t2_cols = list(t2.df.columns)
        numeric_header_count = 0
        for col in t2_cols:
            try:
                pd.to_numeric(str(col).replace(",", "").replace("(", "-").replace(")", ""))
                numeric_header_count += 1
            except (ValueError, TypeError):
                pass

        # If more than half the "header" cells look numeric, it's likely a continuation
        if numeric_header_count > len(t2_cols) / 2:
            return True

        # Also check: if the column names of t2 match the column names of t1, it's a
        # separate table (not a continuation)
        if list(t1.df.columns) == t2_cols:
            return False

        return False

    def _do_merge(self, t1: ExtractedTable, t2: ExtractedTable) -> ExtractedTable:
        """Merge two tables: append t2's data rows under t1."""
        # The second table's "columns" are actually data, so we need to
        # add them as a row first, then append the rest
        header_as_row = pd.DataFrame([list(t2.df.columns)], columns=t1.df.columns)
        combined_df = pd.concat(
            [t1.df, header_as_row, t2.df.set_axis(t1.df.columns, axis=1)],
            ignore_index=True,
        )

        pages = []
        if t1.page_number is not None:
            pages.append(t1.page_number)
        if t2.page_number is not None:
            pages.append(t2.page_number)

        meta = dict(t1.metadata)
        meta["merged_from_pages"] = pages
        meta.update({k: v for k, v in t2.metadata.items() if k not in meta})

        return ExtractedTable(
            df=combined_df,
            source_file=t1.source_file,
            source_file_type=t1.source_file_type,
            page_number=t1.page_number,
            sheet_name=None,
            section_heading=t1.section_heading,
            section_hierarchy=t1.section_hierarchy,
            table_index=t1.table_index,
            bbox=t1.bbox,
            surrounding_text=t1.surrounding_text,
            raw_cell_text=t1.raw_cell_text,
            extraction_method=t1.extraction_method,
            extraction_confidence=t1.extraction_confidence,
            row_count=len(combined_df),
            col_count=len(combined_df.columns),
            has_merged_cells=t1.has_merged_cells or t2.has_merged_cells,
            has_numeric_data=t1.has_numeric_data or t2.has_numeric_data,
            metadata=meta,
        )


# ---------------------------------------------------------------------------
# Excel extractor (openpyxl)
# ---------------------------------------------------------------------------

class _ExcelExtractor:
    """Extract tables from XLSX/XLS files using openpyxl."""

    def extract(self, file_path: Path) -> list[ExtractedTable]:
        """Extract all tables from all sheets of an Excel workbook."""
        from openpyxl import load_workbook

        source_type = file_path.suffix.lower().lstrip(".")
        extracted: list[ExtractedTable] = []
        global_table_idx = 0

        # Load with data_only=True to get computed values
        try:
            wb = load_workbook(str(file_path), data_only=True)
        except Exception as exc:
            logger.error("Cannot open workbook %s: %s", file_path.name, exc)
            return []

        # Also load with data_only=False to capture formulas
        wb_formulas = None
        try:
            wb_formulas = load_workbook(str(file_path), data_only=False)
        except Exception as exc:
            logger.debug("Cannot open workbook for formulas: %s", exc)

        for sheet_idx, sheet_name in enumerate(wb.sheetnames):
            try:
                ws = wb[sheet_name]
                ws_formulas = wb_formulas[sheet_name] if wb_formulas else None

                tables = self._extract_from_sheet(
                    ws, ws_formulas, file_path, source_type,
                    sheet_idx, sheet_name, global_table_idx,
                )
                for t in tables:
                    extracted.append(t)
                    global_table_idx += 1
            except Exception as exc:
                logger.warning(
                    "Failed to process sheet '%s' in %s: %s",
                    sheet_name, file_path.name, exc,
                    exc_info=True,
                )

        wb.close()
        if wb_formulas:
            wb_formulas.close()

        return extracted

    def _extract_from_sheet(
        self,
        ws,
        ws_formulas,
        file_path: Path,
        source_type: str,
        sheet_idx: int,
        sheet_name: str,
        global_idx_start: int,
    ) -> list[ExtractedTable]:
        """Extract one or more tables from a single worksheet.

        Handles merged cells, multiple tables separated by empty rows,
        and header detection.
        """
        # Check for merged cells
        merged_ranges = list(ws.merged_cells.ranges)
        has_merged = len(merged_ranges) > 0

        # Read all data, resolving merged cells
        all_data = self._read_sheet_data(ws, merged_ranges)
        if not all_data:
            return []

        # Detect unit annotation from the first few rows
        unit_annotation = None
        for row in all_data[:5]:
            for cell_val in row:
                if cell_val is not None:
                    unit_annotation = _detect_unit_annotation(str(cell_val))
                    if unit_annotation:
                        break
            if unit_annotation:
                break

        # Split into sub-tables separated by empty rows
        sub_tables = self._split_by_empty_rows(all_data)

        extracted: list[ExtractedTable] = []

        for sub_idx, (start_row_idx, sub_data) in enumerate(sub_tables):
            if not sub_data:
                continue

            try:
                et = self._build_table_from_rows(
                    sub_data, file_path, source_type, sheet_idx,
                    sheet_name, global_idx_start + sub_idx,
                    has_merged, unit_annotation, ws_formulas,
                )
                if et is not None:
                    extracted.append(et)
            except Exception as exc:
                logger.warning(
                    "Failed to build table from rows in sheet '%s', sub-table %d: %s",
                    sheet_name, sub_idx, exc,
                    exc_info=True,
                )

        return extracted

    def _read_sheet_data(self, ws, merged_ranges: list) -> list[list]:
        """Read all cells from a worksheet, resolving merged cells."""
        data: list[list] = []
        for row in ws.iter_rows():
            row_data: list = []
            for cell in row:
                value = cell.value
                # Resolve merged cells
                if value is None:
                    for mr in merged_ranges:
                        if cell.coordinate in mr:
                            value = ws.cell(row=mr.min_row, column=mr.min_col).value
                            break
                row_data.append(value)
            data.append(row_data)
        return data

    def _split_by_empty_rows(
        self, data: list[list], min_empty_gap: int = 2
    ) -> list[tuple[int, list[list]]]:
        """Split sheet data into separate table regions.

        A gap of `min_empty_gap` or more consecutive fully-empty rows
        separates two tables.

        Returns list of (start_row_index, rows) tuples.
        """
        if not data:
            return []

        # Find empty rows
        empty_mask = []
        for row in data:
            is_empty = all(v is None or str(v).strip() == "" for v in row)
            empty_mask.append(is_empty)

        # Group consecutive non-empty rows
        tables: list[tuple[int, list[list]]] = []
        current_start = None
        current_rows: list[list] = []
        consecutive_empty = 0

        for i, (row, is_empty) in enumerate(zip(data, empty_mask)):
            if is_empty:
                consecutive_empty += 1
                if consecutive_empty >= min_empty_gap and current_rows:
                    tables.append((current_start, current_rows))
                    current_rows = []
                    current_start = None
            else:
                if current_start is None:
                    current_start = i
                if consecutive_empty < min_empty_gap and consecutive_empty > 0:
                    # Small gap: include the empty rows (might be formatting)
                    for _ in range(consecutive_empty):
                        current_rows.append([None] * len(row))
                current_rows.append(row)
                consecutive_empty = 0

        if current_rows:
            tables.append((current_start or 0, current_rows))

        return tables

    def _build_table_from_rows(
        self,
        rows: list[list],
        file_path: Path,
        source_type: str,
        sheet_idx: int,
        sheet_name: str,
        table_idx: int,
        has_merged: bool,
        unit_annotation: Optional[str],
        ws_formulas,
    ) -> Optional[ExtractedTable]:
        """Convert raw rows into an ExtractedTable, detecting the header row."""
        if not rows or len(rows) < 1:
            return None

        # Detect header row: find the first row where most cells have text values
        header_idx = self._detect_header_row(rows)
        if header_idx is None:
            header_idx = 0

        # Build column names
        header_row = rows[header_idx]
        columns = []
        for j, v in enumerate(header_row):
            col_name = str(v).strip() if v is not None else f"Col_{j}"
            if not col_name or col_name == "None":
                col_name = f"Col_{j}"
            columns.append(col_name)

        # Data rows are everything after the header
        data_rows = rows[header_idx + 1:]
        if not data_rows:
            # Table has only headers, no data
            df = pd.DataFrame(columns=columns)
            return ExtractedTable(
                df=df,
                source_file=str(file_path),
                source_file_type=source_type,
                page_number=sheet_idx,
                sheet_name=sheet_name,
                section_heading=sheet_name,
                section_hierarchy=[sheet_name],
                table_index=table_idx,
                bbox=None,
                surrounding_text=None,
                raw_cell_text=" | ".join(columns),
                extraction_method="openpyxl",
                extraction_confidence=None,
                row_count=0,
                col_count=len(columns),
                has_merged_cells=has_merged,
                has_numeric_data=False,
                metadata={"source_unit": unit_annotation} if unit_annotation else {},
            )

        # Normalize row lengths to match header
        normalized_rows = []
        for row in data_rows:
            if len(row) < len(columns):
                row = list(row) + [None] * (len(columns) - len(row))
            elif len(row) > len(columns):
                row = row[:len(columns)]
            normalized_rows.append(row)

        df = pd.DataFrame(normalized_rows, columns=columns)

        # Drop fully empty rows
        df = df.dropna(how="all")

        if df.empty:
            return None

        # Detect footnote rows and separate
        footnote_rows = []
        keep_mask = []
        for row_idx in range(len(df)):
            row_vals = df.iloc[row_idx].tolist()
            if _is_footnote_row(row_vals):
                footnote_rows.append(
                    " | ".join(str(v) for v in row_vals if v is not None)
                )
                keep_mask.append(False)
            else:
                keep_mask.append(True)
        if footnote_rows and not all(keep_mask):
            df = df.loc[keep_mask].reset_index(drop=True)

        has_numeric = _check_has_numeric(df)

        # Collect formula info
        formulas = {}
        if ws_formulas:
            try:
                for row in ws_formulas.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith("="):
                            formulas[cell.coordinate] = cell.value
            except Exception:
                pass

        # Raw header text for audit trail
        raw_cell_text = " | ".join(columns)

        metadata: dict = {}
        if unit_annotation:
            metadata["source_unit"] = unit_annotation
        if footnote_rows:
            metadata["footnotes"] = footnote_rows
        if formulas:
            metadata["formula_count"] = len(formulas)
            # Store a sample of formulas (up to 20)
            sample = dict(list(formulas.items())[:20])
            metadata["formula_sample"] = sample

        # Rows above header may contain metadata (company name, period, etc.)
        meta_rows = rows[:header_idx]
        if meta_rows:
            meta_texts = []
            for mr in meta_rows:
                text = " ".join(str(v).strip() for v in mr if v is not None and str(v).strip())
                if text:
                    meta_texts.append(text)
            if meta_texts:
                metadata["header_metadata"] = meta_texts

        return ExtractedTable(
            df=df,
            source_file=str(file_path),
            source_file_type=source_type,
            page_number=sheet_idx,
            sheet_name=sheet_name,
            section_heading=sheet_name,
            section_hierarchy=[sheet_name],
            table_index=table_idx,
            bbox=None,
            surrounding_text=None,
            raw_cell_text=raw_cell_text,
            extraction_method="openpyxl",
            extraction_confidence=None,
            row_count=len(df),
            col_count=len(df.columns),
            has_merged_cells=has_merged,
            has_numeric_data=has_numeric,
            metadata=metadata,
        )

    def _detect_header_row(self, rows: list[list]) -> Optional[int]:
        """Detect which row is the header row.

        Heuristic: the header row is the first row where:
        1. At least half the cells are non-empty
        2. Most cells contain text (not numbers)
        3. The following row(s) contain numeric data

        Falls back to the first non-empty row.
        """
        if not rows:
            return None

        first_nonempty = None

        for i, row in enumerate(rows):
            non_empty_count = sum(
                1 for v in row if v is not None and str(v).strip() != ""
            )
            if non_empty_count == 0:
                continue

            if first_nonempty is None:
                first_nonempty = i

            total = len(row)
            fill_ratio = non_empty_count / total if total > 0 else 0

            if fill_ratio < 0.3:
                continue

            # Check if this row is mostly text
            text_count = 0
            numeric_count = 0
            for v in row:
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                try:
                    float(str(v).replace(",", "").replace("(", "-").replace(")", ""))
                    numeric_count += 1
                except (ValueError, TypeError):
                    text_count += 1

            # Header rows should have more text than numbers
            if text_count >= numeric_count and non_empty_count >= 2:
                # Verify: at least one of the next 3 rows has numeric data
                has_numeric_below = False
                for j in range(i + 1, min(i + 4, len(rows))):
                    next_row = rows[j]
                    for v in next_row:
                        if v is None:
                            continue
                        try:
                            float(
                                str(v).replace(",", "")
                                .replace("(", "-").replace(")", "")
                            )
                            has_numeric_below = True
                            break
                        except (ValueError, TypeError):
                            pass
                    if has_numeric_below:
                        break

                if has_numeric_below:
                    return i

        return first_nonempty


# ---------------------------------------------------------------------------
# CSV extractor (pandas)
# ---------------------------------------------------------------------------

class _CSVExtractor:
    """Extract a single table from a CSV file using pandas."""

    def extract(self, file_path: Path) -> list[ExtractedTable]:
        """Read a CSV file and return it as a single ExtractedTable."""
        source_type = "csv"

        # Detect encoding
        encoding = self._detect_encoding(file_path)

        try:
            df = pd.read_csv(str(file_path), encoding=encoding)
        except UnicodeDecodeError:
            # Fallback encodings
            for enc in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
                try:
                    df = pd.read_csv(str(file_path), encoding=enc)
                    encoding = enc
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            else:
                logger.error("Cannot read CSV %s with any encoding", file_path.name)
                return []
        except Exception as exc:
            logger.error("Cannot read CSV %s: %s", file_path.name, exc)
            return []

        if df.empty:
            return []

        # Check for unit annotations in column names
        unit_annotation = None
        for col in df.columns:
            unit_annotation = _detect_unit_annotation(str(col))
            if unit_annotation:
                break

        # Also check filename
        if not unit_annotation:
            unit_annotation = _detect_unit_annotation(file_path.name)

        raw_cell_text = " | ".join(str(c) for c in df.columns)
        has_numeric = _check_has_numeric(df)

        metadata: dict = {}
        if unit_annotation:
            metadata["source_unit"] = unit_annotation
        metadata["encoding"] = encoding

        section_heading = file_path.stem  # filename without extension

        return [
            ExtractedTable(
                df=df,
                source_file=str(file_path),
                source_file_type=source_type,
                page_number=None,
                sheet_name=None,
                section_heading=section_heading,
                section_hierarchy=[section_heading],
                table_index=0,
                bbox=None,
                surrounding_text=None,
                raw_cell_text=raw_cell_text,
                extraction_method="pandas_csv",
                extraction_confidence=None,
                row_count=len(df),
                col_count=len(df.columns),
                has_merged_cells=False,
                has_numeric_data=has_numeric,
                metadata=metadata,
            )
        ]

    def _detect_encoding(self, file_path: Path) -> str:
        """Detect file encoding by reading a sample of bytes."""
        try:
            import chardet
            with open(file_path, "rb") as f:
                raw = f.read(10000)
            result = chardet.detect(raw)
            enc = result.get("encoding", "utf-8")
            return enc if enc else "utf-8"
        except ImportError:
            pass

        # Simple heuristic without chardet
        try:
            with open(file_path, "rb") as f:
                raw = f.read(4)
            # Check BOM
            if raw.startswith(b"\xef\xbb\xbf"):
                return "utf-8-sig"
            if raw.startswith(b"\xff\xfe"):
                return "utf-16-le"
            if raw.startswith(b"\xfe\xff"):
                return "utf-16-be"
        except Exception:
            pass

        return "utf-8"


# ---------------------------------------------------------------------------
# Main TableExtractor class
# ---------------------------------------------------------------------------

class TableExtractor:
    """Context-aware table extractor for forensic accounting documents.

    Supports PDF, DOCX, XLSX, XLS, and CSV files. Automatically detects
    file type and routes to the appropriate extraction backend.

    Usage:
        extractor = TableExtractor()
        results = extractor.extract_all("path/to/document.pdf")
        for table in results:
            print(table.section_heading, table.df.shape)
    """

    DOCLING_EXTENSIONS = {".pdf", ".docx"}
    EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".xlsb"}
    CSV_EXTENSIONS = {".csv", ".tsv"}

    def __init__(self):
        self._docling = _DoclingExtractor()
        self._excel = _ExcelExtractor()
        self._csv = _CSVExtractor()

    def extract_all(self, file_path: str | Path) -> list[ExtractedTable]:
        """Extract all tables from a document with context metadata.

        Auto-detects file type and routes to the appropriate extractor.
        Returns a list of ExtractedTable objects, one per table found.

        Args:
            file_path: Path to the document (PDF, DOCX, XLSX, XLS, CSV).

        Returns:
            List of ExtractedTable objects. Empty list if no tables found
            or if the file cannot be processed.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file type is not supported.
        """
        path = Path(file_path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        logger.info("Processing %s (type: %s)", path.name, ext)

        if ext in self.DOCLING_EXTENSIONS:
            return self._docling.extract(path)
        elif ext in self.EXCEL_EXTENSIONS:
            return self._excel.extract(path)
        elif ext in self.CSV_EXTENSIONS:
            return self._csv.extract(path)
        else:
            raise ValueError(
                f"Unsupported file type: '{ext}'. "
                f"Supported: {sorted(self.DOCLING_EXTENSIONS | self.EXCEL_EXTENSIONS | self.CSV_EXTENSIONS)}"
            )
