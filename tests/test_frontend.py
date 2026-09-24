"""Tests for the Streamlit frontend: dashboards, the agent toolkit and an app smoke test.

No LLM is called: the chat test swaps build_forensic_agent for a scripted fake
that streams Agno events, and the other tests only construct the agent.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("agno")

from conftest import PROJECT_ROOT  # noqa: E402
from frontend import forensic_agent as fa  # noqa: E402
from frontend import viz_helpers as vh  # noqa: E402

APP = str(PROJECT_ROOT / "frontend" / "app.py")
COMPANY = "Acme Widgets Private Limited"


@pytest.fixture
def skill_data(pipeline_run) -> dict:
    return {name: vh.load_skill_json(path) for name, path in pipeline_run.skill_outputs.items()}


@pytest.fixture
def agent_db(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "agent" / "forensic_agent.db"
    monkeypatch.setattr(fa, "_AGENT_DB_PATH", path)
    return path


def _arrow_ok(df: pd.DataFrame) -> bool:
    import pyarrow as pa

    pa.Table.from_pandas(df)
    return True


# ---------------------------------------------------------------------------
# Visualisation helpers
# ---------------------------------------------------------------------------
def test_dashboard_figures_and_tables(skill_data):
    benford = skill_data["benfords-analysis"]
    fig = vh.benford_chart(benford, "first_digit")
    assert [t.name for t in fig.data] == ["Observed", "Expected (Benford)"]
    assert list(fig.data[0].x) == [str(d) for d in range(1, 10)]
    assert vh.benford_chart(benford, "no_such_test") is None
    assert _arrow_ok(vh.benford_summary_table(benford))

    dups = skill_data["duplicate-detector"]
    summary = vh.duplicate_summary_table(dups)
    assert _arrow_ok(summary)
    assert summary.set_index("Metric").loc["Fuzzy-Name Matches", "Value"] == "1"
    assert vh.duplicate_details_table(dups, "fuzzy_name_duplicates").shape[0] == 1

    ratios = skill_data["ratio-analyzer"]
    assert vh.ratio_bar_chart(ratios) is not None
    yoy = vh.ratio_yoy_table(ratios)
    assert "Revenue" in yoy["Category"].tolist()

    anomalies = skill_data["anomaly-detector"]
    assert vh.anomaly_scatter(anomalies) is not None
    assert "CONSENSUS" in vh.anomaly_summary_table(anomalies)["Method"].tolist()

    network = skill_data["network-analyzer"]
    graph = vh.network_graph_plotly(network)
    assert len(graph.data[1].x) == 6  # one marker per entity
    stats = vh.network_stats_table(network)
    assert _arrow_ok(stats)
    assert stats.set_index("Metric").loc["Nodes", "Value"] == "6"

    for data in skill_data.values():
        overview = vh.render_skill_overview(data)
        assert 1 <= overview["risk_score"] <= 10


def test_dashboard_helpers_tolerate_errors_and_empty_outputs():
    errored = {"tests": {"first_digit": {"test_name": "first_digit", "error": "No valid digits extracted"}}}
    assert vh.benford_chart(errored, "first_digit") is None
    table = vh.benford_summary_table(errored)
    assert list(table.columns) == ["Test", "Verdict", "MAD", "p-value", "Flagged Digits"]
    assert vh.ratio_bar_chart({}) is None and vh.ratio_yoy_table({}) is None
    assert vh.anomaly_scatter({"anomalies": []}) is None
    assert vh.network_graph_plotly({"nodes": []}) is None
    assert vh.risk_badge(8, "Risk").count("#e74c3c") == 1


# ---------------------------------------------------------------------------
# Agent toolkit and factory
# ---------------------------------------------------------------------------
def test_toolkit_runs_skills_and_curation(forensic_db_copy, tmp_path):
    toolkit = fa.ForensicToolkit(db_path=str(forensic_db_copy), output_dir=str(tmp_path / "out"))

    assert toolkit._line_items_table() == "line_items"
    profile = json.loads(toolkit.inspect_database())
    assert profile["needs_curation"] is True

    curated = json.loads(toolkit.curate_dataset(auto=True))
    assert curated["views_created"] == ["curated_line_items", "curated_related_parties"]
    assert toolkit._line_items_table() == "curated_line_items"
    assert toolkit._related_parties_table() == "curated_related_parties"

    dups = json.loads(toolkit.run_duplicate_detector(case_id="ACME-TEST"))
    assert dups["meta"]["table"] == "curated_line_items"
    assert dups["meta"]["case_id"] == "ACME-TEST"

    ratios = json.loads(toolkit.run_ratio_analyzer(
        filter_sql="table_id IN (SELECT table_id FROM source_tables WHERE table_type = 'profit_and_loss')",
    ))
    assert ratios["meta"]["periods_found"] == ["FY 2023-24", "FY 2024-25"]

    network = json.loads(toolkit.run_network_analyzer())
    assert network["graph_stats"]["n_nodes"] == 6

    anomalies = json.loads(toolkit.run_anomaly_detector())
    assert anomalies["anomalies"][0]["account_name"] == "Consultancy - Sample Advisors LLP"

    benford = json.loads(toolkit.run_benfords_analysis(tests="first_digit"))
    assert benford["tests"]["first_digit"]["verdict"] == "CONFORMING"

    # A failing skill comes back as an error payload rather than an exception
    missing = json.loads(toolkit.run_benfords_analysis(table="no_such_table"))
    assert "error" in missing and "TABLE_NOT_FOUND" in missing["stderr"]

    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "anomalies_agent.json", "benfords_agent.json", "duplicates_agent.json",
        "network_agent.json", "ratios_agent.json",
    ]


def test_toolkit_without_a_database(tmp_path):
    toolkit = fa.ForensicToolkit(output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="No database loaded"):
        toolkit.run_duplicate_detector()
    missing = json.loads(toolkit.run_pipeline(str(tmp_path / "missing.pdf")))
    assert missing["error"].startswith("File not found")


async def test_toolkit_lists_indexed_documents(tmp_path):
    toolkit = fa.ForensicToolkit(rag_storage_path=tmp_path, output_dir=str(tmp_path / "out"))
    assert await toolkit.list_indexed_documents() == "No documents indexed yet."
    (tmp_path / "kv_store_full_docs.json").write_text(
        json.dumps({"doc-1": {"content": "Acme Widgets Private Limited annual report"}})
    )
    docs = json.loads(await toolkit.list_indexed_documents())
    assert docs[0]["doc_id"] == "doc-1"


def test_build_forensic_agent_offline(forensic_db, agent_db, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "google")
    agent = fa.build_forensic_agent(
        db_path=str(forensic_db), output_dir=str(tmp_path / "out"), session_id="acme-session",
    )

    assert agent.name == "ForensicAnalyst"
    assert agent.session_id == "acme-session"
    assert [type(t).__name__ for t in agent.tools] == ["ForensicToolkit", "DuckDbTools"]
    assert agent.session_state["db_path"] == str(forensic_db)
    assert agent_db.parent.is_dir()

    rag_only = fa.build_forensic_agent(output_dir=str(tmp_path / "out"))
    assert [type(t).__name__ for t in rag_only.tools] == ["ForensicToolkit"]


def test_agent_db_path_from_environment(tmp_path):
    target = tmp_path / "sessions.db"
    proc = subprocess.run(
        [sys.executable, "-c", "import frontend.forensic_agent as fa; print(fa._AGENT_DB_PATH)"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
        env={**__import__("os").environ, "FORENSIC_AGENT_DB": str(target)},
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert proc.stdout.strip().splitlines()[-1] == str(target)


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------
def _app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=120)


def test_app_starts_without_data(agent_db):
    pytest.importorskip("streamlit")
    at = _app()
    at.run()

    assert not at.exception
    assert [t.label for t in at.tabs] == [
        "Chat", "Benford's", "Duplicates", "Ratios", "Anomalies", "Network", "Logs",
    ]
    assert "No Benford's analysis results. Run the pipeline or load a DB." in [i.value for i in at.info]
    run_button = next(b for b in at.sidebar.button if b.label == "Run Full Pipeline")
    assert run_button.disabled  # nothing uploaded yet


def test_app_loads_an_existing_database(agent_db, pipeline_run):
    pytest.importorskip("streamlit")
    at = _app()
    at.run()
    next(t for t in at.sidebar.text_input if t.label == "Path to DuckDB file").set_value(
        str(pipeline_run.db_path)
    )
    next(b for b in at.sidebar.button if b.label == "Load Existing DB").click()
    at.run()

    assert not at.exception
    assert at.session_state.db_path == str(pipeline_run.db_path)
    assert sorted(at.session_state.skill_data) == sorted(pipeline_run.skill_outputs)
    assert [m.label for m in at.metric] == ["Benford's", "Duplicates", "Ratios", "Anomalies", "Network"]
    assert len(at.get("plotly_chart")) == 4
    assert any(s.value.startswith("Loaded DB:") for s in at.success)


def test_app_lists_recent_sessions(agent_db):
    pytest.importorskip("streamlit")
    agent_db.parent.mkdir(parents=True)
    con = sqlite3.connect(agent_db)
    con.execute("CREATE TABLE agno_sessions (session_id TEXT, created_at BIGINT)")
    con.execute("INSERT INTO agno_sessions VALUES ('acme-review-0001', 1767225600)")
    con.commit()
    con.close()

    at = _app()
    at.run()
    assert not at.exception
    labels = [b.label for b in at.sidebar.button]
    assert any(label.startswith("acme-rev...") for label in labels)


def test_app_streams_the_agent_reply(agent_db, forensic_db, monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from agno.agent import (
        RunCompletedEvent,
        RunContentEvent,
        RunStartedEvent,
        ToolCallCompletedEvent,
        ToolCallStartedEvent,
    )
    from agno.models.response import ToolExecution

    prompts = []
    toolkit = fa.ForensicToolkit(db_path=str(forensic_db), output_dir=str(tmp_path))

    class ScriptedAgent:
        tools = [toolkit]

        def run(self, prompt, stream=False):
            prompts.append(prompt)
            tool = ToolExecution(tool_name="run_benfords_analysis")
            yield RunStartedEvent()
            yield ToolCallStartedEvent(tool=tool)
            yield ToolCallCompletedEvent(tool=tool)
            yield RunContentEvent(content="First-digit test ")
            yield RunContentEvent(content="conforms.")
            yield RunCompletedEvent(content="First-digit test conforms (risk 3/10).")

    built = []

    def fake_build(**kwargs):
        built.append(kwargs)
        return ScriptedAgent()

    monkeypatch.setattr(fa, "build_forensic_agent", fake_build)

    at = _app()
    at.run()
    at.chat_input[0].set_value("Run Benford's test").run()

    assert not at.exception
    assert prompts == ["Run Benford's test"]
    assert built[0]["db_path"] is None and built[0]["session_id"] == at.session_state.session_id
    assert at.session_state.messages == [
        {"role": "user", "content": "Run Benford's test"},
        {"role": "assistant", "content": "First-digit test conforms (risk 3/10)."},
    ]
    # the toolkit's database is picked up for the next turn
    assert at.session_state.db_path == str(forensic_db)


def test_app_shows_agent_errors(agent_db, monkeypatch):
    pytest.importorskip("streamlit")

    class BrokenAgent:
        tools = []

        def run(self, prompt, stream=False):
            raise RuntimeError("model quota exceeded")
            yield  # pragma: no cover

    monkeypatch.setattr(fa, "build_forensic_agent", lambda **kwargs: BrokenAgent())
    at = _app()
    at.run()
    at.chat_input[0].set_value("hello").run()

    assert not at.exception
    assert at.session_state.messages[-1] == {
        "role": "assistant", "content": "Agent error: model quota exceeded",
    }
