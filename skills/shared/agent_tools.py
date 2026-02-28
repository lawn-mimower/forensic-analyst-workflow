"""
ForensicToolkit — Agno Toolkit with 9 tools for the forensic analyst agent.

Tools:
  1. search_knowledge_graph  — Query RAG index
  2. upload_document         — Preprocess + ingest
  3. delete_document         — Remove from index
  4. list_indexed_documents  — Show indexed docs
  5. run_compliance_check    — Full 5-phase pipeline
  6. run_compliance_phase    — Single phase (0-4)
  7. get_compliance_report   — Read latest report
  8. preview_document        — Preprocess without indexing
  9. read_excel_sheet        — Read specific sheet with formulas

Usage:
    from skills.shared.agent_tools import ForensicToolkit
    toolkit = ForensicToolkit(rag=rag_instance)
"""

from __future__ import annotations

import json
import sys
import importlib.util
from pathlib import Path
from typing import Any

from agno.tools import Toolkit

from skills.shared.lightrag_init import (
    PROJECT_ROOT,
    DEFAULT_STORAGE,
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    ensure_output_dir,
)
from skills.shared.preprocessors import PreprocessingRouter
from skills.shared.lightrag_client import LightRAGClient, LightRAGDirectClient

# ---------------------------------------------------------------------------
# Compliance phase loading (same pattern as run_pipeline.py)
# ---------------------------------------------------------------------------
_COMPLIANCE_SCRIPT_DIR = PROJECT_ROOT / "skills" / "compliance-checker" / "scripts"

_phase_modules: dict[str, Any] = {}


def _import_phase(name: str):
    """Import a compliance phase script by name using importlib (handles hyphen in path)."""
    if name not in _phase_modules:
        spec = importlib.util.spec_from_file_location(
            name, _COMPLIANCE_SCRIPT_DIR / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _phase_modules[name] = mod
    return _phase_modules[name]


# Phase name → (module_name, function_name, extra_kwargs_keys)
_PHASE_MAP = {
    0: ("profile_document", "profile_document", ["storage"]),
    1: ("atomise_laws", "atomise_laws", []),
    2: ("batch_retrieve", "batch_retrieve", ["storage", "max_concurrent"]),
    3: ("adjudicate", "adjudicate", ["max_concurrent"]),
    4: ("generate_report", "generate_report", []),
}


# ---------------------------------------------------------------------------
# ForensicToolkit
# ---------------------------------------------------------------------------
class ForensicToolkit(Toolkit):
    """Agent toolkit for forensic document analysis and compliance checking."""

    def __init__(
        self,
        rag: Any = None,
        client: LightRAGClient | None = None,
        storage_path: str | Path | None = None,
        input_dir: str | Path | None = None,
    ):
        super().__init__(name="forensic_tools")

        self._storage_path = str(storage_path or DEFAULT_STORAGE)
        self._input_dir = Path(input_dir or DEFAULT_INPUT_DIR)
        self._input_dir.mkdir(parents=True, exist_ok=True)
        self._router = PreprocessingRouter()

        # Wrap raw rag instance in a client if needed
        if client is not None:
            self._client = client
        elif rag is not None:
            self._client = LightRAGDirectClient(rag)
        else:
            self._client = None  # Will be initialized lazily

        # Register all tools
        self.register(self.search_knowledge_graph)
        self.register(self.upload_document)
        self.register(self.delete_document)
        self.register(self.list_indexed_documents)
        self.register(self.run_compliance_check)
        self.register(self.run_compliance_phase)
        self.register(self.get_compliance_report)
        self.register(self.preview_document)
        self.register(self.read_excel_sheet)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a file path, checking user_documents/ if not found directly."""
        p = Path(file_path)
        if p.exists():
            return p
        # Try relative to user_documents/
        candidate = self._input_dir / p.name
        if candidate.exists():
            return candidate
        candidate = self._input_dir / file_path
        if candidate.exists():
            return candidate
        # Return original (will fail with a clear "not found" message)
        return p

    async def _get_client(self) -> LightRAGClient:
        """Lazy-init the LightRAG client."""
        if self._client is None:
            from skills.shared.lightrag_client import create_lightrag_client
            self._client = await create_lightrag_client(
                storage_path=self._storage_path
            )
        return self._client

    # ----- Tool 1: Search Knowledge Graph -----
    async def search_knowledge_graph(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 60,
    ) -> str:
        """Search the indexed documents using the knowledge graph.

        Args:
            query: The search query.
            mode: Search mode — 'local', 'global', 'hybrid', 'mix', or 'naive'.
            top_k: Number of results to retrieve.

        Returns:
            Search results as text.
        """
        client = await self._get_client()
        return await client.query(query, mode=mode, top_k=top_k)

    # ----- Tool 2: Upload Document -----
    async def upload_document(
        self,
        file_path: str,
        preprocessor_override: str | None = None,
    ) -> str:
        """Upload and index a document. Auto-selects preprocessor by file type.

        Files are looked up in user_documents/ by default. Absolute paths also work.

        Args:
            file_path: Path to document (PDF, XLSX, DOCX, images, CSV, etc.)
            preprocessor_override: Force a specific preprocessor ('docling', 'pandas', 'paddleocr').

        Returns:
            Status message with character count.
        """
        path = self._resolve_path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path} (also checked user_documents/)"

        result = await self._router.process(str(path), override=preprocessor_override)
        text = result.get("text", "")

        if not text.strip():
            return f"Warning: No text extracted from '{path.name}'. File may be empty or unsupported."

        client = await self._get_client()
        await client.insert_text(text)

        extras = []
        if "sheet_count" in result:
            extras.append(f"{result['sheet_count']} sheets")
        if "pages" in result and result["pages"]:
            extras.append(f"{result['pages']} pages")
        if "tables" in result and result["tables"]:
            extras.append(f"{len(result['tables'])} tables")

        info = f" ({', '.join(extras)})" if extras else ""
        return f"Indexed '{path.name}'{info} — {len(text):,} chars extracted."

    # ----- Tool 3: Delete Document -----
    async def delete_document(self, doc_id: str) -> str:
        """Remove a document from the index by its ID.

        Args:
            doc_id: The document ID to remove.

        Returns:
            Status message.
        """
        client = await self._get_client()
        result = await client.delete(doc_id)
        return f"Delete result: {json.dumps(result)}"

    # ----- Tool 4: List Indexed Documents -----
    async def list_indexed_documents(self) -> str:
        """List all documents currently indexed in the knowledge graph.

        Returns:
            JSON string with document info.
        """
        storage = Path(self._storage_path)
        docs_file = storage / "kv_store_full_docs.json"

        if not docs_file.exists():
            return "No documents indexed yet."

        with open(docs_file, "r") as f:
            docs = json.load(f)

        if not docs:
            return "No documents indexed yet."

        entries = []
        for doc_id, doc_data in docs.items():
            content = doc_data if isinstance(doc_data, str) else str(doc_data)
            preview = content[:200] + "..." if len(content) > 200 else content
            entries.append({"doc_id": doc_id, "preview": preview, "chars": len(content)})

        return json.dumps(entries, indent=2)

    # ----- Tool 5: Run Full Compliance Check -----
    async def run_compliance_check(self) -> str:
        """Run the full 5-phase compliance checking pipeline.

        Phases: 0=Profile, 1=Atomise, 2=Retrieve, 3=Adjudicate, 4=Report.

        Returns:
            Summary with overall compliance score.
        """
        out_dir = ensure_output_dir()
        out_str = str(out_dir)
        storage = self._storage_path

        results = {}
        for phase_num in range(5):
            try:
                result = await self._run_single_phase(phase_num, storage, out_str)
                results[f"phase_{phase_num}"] = "completed"
            except Exception as e:
                results[f"phase_{phase_num}"] = f"error: {e}"
                return f"Pipeline failed at phase {phase_num}: {e}\nResults so far: {json.dumps(results)}"

        # Read final report
        report_path = out_dir / "compliance_report.json"
        if report_path.exists():
            with open(report_path, "r") as f:
                report = json.load(f)
            score = report.get("overall", {}).get("score_pct", "N/A")
            totals = report.get("overall", {}).get("totals", {})
            return (
                f"Compliance check complete.\n"
                f"Overall Score: {score}\n"
                f"Compliant: {totals.get('COMPLIANT', 0)}, "
                f"Violations: {totals.get('VIOLATION', 0)}, "
                f"Insufficient Evidence: {totals.get('INSUFFICIENT_EVIDENCE', 0)}\n"
                f"Full report saved to: {out_dir}"
            )

        return f"Pipeline completed. Results: {json.dumps(results)}"

    # ----- Tool 6: Run Single Compliance Phase -----
    async def run_compliance_phase(self, phase: int) -> str:
        """Run a single compliance checking phase.

        Args:
            phase: Phase number (0=Profile, 1=Atomise, 2=Retrieve, 3=Adjudicate, 4=Report).

        Returns:
            Phase result summary.
        """
        if phase not in _PHASE_MAP:
            return f"Error: Invalid phase {phase}. Must be 0-4."

        out_dir = ensure_output_dir()
        try:
            result = await self._run_single_phase(phase, self._storage_path, str(out_dir))
            return f"Phase {phase} completed. Output saved to: {out_dir}"
        except Exception as e:
            return f"Phase {phase} failed: {e}"

    async def _run_single_phase(self, phase_num: int, storage: str, output_dir: str) -> Any:
        """Execute a single compliance phase."""
        mod_name, func_name, extra_keys = _PHASE_MAP[phase_num]
        mod = _import_phase(mod_name)
        func = getattr(mod, func_name)

        kwargs: dict[str, Any] = {"output_dir": output_dir}
        if "storage" in extra_keys:
            kwargs["storage"] = storage
        if "max_concurrent" in extra_keys:
            kwargs["max_concurrent"] = 4

        return await func(**kwargs)

    # ----- Tool 7: Get Compliance Report -----
    async def get_compliance_report(self) -> str:
        """Read the latest compliance report.

        Returns:
            The compliance report in markdown format, or a message if not found.
        """
        out_dir = ensure_output_dir()

        # Prefer markdown report
        md_path = out_dir / "compliance_report.md"
        if md_path.exists():
            return md_path.read_text(encoding="utf-8")

        # Fall back to JSON
        json_path = out_dir / "compliance_report.json"
        if json_path.exists():
            with open(json_path, "r") as f:
                report = json.load(f)
            return json.dumps(report, indent=2)

        return "No compliance report found. Run the compliance check first."

    # ----- Tool 8: Preview Document -----
    async def preview_document(self, file_path: str) -> str:
        """Preview document preprocessing output without indexing.

        Useful for quality-checking extraction before committing to the index.
        Files are looked up in user_documents/ by default.

        Args:
            file_path: Path to the document.

        Returns:
            Extracted text preview (first 3000 chars).
        """
        path = self._resolve_path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path} (also checked user_documents/)"

        result = await self._router.process(str(path))
        text = result.get("text", "")

        if not text.strip():
            return f"Warning: No text extracted from '{path.name}'."

        extras = []
        if "sheet_count" in result:
            extras.append(f"Sheets: {result['sheet_count']}")
        if "pages" in result and result["pages"]:
            extras.append(f"Pages: {result['pages']}")
        if "tables" in result and result["tables"]:
            extras.append(f"Tables: {len(result['tables'])}")
        extras.append(f"Total chars: {len(text):,}")

        header = f"**Preview of {path.name}** ({', '.join(extras)})\n\n"

        # Truncate for agent context
        if len(text) > 3000:
            return header + text[:3000] + "\n\n... (truncated)"
        return header + text

    # ----- Tool 9: Read Excel Sheet -----
    async def read_excel_sheet(
        self,
        file_path: str,
        sheet_name: str | None = None,
    ) -> str:
        """Read a specific Excel sheet with formatting and formula info.

        Files are looked up in user_documents/ by default.

        Args:
            file_path: Path to the Excel file.
            sheet_name: Sheet to read (default: first sheet).

        Returns:
            Sheet data as markdown with metadata and formulas.
        """
        path = self._resolve_path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path} (also checked user_documents/)"

        if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
            return f"Error: Not an Excel file: {path.name}"

        from openpyxl import load_workbook
        import pandas as pd

        wb = load_workbook(str(path), data_only=True)

        if sheet_name and sheet_name not in wb.sheetnames:
            wb.close()
            return f"Error: Sheet '{sheet_name}' not found. Available: {wb.sheetnames}"

        target_sheet = sheet_name or wb.sheetnames[0]
        ws = wb[target_sheet]

        # Build DataFrame
        data = []
        for row in ws.iter_rows(values_only=True):
            data.append(list(row))

        wb.close()

        if not data:
            return f"Sheet '{target_sheet}' is empty."

        # Find header row
        header_idx = 0
        for i, row in enumerate(data):
            if any(v is not None for v in row):
                header_idx = i
                break

        headers = [str(v) if v is not None else f"Col_{j}" for j, v in enumerate(data[header_idx])]
        rows = data[header_idx + 1:]
        df = pd.DataFrame(rows, columns=headers).dropna(how="all")

        # Get formulas
        preprocessor = self._router._excel
        formulas = preprocessor._extract_formulas(str(path), target_sheet)

        parts = [
            f"# {target_sheet}",
            f"**Source:** {path.name}",
            f"**Rows:** {len(df)}, **Columns:** {len(df.columns)}",
            "",
            "## Data",
            df.to_markdown(index=False),
            "",
            "## Formulas",
            formulas,
        ]

        return "\n".join(parts)
