"""
Offline end-to-end run: ingest -> query -> compliance pipeline -> agent tools.

Uses the real LightRAG storage, the local sentence-transformers embedding model
and the real preprocessors, with the Mistral / Gemini calls replaced by the
deterministic fakes from conftest.py.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from conftest import (
    FAKE_ANSWER,
    QUERY_SCRIPT,
    FakeKGProvider,
    FakeReasoningProvider,
    load_phase,
    load_script,
)

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]


@pytest.fixture(scope="module")
def offline_llms():
    from skills.shared import llm_registry, lightrag_init

    kg, reasoning = FakeKGProvider(), FakeReasoningProvider()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(llm_registry, "_providers", {"mistral": kg, "gemini": reasoning})
        mp.setattr(lightrag_init, "_kg_provider", None)
        yield kg, reasoning

    # LightRAG keeps storage contents in process-wide shared dicts; reset them
    # so later modules start from a clean state.
    from lightrag.kg.shared_storage import finalize_share_data

    finalize_share_data()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def indexed_storage(offline_llms, tmp_path_factory, sample_md):
    from skills.shared.lightrag_init import get_rag_instance
    from skills.shared.preprocessors import PreprocessingRouter

    storage = tmp_path_factory.mktemp("rag_storage")
    result = await PreprocessingRouter().process(str(sample_md))
    rag = await get_rag_instance(storage)
    await rag.ainsert(result["text"], file_paths=sample_md.name)
    await rag.finalize_storages()
    return storage


async def test_ingest_builds_graph(indexed_storage, offline_llms):
    kg, _ = offline_llms
    assert kg.calls, "entity extraction should go through the kg_llm role"

    status = json.loads((indexed_storage / "kv_store_doc_status.json").read_text())
    assert [d["status"] for d in status.values()] == ["processed"]

    graph = (indexed_storage / "graph_chunk_entity_relation.graphml").read_text()
    assert "Acme Widgets Private Limited" in graph
    assert "Jane Doe" in graph


@pytest.mark.parametrize("mode", ["local", "global", "hybrid", "mix", "naive"])
async def test_query_cli_context_only(indexed_storage, mode):
    query = load_script(QUERY_SCRIPT, "query_cli")
    out = await query.run_query(
        "Who is the statutory auditor?", mode=mode,
        storage=str(indexed_storage), context_only=True,
    )
    assert out["mode"] == mode and out["context_only"] is True
    assert "Acme Widgets" in out["result"]


async def test_query_cli_answer(indexed_storage):
    query = load_script(QUERY_SCRIPT, "query_cli")
    out = await query.run_query(
        "What was the revenue from operations?", mode="hybrid",
        storage=str(indexed_storage),
    )
    assert out["result"] == FAKE_ANSWER


async def test_full_compliance_pipeline(indexed_storage, offline_llms, small_laws, tmp_path):
    run_pipeline = load_phase("run_pipeline")
    out_dir = tmp_path / "outputs"

    report = await run_pipeline.run_pipeline(
        storage=str(indexed_storage), output_dir=str(out_dir), max_concurrent=2,
    )

    for name in ("document_profile.json", "atomic_questions.json",
                 "retrieved_contexts.json", "verdicts.json",
                 "compliance_report.json", "compliance_report.md"):
        assert (out_dir / name).exists(), name

    profile = json.loads((out_dir / "document_profile.json").read_text())
    assert profile["applicable_category_keys"] == ["companies_act_2013", "income_tax_act_1961"]

    questions = json.loads((out_dir / "atomic_questions.json").read_text())
    assert [q["question_id"] for q in questions] == ["Q0001", "Q0002", "Q0003"]

    contexts = json.loads((out_dir / "retrieved_contexts.json").read_text())
    assert not any(c["is_empty"] for c in contexts.values())

    assert report["overall"]["totals"] == {
        "COMPLIANT": 2, "VIOLATION": 1, "INSUFFICIENT_EVIDENCE": 0,
    }
    assert report["overall"]["score_pct"] == "66.7%"
    assert report["categories"]["income_tax_act_1961"]["score"] == 0.0

    md = (out_dir / "compliance_report.md").read_text()
    assert "## Income Tax Act, 1961" in md


async def test_agent_toolkit(indexed_storage, small_laws, sample_csv, tmp_path, monkeypatch):
    from skills.shared import agent_tools
    from skills.shared.agent_tools import ForensicToolkit
    from skills.shared.lightrag_init import get_rag_instance

    out_dir = tmp_path / "outputs"
    monkeypatch.setattr(
        agent_tools, "ensure_output_dir",
        lambda output_dir=None: (out_dir.mkdir(parents=True, exist_ok=True) or out_dir),
    )
    rag = await get_rag_instance(indexed_storage)
    toolkit = ForensicToolkit(rag=rag, storage_path=indexed_storage, input_dir=tmp_path / "docs")

    assert await toolkit.search_knowledge_graph("Revenue?") == FAKE_ANSWER

    docs = json.loads(await toolkit.list_indexed_documents())
    assert len(docs) >= 1

    assert await toolkit.get_compliance_report() == (
        "No compliance report found. Run the compliance check first."
    )
    summary = await toolkit.run_compliance_check()
    assert "Overall Score: 66.7%" in summary
    assert (await toolkit.get_compliance_report()).startswith("# Compliance Report")
    assert "completed" in await toolkit.run_compliance_phase(4)
    assert "Invalid phase" in await toolkit.run_compliance_phase(7)

    msg = await toolkit.upload_document(str(sample_csv))
    assert msg.startswith("Indexed 'acme_widgets_trial_balance.csv'")
    assert len(json.loads(await toolkit.list_indexed_documents())) == len(docs) + 1


async def test_client_falls_back_to_direct(indexed_storage):
    from skills.shared.lightrag_client import LightRAGDirectClient, create_lightrag_client

    client = await create_lightrag_client(
        server_url="http://127.0.0.1:9", storage_path=indexed_storage,
    )
    assert isinstance(client, LightRAGDirectClient)
    assert (await client.health_check())["mode"] == "direct"


async def test_agent_builds_with_toolkit(indexed_storage, monkeypatch):
    agno_agent = pytest.importorskip("agno.agent")
    from skills.shared.agent_tools import ForensicToolkit
    from skills.shared.model_config_agno import get_agent_model

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    toolkit = ForensicToolkit(storage_path=indexed_storage)
    agent = agno_agent.Agent(name="Forensic Analyst", model=get_agent_model("google", "gemini-3-flash-preview"),
                             tools=[toolkit])
    assert agent.model.id == "gemini-3-flash-preview"
    assert "run_compliance_check" in toolkit.async_functions
