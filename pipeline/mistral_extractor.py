"""
Mistral OCR table extractor — drop-in replacement for the Docling pipeline.

Sends PDFs to Mistral OCR 3 (mistral-ocr-latest) and converts the response
into the same ``ExtractedTable`` dataclass used by the rest of the pipeline.
The normalizer, skills, and DuckDB schema need no changes.

Usage:
    from pipeline.mistral_extractor import MistralTableExtractor

    extractor = MistralTableExtractor()
    tables = extractor.extract("user_documents/some_file.pdf")

Set MISTRAL_API_KEY in the environment (or .env) before use.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline.table_extractor import (
    ExtractedTable,
    _UNIT_PATTERN,
    _FOOTNOTE_PATTERN,
    _detect_unit_annotation,
    _check_has_numeric,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_CACHE_DIR = Path(__file__).resolve().parent / "test_output" / "mistral_cache"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _html_table_to_df(html: str) -> Optional[pd.DataFrame]:
    """Convert a single Mistral HTML table to a DataFrame.

    ``pd.read_html`` handles colspan/rowspan natively, which is the main
    reason we request ``table_format="html"`` from Mistral.
    """
    try:
        dfs = pd.read_html(StringIO(html))
        if not dfs:
            return None
        df = dfs[0]
        # Drop fully-empty rows and columns
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return None
        # Clean column names
        df.columns = [
            str(c).strip() if pd.notna(c) else f"Column_{i}"
            for i, c in enumerate(df.columns)
        ]
        return df
    except Exception as exc:
        logger.warning("pd.read_html failed on HTML table: %s", exc)
        return None


def _has_merged_cells_in_html(html: str) -> bool:
    """Return True if the HTML contains colspan or rowspan attributes."""
    return bool(re.search(r"(?:colspan|rowspan)\s*=\s*[\"']?\d+", html, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Page-level context parsing
# ---------------------------------------------------------------------------
#
# Indian financial statements follow a rigid page structure:
#   Line 1:  Entity name            (repeats on most pages)
#   Line 2:  Statement/note title   ("Notes to the financial statements ...")
#   Line 3:  Period                 ("for the year ended March 31, 2024")
#   Line 4:  Unit annotation        ("(All amounts in Rs. Lakhs, ...)")
#   ...
#   [TABLE]
#
# We parse the preamble (text before the first table) to get page-level
# context, then let each table inherit it.  Per-table sub-headings (e.g.
# "33 Income Tax") refine the context but don't replace it.

# Statement type keywords — order matters (first match wins)
_STATEMENT_KEYWORDS: list[tuple[str, str]] = [
    ("profit and loss", "profit_and_loss"),
    ("profit & loss", "profit_and_loss"),
    ("p&l", "profit_and_loss"),
    ("income statement", "profit_and_loss"),
    ("balance sheet", "balance_sheet"),
    ("financial position", "balance_sheet"),
    ("cash flow", "cash_flow"),
    ("trial balance", "trial_balance"),
    ("general ledger", "general_ledger"),
    ("bank statement", "bank_statement"),
    ("related party", "related_party"),
    ("related parties", "related_party"),
    ("notes to the financial statements", "notes_schedule"),
    ("notes to financial statements", "notes_schedule"),
]


def _build_page_context(
    markdown: str,
    header_text: str,
    footer_text: str,
    prev_context: Optional[dict] = None,
) -> dict:
    """Parse the page preamble to extract page-level context.

    Returns a dict with:
      entity_name, statement_title, statement_type, unit, period, preamble_text
    """
    # Find preamble: text before the first table placeholder
    first_tbl = re.search(r"\[tbl-\d+\.html\]", markdown)
    preamble = markdown[:first_tbl.start()].strip() if first_tbl else ""

    lines = [ln.strip() for ln in preamble.splitlines() if ln.strip()]

    # --- Entity name: first line if it looks like a proper name (no keywords) ---
    entity_name = None
    statement_title = None
    period = None
    unit = None
    statement_type = "other"

    # Classify each preamble line
    for line in lines:
        ll = line.lower().lstrip("#").strip()

        # Skip unit annotation lines — they're not titles
        if _detect_unit_annotation(line):
            unit = _detect_unit_annotation(line)
            continue

        # Skip bare page numbers
        if re.match(r"^\d{1,3}$", ll):
            continue

        # Check for statement type keywords (first match wins — don't overwrite)
        if statement_type == "other":
            matched_type = None
            for keyword, stype in _STATEMENT_KEYWORDS:
                if keyword in ll:
                    matched_type = stype
                    statement_title = line.lstrip("#").strip()
                    break

            if matched_type:
                statement_type = matched_type
                continue

        # Check for period pattern
        if re.search(r"for the year ended|as at|as on", ll):
            period = line.strip()
            # Period lines sometimes contain the statement title too
            # e.g. "Standalone Statement of Profit and Loss for the year ended..."
            if statement_type == "other":
                for keyword, stype in _STATEMENT_KEYWORDS:
                    if keyword in ll:
                        statement_type = stype
                        statement_title = line.lstrip("#").strip()
                        break
            continue

        # First unclassified non-trivial line → likely entity name
        if entity_name is None and len(ll) > 3:
            entity_name = line.strip()

    # Also check header/footer for unit
    if not unit:
        unit = _detect_unit_from_texts(header_text, footer_text)

    # --- Carry forward from previous page if this page is sparse ---
    if prev_context:
        if not entity_name:
            entity_name = prev_context.get("entity_name")
        if statement_type == "other" and not statement_title:
            # Bare pages (just "3" or empty) → continuation of previous section
            statement_type = prev_context.get("statement_type", "other")
            statement_title = prev_context.get("statement_title")
        if not unit:
            unit = prev_context.get("unit")

    return {
        "entity_name": entity_name,
        "statement_title": statement_title,
        "statement_type": statement_type,
        "unit": unit,
        "period": period,
        "preamble_text": preamble,
    }


def _get_local_heading(markdown: str, table_placeholder: str, page_ctx: dict) -> str:
    """Get the per-table heading: local sub-heading if any, else page statement title.

    For a page with multiple tables, the text between the previous table and
    the current one often contains a sub-heading like "33 Income Tax".
    """
    idx = markdown.find(table_placeholder)
    if idx < 0:
        return page_ctx.get("statement_title") or ""

    before = markdown[:idx]

    # Find preceding table placeholder to isolate the inter-table text
    prev_tables = list(re.finditer(r"\[tbl-\d+\.html\]\(tbl-\d+\.html\)", before))
    if prev_tables:
        inter_text = before[prev_tables[-1].end():].strip()
    else:
        # First table on page — inter_text is the preamble (already parsed)
        inter_text = ""

    # Look for a sub-heading in the inter-table text
    local_heading = None
    if inter_text:
        # Try markdown headings
        heading_match = re.findall(r"^#{1,5}\s+(.+)$", inter_text, re.MULTILINE)
        if heading_match:
            local_heading = heading_match[-1].strip()
        else:
            # Use last non-trivial, non-unit line
            for line in reversed(inter_text.splitlines()):
                line = line.strip()
                if not line:
                    continue
                if _detect_unit_annotation(line):
                    continue
                if re.match(r"^\d{1,3}$", line):
                    continue
                if len(line) > 3:
                    local_heading = line[:120]
                    break

    # Compose: "Statement Title — Local Sub-heading" or just one of them
    stmt_title = page_ctx.get("statement_title") or ""
    if local_heading and stmt_title:
        # Don't duplicate if the local heading IS the statement title
        if local_heading.lower().strip() == stmt_title.lower().strip():
            return stmt_title
        return f"{stmt_title} — {local_heading}"
    return local_heading or stmt_title or ""


def _extract_surrounding_text(markdown: str, table_placeholder: str, chars: int = 200) -> str:
    """Extract ~*chars* characters before and after *table_placeholder* in *markdown*."""
    idx = markdown.find(table_placeholder)
    if idx < 0:
        return ""
    before = markdown[max(0, idx - chars):idx].strip()
    after = markdown[idx + len(table_placeholder):idx + len(table_placeholder) + chars].strip()
    parts = []
    if before:
        parts.append(f"[BEFORE] {before}")
    if after:
        parts.append(f"[AFTER] {after}")
    return " ".join(parts)


def _detect_unit_from_texts(*texts: str) -> Optional[str]:
    """Run ``_detect_unit_annotation`` across multiple text sources; return first hit."""
    for text in texts:
        if not text:
            continue
        unit = _detect_unit_annotation(text)
        if unit:
            return unit
    return None


def _detect_footnote_rows(df: pd.DataFrame) -> list[str]:
    """Return footnote-like text found in the last rows of *df*."""
    footnotes: list[str] = []
    for _, row in df.tail(5).iterrows():
        first_val = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        if first_val and _FOOTNOTE_PATTERN.match(first_val):
            footnotes.append(first_val)
    return footnotes


def _file_hash(path: Path) -> str:
    """Return a short SHA-256 hex digest for cache keying."""
    h = hashlib.sha256()
    h.update(path.name.encode())
    h.update(str(path.stat().st_size).encode())
    h.update(str(path.stat().st_mtime_ns).encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class MistralTableExtractor:
    """Extract tables from PDFs via Mistral OCR, returning ``ExtractedTable`` objects."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "mistral-ocr-latest",
    ):
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self.model = model
        if not self.api_key:
            raise ValueError(
                "MISTRAL_API_KEY not set. Pass api_key= or set the env var."
            )

    # ----- public API -----

    def extract(
        self,
        file_path: str | Path,
        *,
        max_pages: int | None = None,
        use_cache: bool = True,
    ) -> list[ExtractedTable]:
        """Extract tables from *file_path* via Mistral OCR.

        Parameters
        ----------
        file_path : str or Path
            Path to the input PDF.
        max_pages : int, optional
            Only process the first N pages (saves post-processing time; the
            API still processes the whole PDF).
        use_cache : bool
            If True, cache the raw API response to disk and reuse it on
            subsequent calls for the same file.

        Returns
        -------
        list[ExtractedTable]
            Same contract as ``TableExtractor.extract_all()``.
        """
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw_response = self._get_or_call_api(file_path, use_cache=use_cache)
        return self._response_to_tables(raw_response, file_path, max_pages=max_pages)

    def extract_text(
        self,
        file_path: str | Path,
        *,
        max_pages: int | None = None,
        use_cache: bool = True,
    ) -> str:
        """Extract full page markdown text from *file_path* via Mistral OCR.

        Returns the concatenated markdown of all pages — prose, headings,
        tables (as markdown), and all other content.  This is the full OCR
        output, not just extracted tables.

        Parameters
        ----------
        file_path : str or Path
            Path to the input PDF.
        max_pages : int, optional
            Only return text from the first N pages.
        use_cache : bool
            Reuse cached API response if available.

        Returns
        -------
        str
            Full page markdown, pages separated by ``\\n\\n---\\n\\n``.
        """
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw_response = self._get_or_call_api(file_path, use_cache=use_cache)
        return self._response_to_text(raw_response, max_pages=max_pages)

    def extract_both(
        self,
        file_path: str | Path,
        *,
        max_pages: int | None = None,
        use_cache: bool = True,
    ) -> tuple[str, list[ExtractedTable]]:
        """Extract both full-text markdown AND structured tables in one call.

        Single API call (or cache hit), dual output — used for dual-indexing
        where text goes to LightRAG and tables go to DuckDB normalization.

        Returns
        -------
        tuple[str, list[ExtractedTable]]
            (full_page_markdown, extracted_tables)
        """
        file_path = Path(file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        raw_response = self._get_or_call_api(file_path, use_cache=use_cache)
        text = self._response_to_text(raw_response, max_pages=max_pages)
        tables = self._response_to_tables(raw_response, file_path, max_pages=max_pages)
        return text, tables

    # ----- API interaction -----

    def _get_or_call_api(self, file_path: Path, *, use_cache: bool) -> dict:
        """Return the raw OCR response dict, from cache or fresh API call."""
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _CACHE_DIR / f"{_file_hash(file_path)}.json"

        if use_cache and cache_file.exists():
            logger.info("Loading cached Mistral response from %s", cache_file.name)
            with open(cache_file) as f:
                return json.load(f)

        response_dict = self._call_api(file_path)

        # Persist for future runs
        with open(cache_file, "w") as f:
            json.dump(response_dict, f, indent=2, default=str)
        logger.info("Cached Mistral response to %s", cache_file.name)

        return response_dict

    def _call_api(self, file_path: Path) -> dict:
        """Upload the PDF and call Mistral OCR; return the response as a dict.

        Uses the upload → signed URL → process → cleanup pattern from the
        lightrag-bench reference code.
        """
        from mistralai import Mistral

        client = Mistral(api_key=self.api_key)
        uploaded_file = None
        try:
            # Upload
            logger.info("Uploading %s to Mistral …", file_path.name)
            with open(file_path, "rb") as f:
                uploaded_file = client.files.upload(
                    file={"file_name": file_path.name, "content": f},
                    purpose="ocr",
                )
            logger.info("Upload complete — file id %s", uploaded_file.id)

            # Get signed URL
            signed = client.files.get_signed_url(file_id=uploaded_file.id)
            signed_url = signed.url

            # Process
            logger.info("Calling OCR …")
            ocr_response = client.ocr.process(
                model=self.model,
                document={
                    "type": "document_url",
                    "document_url": signed_url,
                },
                table_format="html",
                include_image_base64=False,
            )
            logger.info(
                "OCR complete — %d page(s)",
                len(ocr_response.pages) if ocr_response.pages else 0,
            )

            # Convert to plain dict for caching
            return self._response_to_dict(ocr_response)
        finally:
            if uploaded_file is not None:
                try:
                    client.files.delete(file_id=uploaded_file.id)
                    logger.info("Cleaned up uploaded file %s", uploaded_file.id)
                except Exception:
                    logger.warning("Failed to delete uploaded file %s", uploaded_file.id)

    @staticmethod
    def _response_to_dict(ocr_response) -> dict:
        """Serialize the Mistral OCR response object to a JSON-safe dict."""
        pages = []
        for page in (ocr_response.pages or []):
            tables = []
            for tbl in (page.images if hasattr(page, "images") else []):
                # Tables come as image objects with HTML content in some SDK versions
                tables.append({
                    "id": getattr(tbl, "id", ""),
                    "content": getattr(tbl, "image_base64", "") or getattr(tbl, "content", ""),
                })
            # In the current SDK, tables are in page.tables (list of objects with .content)
            if hasattr(page, "tables") and page.tables:
                tables = []
                for tbl in page.tables:
                    tables.append({
                        "id": getattr(tbl, "id", ""),
                        "content": getattr(tbl, "content", ""),
                    })
            pages.append({
                "index": page.index,
                "markdown": page.markdown,
                "tables": tables,
                "header": getattr(page, "header", None),
                "footer": getattr(page, "footer", None),
            })
        return {
            "model": getattr(ocr_response, "model", ""),
            "pages": pages,
        }

    # ----- Response → full text -----

    @staticmethod
    def _response_to_text(
        response: dict,
        *,
        max_pages: int | None = None,
    ) -> str:
        """Concatenate all page markdown from the cached response.

        Returns one string with pages separated by horizontal rules.
        """
        pages = response.get("pages", [])
        if max_pages is not None:
            pages = pages[:max_pages]

        page_texts: list[str] = []
        for page in pages:
            md = page.get("markdown", "").strip()
            if md:
                page_texts.append(md)

        return "\n\n---\n\n".join(page_texts)

    # ----- Response → ExtractedTable conversion -----

    def _response_to_tables(
        self,
        response: dict,
        file_path: Path,
        *,
        max_pages: int | None = None,
    ) -> list[ExtractedTable]:
        """Convert a cached Mistral response dict into ``ExtractedTable`` objects."""
        tables: list[ExtractedTable] = []
        global_idx = 0
        prev_page_ctx: dict | None = None

        pages = response.get("pages", [])
        if max_pages is not None:
            pages = pages[:max_pages]

        for page in pages:
            page_index = page.get("index", 0)
            markdown = page.get("markdown", "")
            header_text = page.get("header") or ""
            footer_text = page.get("footer") or ""
            page_tables = page.get("tables", [])

            # Build page-level context (carries forward from previous page)
            page_ctx = _build_page_context(
                markdown, header_text, footer_text, prev_context=prev_page_ctx,
            )
            prev_page_ctx = page_ctx

            if not page_tables:
                continue

            # Use page context for unit (fallback to column-level detection)
            page_unit = page_ctx.get("unit")

            for tbl_i, tbl_obj in enumerate(page_tables):
                html_content = tbl_obj.get("content", "")
                tbl_id = tbl_obj.get("id", f"TABLE_{tbl_i + 1}")
                if not html_content:
                    continue

                # Parse HTML → DataFrame
                df = _html_table_to_df(html_content)
                if df is None or df.empty:
                    logger.info(
                        "Page %d table %d: empty after parsing, skipped", page_index, tbl_i
                    )
                    continue

                # Determine table placeholder as used in markdown
                placeholder = f"[{tbl_id}]"
                if placeholder not in markdown:
                    placeholder = f"[TABLE_{tbl_i + 1}]"
                if placeholder not in markdown:
                    placeholder = f"![{tbl_id}]"
                if placeholder not in markdown:
                    placeholder = f"![img-{tbl_i}]"

                # Section heading — page context + local sub-heading
                section_heading = _get_local_heading(markdown, placeholder, page_ctx)

                # Surrounding text
                surrounding_text = _extract_surrounding_text(markdown, placeholder)

                # Source unit — page context first, then column headers
                col_header_text = " | ".join(str(c) for c in df.columns)
                source_unit = page_unit or _detect_unit_from_texts(col_header_text)

                # Section hierarchy
                hierarchy: list[str] = []
                entity = page_ctx.get("entity_name")
                stmt_title = page_ctx.get("statement_title")
                if entity:
                    hierarchy.append(entity)
                if stmt_title:
                    hierarchy.append(stmt_title)
                # Add local sub-heading if it differs from statement title
                if section_heading and section_heading != stmt_title:
                    hierarchy.append(section_heading)

                # Merged cells
                has_merged = _has_merged_cells_in_html(html_content)

                # Numeric data
                has_numeric = _check_has_numeric(df)

                # Footnotes
                footnotes = _detect_footnote_rows(df)

                # Raw cell text (pipe-join of column headers)
                raw_cell_text = " | ".join(str(c) for c in df.columns)

                et = ExtractedTable(
                    df=df,
                    source_file=str(file_path),
                    source_file_type="pdf",
                    page_number=page_index,
                    sheet_name=None,
                    section_heading=section_heading,
                    section_hierarchy=hierarchy,
                    table_index=global_idx,
                    bbox=None,
                    surrounding_text=surrounding_text,
                    raw_cell_text=raw_cell_text,
                    extraction_method="mistral_ocr",
                    extraction_confidence=0.95,
                    row_count=len(df),
                    col_count=len(df.columns),
                    has_merged_cells=has_merged,
                    has_numeric_data=has_numeric,
                    metadata={
                        "source_unit": source_unit,
                        "footnotes": footnotes if footnotes else [],
                        "page_header": header_text if header_text else None,
                        "page_footer": footer_text if footer_text else None,
                        "statement_type": page_ctx.get("statement_type"),
                        "entity_name": page_ctx.get("entity_name"),
                    },
                )
                tables.append(et)
                global_idx += 1
                logger.info(
                    "Page %d table %d → %d rows × %d cols, unit=%s, type=%s, heading=%s",
                    page_index,
                    tbl_i,
                    len(df),
                    len(df.columns),
                    source_unit,
                    page_ctx.get("statement_type"),
                    (section_heading or "")[:60],
                )

        logger.info("Extracted %d table(s) total from %s", len(tables), file_path.name)
        return tables
