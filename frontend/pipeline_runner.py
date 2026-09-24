"""
Pipeline Runner — programmatic wrapper around Extract → Normalize → Skill Sweep.

Called by the Streamlit app to run the full pipeline on uploaded documents.
Returns paths to the DuckDB database and skill output JSON files.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure project root is importable
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def default_output_dir() -> Path:
    """Where pipeline runs write DuckDB, table caches and skill JSON.

    Defaults to pipeline/test_output; override with FORENSIC_OUTPUT_DIR.
    """
    return Path(os.environ.get("FORENSIC_OUTPUT_DIR") or _PROJECT_ROOT / "pipeline" / "test_output")


@dataclass
class PipelineResult:
    """Holds paths and status for a completed pipeline run."""

    db_path: Path | None = None
    skill_outputs: dict[str, Path] = field(default_factory=dict)
    skill_statuses: dict[str, str] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    success: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Skill definitions (mirrors _run_skills in test_normalization.py)
# ---------------------------------------------------------------------------

def _skill_commands(db_path: str, output_dir: Path, curated: bool = False) -> list[dict[str, Any]]:
    """Return skill definitions with CLI args for the sweep.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB database.
    output_dir : Path
        Directory for skill JSON outputs.
    curated : bool
        If True, route line_items skills to curated_line_items and
        network analyzer to curated_related_parties.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    li_table = "curated_line_items" if curated else "line_items"
    rp_table = "curated_related_parties" if curated else "related_parties"

    return [
        {
            "name": "benfords-analysis",
            "script": _PROJECT_ROOT / "skills/benfords-analysis/scripts/benfords.py",
            "output": output_dir / "benfords.json",
            "args": [
                "--db", db_path,
                "--table", li_table,
                "--column", "amount",
                "--tests", "all",
            ],
        },
        {
            "name": "duplicate-detector",
            "script": _PROJECT_ROOT / "skills/duplicate-detector/scripts/duplicate_detector.py",
            "output": output_dir / "duplicates.json",
            "args": ["--db", db_path, "--table", li_table],
        },
        {
            "name": "ratio-analyzer",
            "script": _PROJECT_ROOT / "skills/ratio-analyzer/scripts/ratio_analyzer.py",
            "output": output_dir / "ratios.json",
            "args": ["--db", db_path, "--table", li_table],
        },
        {
            "name": "anomaly-detector",
            "script": _PROJECT_ROOT / "skills/anomaly-detector/scripts/anomaly_detector.py",
            "output": output_dir / "anomalies.json",
            "args": [
                "--db", db_path,
                "--table", li_table,
                "--column", "amount",
            ],
        },
        {
            "name": "network-analyzer",
            "script": _PROJECT_ROOT / "skills/network-analyzer/scripts/network_analyzer.py",
            "output": output_dir / "network.json",
            "args": ["--db", db_path, "--table", rp_table],
        },
    ]


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_tables(file_paths: list[Path], extractor: str, max_pages: int | None):
    """Extract tables from files using the specified backend."""
    if extractor == "mistral":
        from pipeline.mistral_extractor import MistralTableExtractor

        ext = MistralTableExtractor()
        all_tables = []
        for fp in file_paths:
            if fp.suffix.lower() == ".pdf":
                all_tables.extend(ext.extract(fp, max_pages=max_pages))
            else:
                from pipeline.test_normalization import extract_tables as _fallback
                all_tables.extend(_fallback(fp))
        return all_tables

    # docling / fallback
    from pipeline.test_normalization import extract_tables as _fallback
    all_tables = []
    for fp in file_paths:
        all_tables.extend(_fallback(fp))
    return all_tables


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_pipeline(
    file_paths: list[Path],
    *,
    extractor: str = "mistral",
    from_cache: bool = False,
    max_pages: int | None = None,
    entity_name: str = "Unknown",
    fiscal_year: str = "Unknown",
    output_dir: Path | None = None,
    case_id: str | None = None,
    on_progress: Any = None,
) -> PipelineResult:
    """Run the full Extract → Normalize → Skill Sweep pipeline.

    Parameters
    ----------
    file_paths : list[Path]
        Documents to process.
    extractor : str
        "mistral" or "docling".
    from_cache : bool
        If True, load tables from pickle cache instead of extracting.
    entity_name, fiscal_year : str
        Passed to the normalizer.
    output_dir : Path | None
        Where to write DuckDB and skill JSON.  Defaults to
        ``default_output_dir()`` (pipeline/test_output or FORENSIC_OUTPUT_DIR).
    case_id : str | None
        Case ID for audit trail.
    on_progress : callable | None
        Called with (step_name: str, detail: str) for UI updates.

    Returns
    -------
    PipelineResult
    """
    result = PipelineResult()
    _out = Path(output_dir) if output_dir else default_output_dir()
    _out.mkdir(parents=True, exist_ok=True)

    suffix = "_mistral" if extractor == "mistral" else ""
    db_path = _out / f"test_forensic{suffix}.duckdb"
    cache_path = _out / f"extracted_tables{suffix}.pkl"

    def _log(msg: str):
        result.logs.append(msg)
        if on_progress:
            on_progress("log", msg)

    # ── Step 1: Extract ──────────────────────────────────────────────────
    try:
        if from_cache and cache_path.exists():
            _log(f"Loading cached tables from {cache_path.name}")
            if on_progress:
                on_progress("extract", "Loading from cache...")
            with open(cache_path, "rb") as f:
                all_tables = pickle.load(f)
            _log(f"Loaded {len(all_tables)} table(s) from cache")
        else:
            _log(f"Extracting tables ({extractor})...")
            if on_progress:
                on_progress("extract", f"Extracting with {extractor}...")
            all_tables = _extract_tables(file_paths, extractor, max_pages)
            # Cache for future runs
            with open(cache_path, "wb") as f:
                pickle.dump(all_tables, f)
            _log(f"Extracted and cached {len(all_tables)} table(s)")

        if not all_tables:
            result.error = "No tables extracted from the uploaded documents."
            return result
    except Exception as exc:
        result.error = f"Extraction failed: {exc}"
        return result

    # ── Step 2: Normalize ────────────────────────────────────────────────
    try:
        if on_progress:
            on_progress("normalize", "Normalizing into DuckDB...")
        _log("Initializing normalizer...")

        # Remove stale DB
        if db_path.exists():
            db_path.unlink()

        from pipeline.data_normalizer import DataNormalizer

        normalizer = DataNormalizer(db_path=str(db_path))
        normalizer.initialize_schema()

        norm_result = normalizer.normalize_and_load(
            all_tables,
            entity_name=entity_name,
            fiscal_year=fiscal_year,
        )
        normalizer.close()

        _log(
            f"Normalized: {norm_result.line_items_loaded} line items, "
            f"{norm_result.related_parties_loaded} related parties"
        )
        result.db_path = db_path
    except Exception as exc:
        result.error = f"Normalization failed: {exc}"
        return result

    # ── Step 2.5: Auto-Curate ───────────────────────────────────────────
    curated = False
    try:
        if on_progress:
            on_progress("curate", "Inspecting and curating data...")
        _log("Running data quality inspection...")

        from skills.shared.data_inspector import profile_database
        from skills.shared.data_curator import auto_curate, has_curated_views

        profile = profile_database(str(db_path))
        if profile.needs_curation:
            _log(f"Issues found: {'; '.join(profile.issues)}")
            _log("Auto-curating: creating clean views...")
            curation_result = auto_curate(str(db_path), profile.to_dict())
            for action in curation_result.actions:
                _log(f"  Curation: {action}")
            curated = has_curated_views(str(db_path))
            _log(f"Curated views ready: {curated}")
        else:
            _log("Data quality OK — no curation needed")
    except Exception as exc:
        _log(f"Auto-curation failed (non-fatal, skills will use raw tables): {exc}")

    # ── Step 3: Skill Sweep ──────────────────────────────────────────────
    if on_progress:
        on_progress("skills", "Running forensic skill sweep...")

    skill_output_dir = _out / "skill_results"
    skills = _skill_commands(str(db_path), skill_output_dir, curated=curated)

    for skill in skills:
        script = skill["script"]
        if not script.exists():
            result.skill_statuses[skill["name"]] = "SKIP (script not found)"
            continue

        _log(f"Running {skill['name']}...")
        if on_progress:
            on_progress("skills", f"Running {skill['name']}...")

        cmd = [
            sys.executable, str(script),
            *skill["args"],
            "--output", str(skill["output"]),
        ]
        if case_id:
            cmd.extend(["--case-id", case_id])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                cwd=str(_PROJECT_ROOT),
            )
            if proc.returncode == 0:
                result.skill_statuses[skill["name"]] = "OK"
                result.skill_outputs[skill["name"]] = skill["output"]
                _log(f"  {skill['name']}: OK")
            else:
                stderr_tail = (proc.stderr or "").strip().split("\n")[-3:]
                result.skill_statuses[skill["name"]] = f"FAILED (exit {proc.returncode})"
                _log(f"  {skill['name']}: FAILED — {' '.join(stderr_tail)}")
        except subprocess.TimeoutExpired:
            result.skill_statuses[skill["name"]] = "TIMEOUT"
            _log(f"  {skill['name']}: TIMEOUT")
        except Exception as exc:
            result.skill_statuses[skill["name"]] = f"ERROR: {exc}"
            _log(f"  {skill['name']}: ERROR — {exc}")

    result.success = result.db_path is not None
    if on_progress:
        on_progress("done", "Pipeline complete.")
    return result
