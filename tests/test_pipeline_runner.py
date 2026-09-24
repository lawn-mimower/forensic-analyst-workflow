"""End-to-end tests for the extract -> normalise -> curate -> skill sweep pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from conftest import PROJECT_ROOT  # noqa: E402
from frontend import pipeline_runner  # noqa: E402
from frontend.pipeline_runner import default_output_dir, run_pipeline  # noqa: E402

COMPANY = "Acme Widgets Private Limited"
SKILLS = ["benfords-analysis", "duplicate-detector", "ratio-analyzer", "anomaly-detector", "network-analyzer"]


def test_full_pipeline_on_synthetic_documents(pipeline_run):
    result = pipeline_run

    assert result.success and result.error is None
    assert result.skill_statuses == {name: "OK" for name in SKILLS}
    assert result.db_path.exists()
    assert any(line.startswith("Normalized: ") for line in result.logs)
    assert "Curated views ready: True" in result.logs

    for name, path in result.skill_outputs.items():
        data = json.loads(Path(path).read_text())
        assert data["meta"]["case_id"] == "ACME-TEST", name
        # the sweep runs on the curated views
        assert data["meta"]["table"].startswith("curated_"), name

    con = duckdb.connect(str(result.db_path), read_only=True)
    entities = con.execute("SELECT DISTINCT entity_name, fiscal_year FROM source_tables").fetchall()
    views = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    con.close()
    assert entities == [(COMPANY, "2024-25")]
    assert {"curated_line_items", "curated_related_parties"} <= views

    anomalies = json.loads(Path(result.skill_outputs["anomaly-detector"]).read_text())
    assert anomalies["anomalies"][0]["account_name"] == "Consultancy - Sample Advisors LLP"


def test_pipeline_reuses_the_table_cache(pipeline_run, forensic_docs, monkeypatch, tmp_path):
    import shutil

    cache = pipeline_run.db_path.parent / "extracted_tables.pkl"
    assert cache.exists()
    shutil.copy(cache, tmp_path / cache.name)

    def no_extraction(*args, **kwargs):
        raise AssertionError("extraction should come from the cache")

    monkeypatch.setattr(pipeline_runner, "_extract_tables", no_extraction)
    steps = []
    again = run_pipeline(
        list(forensic_docs), extractor="docling", from_cache=True,
        entity_name=COMPANY, fiscal_year="2024-25", output_dir=tmp_path,
        on_progress=lambda step, detail: steps.append(step),
    )
    assert again.success
    assert again.logs[0] == "Loading cached tables from extracted_tables.pkl"
    stages = [s for s in steps if s != "log"]
    assert stages[0] == "extract" and stages[-1] == "done"
    assert {"normalize", "curate", "skills"} <= set(stages)
    assert again.skill_statuses == pipeline_run.skill_statuses


def test_pipeline_with_mistral_backend_offline(tmp_path, offline_mistral, sample_csv):
    pdf = tmp_path / "acme_statements.pdf"
    pdf.write_bytes(b"%PDF-1.4 fictional sample")

    result = run_pipeline(
        [pdf, sample_csv], extractor="mistral",
        entity_name=COMPANY, fiscal_year="2024-25", output_dir=tmp_path / "out",
    )

    assert result.success, result.error
    assert len(offline_mistral) == 1
    assert result.db_path.name == "test_forensic_mistral.duckdb"
    con = duckdb.connect(str(result.db_path), read_only=True)
    methods = {r[0] for r in con.execute("SELECT DISTINCT extraction_method FROM source_tables").fetchall()}
    revenue = con.execute(
        "SELECT amount_inr FROM line_items WHERE account_name = 'Revenue from operations' "
        "AND period_label = 'FY 2024-25' AND source_unit = 'lakhs'"
    ).fetchone()
    parties = {r[0] for r in con.execute("SELECT party_name FROM related_parties").fetchall()}
    con.close()
    assert methods == {"mistral_ocr", "pandas_csv"}
    assert revenue == (85_000_000.0,)
    assert parties == {"Jane Doe", "Acme Holdings Private Limited"}
    # too few line items for Benford's minimum sample; the other skills run
    assert result.skill_statuses["benfords-analysis"].startswith("FAILED")
    assert result.skill_statuses["duplicate-detector"] == "OK"
    assert result.skill_statuses["network-analyzer"] == "OK"


def test_pipeline_reports_extraction_errors(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("scanner offline")

    monkeypatch.setattr(pipeline_runner, "_extract_tables", broken)
    result = run_pipeline([tmp_path / "x.pdf"], extractor="docling", output_dir=tmp_path)
    assert not result.success
    assert result.error == "Extraction failed: scanner offline"

    monkeypatch.setattr(pipeline_runner, "_extract_tables", lambda *a, **k: [])
    result = run_pipeline([tmp_path / "x.pdf"], extractor="docling", output_dir=tmp_path)
    assert result.error == "No tables extracted from the uploaded documents."


def test_default_output_dir_from_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("FORENSIC_OUTPUT_DIR", raising=False)
    assert default_output_dir() == PROJECT_ROOT / "pipeline" / "test_output"
    monkeypatch.setenv("FORENSIC_OUTPUT_DIR", str(tmp_path))
    assert default_output_dir() == tmp_path


# ---------------------------------------------------------------------------
# Command-line runners
# ---------------------------------------------------------------------------
def _run_module(module: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True, text=True, timeout=600, cwd=str(PROJECT_ROOT),
    )


def test_normalization_cli(tmp_path, forensic_docs):
    proc = _run_module(
        "pipeline.test_normalization", *map(str, forensic_docs),
        "--entity", COMPANY, "--fiscal-year", "2024-25", "--output-dir", str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Errors:              0" in proc.stdout
    assert "READY for Benford's analysis" in proc.stdout

    con = duckdb.connect(str(tmp_path / "test_forensic.duckdb"), read_only=True)
    count = con.execute("SELECT COUNT(*) FROM line_items").fetchone()[0]
    con.close()
    assert count > 250
    assert (tmp_path / "extracted_tables.pkl").exists()

    # --from-cache and --files filter
    proc = _run_module(
        "pipeline.test_normalization", "--from-cache", "--output-dir", str(tmp_path),
        "--files", "ledger",
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Loaded 4 table(s) from cache" in proc.stdout


def test_extraction_cli(tmp_path, sample_xlsx, sample_csv):
    proc = _run_module(
        "pipeline.test_extraction", str(sample_xlsx), str(sample_csv), "--output-dir", str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    manifest = json.loads((tmp_path / "extraction_manifest.json").read_text())
    assert manifest["files_processed"] == 2
    assert manifest["total_tables_extracted"] == 3
    assert [t["sheet_name"] for t in manifest["tables"]][:2] == ["Profit and Loss", "Balance Sheet"]


def test_extraction_cli_without_documents(tmp_path):
    proc = _run_module("pipeline.test_extraction", str(tmp_path / "missing.xlsx"), "--output-dir", str(tmp_path))
    assert proc.returncode == 1
    assert "No test files found" in proc.stdout
