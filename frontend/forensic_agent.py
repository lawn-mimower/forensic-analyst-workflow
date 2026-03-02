"""
Forensic Agent — Unified toolkit + persistent agent with memory/reasoning.

Provides:
  1. ForensicToolkit   — single Agno Toolkit with all forensic, RAG, and
                         compliance tools (merges the old ForensicSkillToolkit
                         and agent_tools.ForensicToolkit)
  2. build_forensic_agent — factory returning a fully-configured Agent with
                            SQLite persistence, session history, agentic memory,
                            and reasoning
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.tools.duckdb import DuckDbTools
from agno.tools.toolkit import Toolkit

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure project root is importable
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.model_config_agno import get_agent_model  # noqa: E402

# SQLite database for agent sessions and memory
_AGENT_DB_PATH = _PROJECT_ROOT / "data" / "forensic_agent.db"


# ---------------------------------------------------------------------------
# Skill runner helper
# ---------------------------------------------------------------------------

def _run_skill_script(
    script: Path,
    args: list[str],
    output_path: Path,
) -> dict[str, Any]:
    """Run a forensic skill script as a subprocess and return parsed JSON output."""
    cmd = [sys.executable, str(script), *args, "--output", str(output_path)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120,
        cwd=str(_PROJECT_ROOT),
    )
    if proc.returncode != 0:
        return {"error": f"Script exited {proc.returncode}", "stderr": proc.stderr[-500:]}
    try:
        with open(output_path) as f:
            return json.load(f)
    except Exception as exc:
        return {"error": f"Failed to parse output: {exc}"}


# ---------------------------------------------------------------------------
# View resolution helper
# ---------------------------------------------------------------------------

def _resolve_table(db_path: str, preferred: str, fallback: str) -> str:
    """Return *preferred* if it exists as a table/view in the DB, else *fallback*."""
    try:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return preferred if preferred in tables else fallback
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Compliance phase loading (same pattern as agent_tools.py)
# ---------------------------------------------------------------------------
_COMPLIANCE_SCRIPT_DIR = _PROJECT_ROOT / "skills" / "compliance-checker" / "scripts"
_phase_modules: dict[str, Any] = {}


def _import_phase(name: str):
    """Import a compliance phase script by name using importlib."""
    if name not in _phase_modules:
        script_path = _COMPLIANCE_SCRIPT_DIR / f"{name}.py"
        if not script_path.exists():
            raise FileNotFoundError(f"Compliance phase script not found: {script_path}")
        spec = importlib.util.spec_from_file_location(name, script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _phase_modules[name] = mod
    return _phase_modules[name]


_PHASE_MAP = {
    0: ("profile_document", "profile_document", ["storage"]),
    1: ("atomise_laws", "atomise_laws", []),
    2: ("batch_retrieve", "batch_retrieve", ["storage", "max_concurrent"]),
    3: ("adjudicate", "adjudicate", ["max_concurrent"]),
    4: ("generate_report", "generate_report", []),
}


# ---------------------------------------------------------------------------
# Unified ForensicToolkit
# ---------------------------------------------------------------------------

class ForensicToolkit(Toolkit):
    """Single Agno Toolkit combining forensic skills, data quality,
    RAG/knowledge-graph search, compliance pipeline, and dual-index
    document processing.

    Tools registered:
      PIPELINE:       run_pipeline
      DATA QUALITY:   inspect_database, curate_dataset
      FORENSIC:       run_benfords_analysis, run_duplicate_detector,
                      run_ratio_analyzer, run_anomaly_detector,
                      run_network_analyzer
      RAG / Q&A:      search_knowledge_graph, upload_document,
                      list_indexed_documents
      COMPLIANCE:     run_compliance_check, run_compliance_phase,
                      get_compliance_report
    """

    def __init__(
        self,
        db_path: str | None = None,
        rag_storage_path: str | Path | None = None,
        output_dir: str | None = None,
    ):
        super().__init__(name="forensic_toolkit")
        self.db_path = db_path
        self.rag_storage_path = str(
            rag_storage_path or _PROJECT_ROOT / "rag_storage"
        )
        self.output_dir = Path(output_dir) if output_dir else (
            Path(db_path).parent / "skill_results" if db_path else
            _PROJECT_ROOT / "pipeline" / "test_output" / "skill_results"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-init RAG client
        self._rag_client = None
        self._router = None  # Lazy PreprocessingRouter

        # Register all tools
        # -- Pipeline --
        self.register(self.run_pipeline)
        # -- Data quality --
        self.register(self.inspect_database)
        self.register(self.curate_dataset)
        # -- Forensic skills --
        self.register(self.run_benfords_analysis)
        self.register(self.run_duplicate_detector)
        self.register(self.run_ratio_analyzer)
        self.register(self.run_anomaly_detector)
        self.register(self.run_network_analyzer)
        # -- RAG / Q&A --
        self.register(self.search_knowledge_graph)
        self.register(self.upload_document)
        self.register(self.list_indexed_documents)
        # -- Compliance --
        self.register(self.run_compliance_check)
        self.register(self.run_compliance_phase)
        self.register(self.get_compliance_report)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _require_db(self) -> str:
        """Return db_path or raise a helpful error."""
        if not self.db_path:
            raise ValueError(
                "No database loaded. Run `run_pipeline` to process a document "
                "first, or load an existing DuckDB database."
            )
        return self.db_path

    def _line_items_table(self) -> str:
        return _resolve_table(self._require_db(), "curated_line_items", "line_items")

    def _related_parties_table(self) -> str:
        return _resolve_table(self._require_db(), "curated_related_parties", "related_parties")

    def _get_router(self):
        if self._router is None:
            from skills.shared.preprocessors import PreprocessingRouter
            self._router = PreprocessingRouter(pdf_backend="mistral")
        return self._router

    async def _get_rag_client(self):
        """Lazy-init the LightRAG client."""
        if self._rag_client is None:
            from skills.shared.lightrag_client import create_lightrag_client
            self._rag_client = await create_lightrag_client(
                storage_path=self.rag_storage_path
            )
        return self._rag_client

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve a file path, checking user_documents/ if not found."""
        p = Path(file_path)
        if p.exists():
            return p
        user_docs = _PROJECT_ROOT / "user_documents"
        candidate = user_docs / p.name
        if candidate.exists():
            return candidate
        candidate = user_docs / file_path
        if candidate.exists():
            return candidate
        return p

    # ══════════════════════════════════════════════════════════════════════
    # PIPELINE TOOL
    # ══════════════════════════════════════════════════════════════════════

    def run_pipeline(
        self,
        file_path: str,
        entity_name: str = "Unknown",
        fiscal_year: str = "Unknown",
        extractor: str = "mistral",
    ) -> str:
        """Process a financial document through dual indexing.

        Performs:
        1. Mistral OCR extracts full page content (cached)
        2. Full text → LightRAG index (for Q&A and compliance)
        3. Tables → DuckDB normalization (for forensic skills)
        4. Auto-curate the DuckDB
        5. Run full forensic skill sweep

        Args:
            file_path: Path to document (PDF, XLSX).
            entity_name: Company name for normalization.
            fiscal_year: Fiscal year (e.g. "2023-24").
            extractor: "mistral" (default) or "docling".

        Returns:
            JSON with: db_path, rag_indexed, line_items_count,
            skills_run, skill_statuses.
        """
        path = self._resolve_path(file_path)
        if not path.exists():
            return json.dumps({"error": f"File not found: {file_path}"})

        result_info: dict[str, Any] = {
            "file": str(path),
            "entity_name": entity_name,
            "fiscal_year": fiscal_year,
        }

        # ── Track 1: DuckDB pipeline (extract → normalize → curate → skills) ──
        try:
            from frontend.pipeline_runner import run_pipeline as _run_duckdb_pipeline
            pr = _run_duckdb_pipeline(
                file_paths=[path],
                extractor=extractor,
                from_cache=True,
                entity_name=entity_name,
                fiscal_year=fiscal_year,
            )
            if pr.success and pr.db_path:
                self.db_path = str(pr.db_path)
                result_info["db_path"] = str(pr.db_path)
                result_info["duckdb_success"] = True
                result_info["skill_statuses"] = pr.skill_statuses
                result_info["skills_run"] = list(pr.skill_outputs.keys())
            else:
                result_info["duckdb_success"] = False
                result_info["duckdb_error"] = pr.error
        except Exception as exc:
            result_info["duckdb_success"] = False
            result_info["duckdb_error"] = str(exc)

        # ── Track 2: LightRAG indexing ──
        try:
            if path.suffix.lower() == ".pdf" and extractor == "mistral":
                from pipeline.mistral_extractor import MistralTableExtractor
                ext = MistralTableExtractor()
                full_text = ext.extract_text(path, use_cache=True)
            else:
                # Fallback: use preprocessing router
                router = self._get_router()
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        prep_result = pool.submit(
                            asyncio.run, router.process(str(path))
                        ).result()
                else:
                    prep_result = asyncio.run(router.process(str(path)))
                full_text = prep_result.get("text", "")

            if full_text.strip():
                # Insert into RAG
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            pool.submit(
                                asyncio.run,
                                self._index_text_to_rag(full_text),
                            ).result()
                    else:
                        asyncio.run(self._index_text_to_rag(full_text))
                    result_info["rag_indexed"] = True
                    result_info["rag_chars"] = len(full_text)
                except Exception as rag_exc:
                    result_info["rag_indexed"] = False
                    result_info["rag_error"] = str(rag_exc)
            else:
                result_info["rag_indexed"] = False
                result_info["rag_error"] = "No text extracted"
        except Exception as exc:
            result_info["rag_indexed"] = False
            result_info["rag_error"] = str(exc)

        return json.dumps(result_info, indent=2, default=str)

    async def _index_text_to_rag(self, text: str) -> None:
        """Insert text into LightRAG knowledge graph."""
        client = await self._get_rag_client()
        await client.insert_text(text)

    # ══════════════════════════════════════════════════════════════════════
    # DATA QUALITY TOOLS
    # ══════════════════════════════════════════════════════════════════════

    def inspect_database(self) -> str:
        """Inspect the forensic database for data quality issues.

        Profiles period labels, account names, related parties, extraction
        duplicates, and unit consistency.  Returns a structured report with
        a needs_curation flag and suggested fixes.

        Use this FIRST before running any analysis skills to understand the
        quality of the data.

        Returns:
            JSON string with quality profile, issues list, and suggested
            curation actions.
        """
        db = self._require_db()
        from skills.shared.data_inspector import profile_database
        profile = profile_database(db)
        return json.dumps(profile.to_dict(), indent=2, default=str)

    def curate_dataset(
        self,
        auto: bool = True,
        period_map: str = "",
        deduplicate: bool = True,
        entity_whitelist: str = "",
        exclude_account_patterns: str = "",
        exclude_account_names: str = "",
    ) -> str:
        """Create curated views for clean skill consumption.

        Creates ``curated_line_items`` and ``curated_related_parties`` views.
        Raw tables are NEVER modified.

        Args:
            auto: If True, use inspector's suggestions for all parameters.
            period_map: JSON string of {raw_label: canonical_label} mapping.
            deduplicate: Remove extraction duplicates (default: True).
            entity_whitelist: JSON array of party names to keep.
            exclude_account_patterns: JSON array of regex patterns to exclude.
            exclude_account_names: JSON array of exact account names to exclude.

        Returns:
            JSON string with curation report: views created, row counts
            before/after, actions taken.
        """
        db = self._require_db()
        from skills.shared.data_inspector import profile_database
        from skills.shared.data_curator import auto_curate, curate, CurationConfig

        if auto:
            profile = profile_database(db)
            profile_dict = profile.to_dict()
            if period_map:
                profile_dict["periods"]["suggested_map"] = json.loads(period_map)
            if entity_whitelist:
                profile_dict["related_parties"]["suggested_whitelist"] = json.loads(entity_whitelist)
            if exclude_account_names:
                profile_dict["accounts"]["garbage_names"] = json.loads(exclude_account_names)
            result = auto_curate(db, profile_dict)
        else:
            config = CurationConfig(
                period_map=json.loads(period_map) if period_map else None,
                deduplicate=deduplicate,
                entity_whitelist=json.loads(entity_whitelist) if entity_whitelist else None,
                exclude_account_patterns=json.loads(exclude_account_patterns) if exclude_account_patterns else None,
                exclude_account_names=json.loads(exclude_account_names) if exclude_account_names else None,
            )
            result = curate(db, config)

        return json.dumps(result.to_dict(), indent=2, default=str)

    # ══════════════════════════════════════════════════════════════════════
    # FORENSIC SKILL TOOLS
    # ══════════════════════════════════════════════════════════════════════

    def run_benfords_analysis(
        self,
        table: str = "",
        column: str = "amount",
        tests: str = "all",
        filter_sql: str = "",
        case_id: str = "",
    ) -> str:
        """Run Benford's Law digit-frequency analysis on financial data.

        Tests conformity of leading/trailing digit distributions to detect
        potential data manipulation. Available tests: first_digit, second_digit,
        first_two, last_two, summation, or 'all'.

        Args:
            table: DuckDB table to analyze. Leave empty to auto-resolve.
            column: Numeric column to test (default: amount).
            tests: Comma-separated test names or 'all'.
            filter_sql: Optional SQL WHERE clause to filter data.
            case_id: Optional case identifier for audit trail.

        Returns:
            JSON string with test results, verdicts, flagged digits, risk score,
            and investigation suggestions.
        """
        if not table:
            table = self._line_items_table()

        script = _PROJECT_ROOT / "skills/benfords-analysis/scripts/benfords.py"
        args = [
            "--db", self._require_db(),
            "--table", table,
            "--column", column,
            "--tests", tests,
        ]
        if filter_sql:
            args.extend(["--filter", filter_sql])
        if case_id:
            args.extend(["--case-id", case_id])

        out = self.output_dir / "benfords_agent.json"
        result = _run_skill_script(script, args, out)
        return json.dumps(result, indent=2, default=str)

    def run_duplicate_detector(
        self,
        table: str = "",
        tolerance: float = 0.01,
        fuzzy_threshold: int = 85,
        filter_sql: str = "",
        case_id: str = "",
    ) -> str:
        """Detect exact, near-amount, fuzzy-name, and cross-period duplicate entries.

        Args:
            table: DuckDB table. Leave empty to auto-resolve.
            tolerance: Near-amount tolerance as fraction (default: 0.01 = 1%).
            fuzzy_threshold: Minimum rapidfuzz score for fuzzy name match.
            filter_sql: Optional SQL WHERE clause.
            case_id: Optional case identifier.

        Returns:
            JSON string with duplicate findings, round-number analysis,
            risk score, and investigation suggestions.
        """
        if not table:
            table = self._line_items_table()

        script = _PROJECT_ROOT / "skills/duplicate-detector/scripts/duplicate_detector.py"
        args = [
            "--db", self._require_db(),
            "--table", table,
            "--tolerance", str(tolerance),
            "--fuzzy-threshold", str(fuzzy_threshold),
        ]
        if filter_sql:
            args.extend(["--filter", filter_sql])
        if case_id:
            args.extend(["--case-id", case_id])

        out = self.output_dir / "duplicates_agent.json"
        result = _run_skill_script(script, args, out)
        return json.dumps(result, indent=2, default=str)

    def run_ratio_analyzer(
        self,
        table: str = "",
        change_threshold: float = 0.20,
        filter_sql: str = "",
        case_id: str = "",
    ) -> str:
        """Compute financial ratios and flag anomalous year-on-year changes.

        Args:
            table: DuckDB table. Leave empty to auto-resolve.
            change_threshold: Flag ratio changes above this (default: 0.20).
            filter_sql: Optional SQL WHERE clause.
            case_id: Optional case identifier.

        Returns:
            JSON string with ratios by period, YoY growth, flagged changes,
            risk score, and investigation suggestions.
        """
        if not table:
            table = self._line_items_table()

        script = _PROJECT_ROOT / "skills/ratio-analyzer/scripts/ratio_analyzer.py"
        args = [
            "--db", self._require_db(),
            "--table", table,
            "--change-threshold", str(change_threshold),
        ]
        if filter_sql:
            args.extend(["--filter", filter_sql])
        if case_id:
            args.extend(["--case-id", case_id])

        out = self.output_dir / "ratios_agent.json"
        result = _run_skill_script(script, args, out)
        return json.dumps(result, indent=2, default=str)

    def run_anomaly_detector(
        self,
        table: str = "",
        column: str = "amount",
        contamination: float = 0.05,
        filter_sql: str = "",
        case_id: str = "",
    ) -> str:
        """Run unsupervised anomaly detection (IQR, Z-score, Isolation Forest).

        Args:
            table: DuckDB table. Leave empty to auto-resolve.
            column: Numeric column (default: amount).
            contamination: IForest contamination parameter (default: 0.05).
            filter_sql: Optional SQL WHERE clause.
            case_id: Optional case identifier.

        Returns:
            JSON string with per-method results, anomaly records,
            risk score, and investigation suggestions.
        """
        if not table:
            table = self._line_items_table()

        script = _PROJECT_ROOT / "skills/anomaly-detector/scripts/anomaly_detector.py"
        args = [
            "--db", self._require_db(),
            "--table", table,
            "--column", column,
            "--contamination", str(contamination),
        ]
        if filter_sql:
            args.extend(["--filter", filter_sql])
        if case_id:
            args.extend(["--case-id", case_id])

        out = self.output_dir / "anomalies_agent.json"
        result = _run_skill_script(script, args, out)
        return json.dumps(result, indent=2, default=str)

    def run_network_analyzer(
        self,
        table: str = "",
        filter_sql: str = "",
        case_id: str = "",
    ) -> str:
        """Analyze related-party entity network for hidden connections.

        Args:
            table: DuckDB table/view for related parties. Leave empty to
                   auto-resolve.
            filter_sql: Optional SQL WHERE clause.
            case_id: Optional case identifier.

        Returns:
            JSON string with graph stats, nodes, edges, communities, cycles,
            hubs, risk score, and investigation suggestions.
        """
        if not table:
            table = self._related_parties_table()

        script = _PROJECT_ROOT / "skills/network-analyzer/scripts/network_analyzer.py"
        args = ["--db", self._require_db(), "--table", table]
        if filter_sql:
            args.extend(["--filter", filter_sql])
        if case_id:
            args.extend(["--case-id", case_id])

        out = self.output_dir / "network_agent.json"
        result = _run_skill_script(script, args, out)
        return json.dumps(result, indent=2, default=str)

    # ══════════════════════════════════════════════════════════════════════
    # RAG / KNOWLEDGE GRAPH TOOLS
    # ══════════════════════════════════════════════════════════════════════

    async def search_knowledge_graph(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 60,
    ) -> str:
        """Search the indexed documents using the LightRAG knowledge graph.

        Use this for factual Q&A about document contents — revenue figures,
        disclosures, specific notes, policy details, compliance language.

        Args:
            query: The search query.
            mode: Search mode — 'local', 'global', 'hybrid', 'mix', or 'naive'.
                  'hybrid' (default) combines local entity matching with global
                  document-level context.
            top_k: Number of results to retrieve.

        Returns:
            Search results as text.
        """
        client = await self._get_rag_client()
        return await client.query(query, mode=mode, top_k=top_k)

    async def upload_document(
        self,
        file_path: str,
        preprocessor_override: str | None = None,
    ) -> str:
        """Upload and index a document into the knowledge graph.

        For RAG-only indexing (no DuckDB/forensic skills). Use run_pipeline
        for dual indexing.

        Args:
            file_path: Path to document (PDF, XLSX, DOCX, CSV, etc.)
            preprocessor_override: Force 'docling', 'mistral', 'pandas'.

        Returns:
            Status message with character count.
        """
        path = self._resolve_path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        router = self._get_router()
        result = await router.process(str(path), override=preprocessor_override)
        text = result.get("text", "")

        if not text.strip():
            return f"Warning: No text extracted from '{path.name}'."

        client = await self._get_rag_client()
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

    async def list_indexed_documents(self) -> str:
        """List all documents currently indexed in the knowledge graph.

        Returns:
            JSON string with document info.
        """
        storage = Path(self.rag_storage_path)
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

    # ══════════════════════════════════════════════════════════════════════
    # COMPLIANCE TOOLS
    # ══════════════════════════════════════════════════════════════════════

    async def run_compliance_check(self) -> str:
        """Run the full 5-phase compliance checking pipeline.

        Phases: 0=Profile, 1=Atomise, 2=Retrieve, 3=Adjudicate, 4=Report.

        Returns:
            Summary with overall compliance score.
        """
        from skills.shared.lightrag_init import ensure_output_dir
        out_dir = ensure_output_dir()
        out_str = str(out_dir)
        storage = self.rag_storage_path

        results = {}
        for phase_num in range(5):
            try:
                await self._run_single_phase(phase_num, storage, out_str)
                results[f"phase_{phase_num}"] = "completed"
            except Exception as e:
                results[f"phase_{phase_num}"] = f"error: {e}"
                return (
                    f"Pipeline failed at phase {phase_num}: {e}\n"
                    f"Results so far: {json.dumps(results)}"
                )

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

    async def run_compliance_phase(self, phase: int) -> str:
        """Run a single compliance checking phase.

        Args:
            phase: Phase number (0=Profile, 1=Atomise, 2=Retrieve,
                   3=Adjudicate, 4=Report).

        Returns:
            Phase result summary.
        """
        if phase not in _PHASE_MAP:
            return f"Error: Invalid phase {phase}. Must be 0-4."

        from skills.shared.lightrag_init import ensure_output_dir
        out_dir = ensure_output_dir()
        try:
            await self._run_single_phase(phase, self.rag_storage_path, str(out_dir))
            return f"Phase {phase} completed. Output saved to: {out_dir}"
        except Exception as e:
            return f"Phase {phase} failed: {e}"

    async def _run_single_phase(
        self, phase_num: int, storage: str, output_dir: str
    ) -> Any:
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

    async def get_compliance_report(self) -> str:
        """Read the latest compliance report.

        Returns:
            The compliance report in markdown format, or a message if not found.
        """
        from skills.shared.lightrag_init import ensure_output_dir
        out_dir = ensure_output_dir()

        md_path = out_dir / "compliance_report.md"
        if md_path.exists():
            return md_path.read_text(encoding="utf-8")

        json_path = out_dir / "compliance_report.json"
        if json_path.exists():
            with open(json_path, "r") as f:
                report = json.load(f)
            return json.dumps(report, indent=2)

        return "No compliance report found. Run the compliance check first."


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Forensic Accounting Investigator. You help analysts investigate
financial data for fraud, manipulation, anomalies, and compliance violations.
You maintain investigation context across the conversation and build on
previous findings.

## Your Capabilities

You have TWO data backends:
1. **DuckDB** — structured financial data (line items, amounts, periods,
   related parties). Use for: forensic skills (Benford's, duplicates, ratios,
   anomalies, network), SQL queries, quantitative analysis.
2. **LightRAG Knowledge Graph** — full document text indexed with entity and
   relation extraction. Use for: factual Q&A ("what is the CSR expenditure?"),
   document search, compliance checking, finding specific disclosures or notes.

## How to Route Questions

| User asks... | You use... |
|---|---|
| Factual question about the document | search_knowledge_graph (mode: hybrid) |
| "Are there suspicious duplicates?" | run_duplicate_detector |
| "Run Benford's test" | run_benfords_analysis |
| "Check financial ratios" | run_ratio_analyzer |
| "Find outliers / anomalies" | run_anomaly_detector |
| "Analyze related-party network" | run_network_analyzer |
| "Run compliance check" | run_compliance_check |
| "Analyze this PDF" / document upload | run_pipeline (dual-index) |
| "What's the overall risk?" | Synthesize from skills already run |
| Specific account/amount query | DuckDB SQL query |

## Investigation Methodology

### When starting with new data:
1. **inspect_database()** — understand what you have (row counts, periods, quality)
2. **curate_dataset(auto=True)** if inspector says needs_curation — clean the data
3. Choose relevant skills based on data contents
4. Cross-reference findings across skills
5. Synthesize and advise the analyst

### Cross-referencing patterns (flag as HIGH significance):
- Benford's anomaly + duplicate in same account → likely manipulation
- Network hub + anomalous amounts → investigate for fund routing
- Period ratio changes + new related parties → possible relationship-driven manipulation
- Compliance violation + matching financial anomaly → evidence convergence

## Database Tables

Raw tables (from normalization):
  - source_tables: metadata about each ingested document/table
  - line_items: normalized financial line items (account_name, amount, period, etc.)
  - related_parties: related-party transaction records
  - analysis_results: stored analysis outputs

Curated views (after curation, if available):
  - curated_line_items: deduplicated, period-consolidated, garbage-filtered
  - curated_related_parties: entity-whitelisted, period-consolidated

## Conversation Behavior

- You REMEMBER this session. Build on findings, don't repeat work.
- When asked "what have you found?", synthesize everything from this session.
- If a question is vague, use your accumulated context to give a targeted answer.
- Ask clarifying questions when investigation direction is ambiguous.
- Always cite specific numbers, risk scores, and flagged items.
- When the user uploads a document, suggest running the pipeline for dual indexing.

## Session State

Track your progress:
- investigation_stage: new → inspected → curated → analyzing → synthesizing
- skills_run: which analyses you've completed
- key_findings: significant results to reference later

## Guidelines

- Always explain findings in plain English with specific numbers and risk scores.
- Suggest next investigation steps based on results.
- Be precise — cite exact values from the analysis.
- When the user asks to "run all tests" or "sweep", inspect and curate first,
  then run all 5 analysis skills.
- For compliance questions, prefer search_knowledge_graph first (faster),
  escalate to run_compliance_check for formal assessment.
"""


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def build_forensic_agent(
    db_path: str | None = None,
    rag_storage_path: str | None = None,
    output_dir: str | None = None,
    model_provider: str | None = None,
    model_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> Agent:
    """Create a fully-configured Agno Agent with forensic skills, RAG,
    compliance tools, SQLite persistence, memory, and reasoning.

    Parameters
    ----------
    db_path : str | None
        Path to the forensic DuckDB database.  Optional — agent can work
        without one (RAG-only Q&A) until a pipeline run creates one.
    rag_storage_path : str | None
        Path to LightRAG storage directory.
    output_dir : str | None
        Directory for skill JSON outputs.
    model_provider, model_id : str | None
        Override model config (defaults from env vars / model_config_agno.py).
    session_id : str | None
        Resume an existing session.  If None, Agno creates a new one.
    user_id : str | None
        User identifier for memory isolation.
    """
    # Ensure data directory exists
    _AGENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    model = get_agent_model(provider=model_provider, model_id=model_id)
    agent_db = SqliteDb(db_file=str(_AGENT_DB_PATH))

    toolkit = ForensicToolkit(
        db_path=db_path,
        rag_storage_path=rag_storage_path,
        output_dir=output_dir,
    )

    tools: list = [toolkit]
    if db_path:
        duckdb_tools = DuckDbTools(db_path=db_path, read_only=True)
        tools.append(duckdb_tools)

    agent = Agent(
        name="ForensicAnalyst",
        model=model,
        tools=tools,
        instructions=_SYSTEM_PROMPT,

        # Persistence — SQLite for sessions + memory
        session_id=session_id,
        user_id=user_id or "default",
        db=agent_db,

        # History — agent sees last 3 runs of conversation
        add_history_to_context=True,
        num_history_runs=3,

        # Session summaries off — saves an LLM call per turn.
        # History context (last 3 runs) provides sufficient continuity.
        enable_session_summaries=False,

        # Session state — tracks investigation progress
        session_state={
            "investigation_stage": "new",
            "skills_run": [],
            "key_findings": [],
            "db_path": db_path,
        },
        add_session_state_to_context=True,

        # Memory — cross-session learnings (read existing, don't auto-update
        # every turn — that adds an extra LLM call per message)
        memory_manager=MemoryManager(model=model, db=agent_db),
        enable_agentic_memory=True,
        update_memory_on_run=False,
        add_memories_to_context=True,

        # Reasoning off by default — the model reasons natively.
        # Enable per-run with agent.run(prompt, reasoning=True) for complex queries.
        reasoning=False,

        markdown=True,
        add_datetime_to_context=True,
    )

    return agent
