"""
Live end-to-end run against the real Mistral and Gemini APIs.

Deselected by default and skipped unless MISTRAL_API_KEY and GEMINI_API_KEY are
set (environment or project .env). Run with:

    pytest -m e2e

API usage is kept small: one short fictional document, one query and a
single law section for the compliance pipeline.
"""

from __future__ import annotations

import json
import os

import pytest

from conftest import QUERY_SCRIPT, load_phase, load_script

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

REQUIRED_KEYS = ("MISTRAL_API_KEY", "GEMINI_API_KEY")


@pytest.fixture(scope="module", autouse=True)
def live_keys():
    import skills.shared.lightrag_init  # noqa: F401  (loads the project .env)

    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        pytest.skip(f"live test needs {', '.join(missing)}")


async def test_ingest_query_and_compliance(sample_md, tmp_path, monkeypatch):
    from lightrag.kg.shared_storage import finalize_share_data
    from skills.shared import lightrag_init
    from skills.shared.preprocessors import PreprocessingRouter

    finalize_share_data()
    storage = tmp_path / "rag_storage"
    out_dir = tmp_path / "outputs"

    # 1. Ingest
    text = (await PreprocessingRouter().process(str(sample_md)))["text"]
    rag = await lightrag_init.get_rag_instance(storage)
    await rag.ainsert(text, file_paths=sample_md.name)
    await rag.finalize_storages()

    status = json.loads((storage / "kv_store_doc_status.json").read_text())
    doc = next(iter(status.values()))
    assert doc["status"] == "processed", doc.get("error_msg")

    # 2. Query
    query = load_script(QUERY_SCRIPT, "query_cli_live")
    answer = await query.run_query(
        "What was the revenue from operations of Acme Widgets for FY 2024-25?",
        mode="hybrid", storage=str(storage),
    )
    assert "850" in answer["result"]

    # 3. Compliance pipeline on a single law section
    full = lightrag_init.get_laws_data()
    monkeypatch.setattr(lightrag_init, "_laws_data", {
        "metadata": dict(full["metadata"], categories=["Income Tax Act, 1961"]),
        "income_tax_act_1961": {"section_269SS": full["income_tax_act_1961"]["section_269SS"]},
    })
    run_pipeline = load_phase("run_pipeline")
    report = await run_pipeline.run_pipeline(
        storage=str(storage), output_dir=str(out_dir), max_concurrent=2,
    )

    assert (out_dir / "compliance_report.md").exists()
    questions = json.loads((out_dir / "atomic_questions.json").read_text())
    assert sum(report["overall"]["totals"].values()) == len(questions)
