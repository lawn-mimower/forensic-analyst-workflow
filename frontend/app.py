"""
Forensic Analyst Workflow — Streamlit Chat UI

Streaming chat with the unified ForensicAnalyst agent. Supports:
  - Dual-index pipeline (DuckDB + LightRAG)
  - Streaming tool-call visibility
  - Persistent sessions (SQLite)
  - Works with or without a DuckDB database loaded

Run with:
    streamlit run frontend/app.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env for API keys
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

from frontend.forensic_agent import (  # noqa: E402
    build_forensic_agent,
    ForensicToolkit,
    _AGENT_DB_PATH,
)
from frontend.pipeline_runner import (  # noqa: E402
    PipelineResult,
    default_output_dir,
    run_pipeline,
)
from frontend.viz_helpers import (  # noqa: E402
    anomaly_scatter,
    anomaly_summary_table,
    benford_chart,
    benford_summary_table,
    duplicate_details_table,
    duplicate_summary_table,
    load_skill_json,
    network_graph_plotly,
    network_stats_table,
    ratio_bar_chart,
    ratio_yoy_table,
    render_skill_overview,
    risk_badge,
)
from agno.agent import (  # noqa: E402
    RunEvent,
    RunContentEvent,
    RunCompletedEvent,
    RunStartedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Forensic Analyst Workflow",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "pipeline_result": None,
    "messages": [],
    "skill_data": {},
    "session_id": str(uuid.uuid4()),
    "db_path": None,
}
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _get_agent():
    """Build (or rebuild) the forensic agent with current session config."""
    return build_forensic_agent(
        db_path=st.session_state.db_path,
        session_id=st.session_state.session_id,
    )


# ---------------------------------------------------------------------------
# Sidebar — File Upload + Pipeline Controls + Session Management
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Forensic Analyst")
    st.caption(
        "Upload financial documents, run the forensic pipeline, "
        "then chat with the AI analyst."
    )

    # ── Session management ────────────────────────────────────────────────
    st.divider()
    st.subheader("Session")
    st.code(st.session_state.session_id[:8] + "...", language=None)

    col_new, col_resume = st.columns(2)
    with col_new:
        if st.button("New Investigation", width="stretch"):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.pipeline_result = None
            st.session_state.skill_data = {}
            st.session_state.db_path = None
            st.rerun()

    with col_resume:
        resume_id = st.text_input(
            "Resume session ID",
            placeholder="paste session ID",
            label_visibility="collapsed",
        )
        if st.button("Resume", width="stretch") and resume_id:
            st.session_state.session_id = resume_id.strip()
            st.session_state.messages = []
            st.rerun()

    # ── Previous sessions ─────────────────────────────────────────────────
    try:
        if _AGENT_DB_PATH.exists():
            from sqlalchemy import create_engine, text as sql_text
            eng = create_engine(f"sqlite:///{_AGENT_DB_PATH}")
            with eng.connect() as conn:
                rows = conn.execute(sql_text(
                    "SELECT session_id, created_at FROM sessions "
                    "ORDER BY created_at DESC LIMIT 10"
                )).fetchall()
            if rows:
                with st.expander("Recent sessions"):
                    for row in rows:
                        sid = row[0]
                        created = row[1]
                        label = f"{sid[:8]}... ({created})" if created else sid[:8]
                        if st.button(label, key=f"sess_{sid}"):
                            st.session_state.session_id = sid
                            st.session_state.messages = []
                            st.rerun()
    except Exception:
        pass  # No sessions table yet — that's fine

    # ── File upload ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("1. Upload Documents")
    uploaded_files = st.file_uploader(
        "PDF, Excel, or CSV files",
        type=["pdf", "xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key="file_uploader",
    )

    # ── Pipeline settings ────────────────────────────────────────────────
    st.subheader("2. Pipeline Settings")
    extractor = st.selectbox("Extraction backend", ["mistral", "docling"], index=0)
    from_cache = st.checkbox("Use cached extraction", value=True)
    entity_name = st.text_input("Entity name", value="Unknown")
    fiscal_year = st.text_input("Fiscal year", value="2023-24")

    # ── Or use existing DB ───────────────────────────────────────────────
    st.divider()
    st.subheader("Or: Use Existing Database")
    existing_db = st.text_input(
        "Path to DuckDB file",
        value=str(default_output_dir() / "test_forensic_mistral.duckdb"),
    )
    use_existing = st.button("Load Existing DB", type="secondary")

    # ── Run pipeline ─────────────────────────────────────────────────────
    st.divider()
    run_pipeline_btn = st.button(
        "Run Full Pipeline", type="primary", disabled=not uploaded_files
    )

    # ── Pipeline progress ────────────────────────────────────────────────
    pipeline_status = st.empty()
    pipeline_progress = st.empty()


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

def _handle_pipeline_run():
    """Run the pipeline on uploaded files."""
    if not uploaded_files:
        st.sidebar.error("Upload at least one file first.")
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix="forensic_"))
    file_paths = []
    for uf in uploaded_files:
        p = tmp_dir / uf.name
        p.write_bytes(uf.getvalue())
        file_paths.append(p)

    progress_bar = pipeline_progress.progress(0, text="Starting pipeline...")
    steps = {"extract": 0.2, "normalize": 0.5, "curate": 0.6, "skills": 0.7, "done": 1.0}

    def on_progress(step: str, detail: str):
        pct = steps.get(step, 0)
        progress_bar.progress(pct, text=detail)

    result = run_pipeline(
        file_paths=file_paths,
        extractor=extractor,
        from_cache=from_cache,
        entity_name=entity_name,
        fiscal_year=fiscal_year,
        on_progress=on_progress,
    )

    st.session_state.pipeline_result = result
    _init_from_result(result)

    if result.success:
        pipeline_status.success(f"Pipeline complete. DB: {result.db_path}")
    else:
        pipeline_status.error(f"Pipeline failed: {result.error}")


def _handle_existing_db():
    """Load an existing DuckDB and scan for skill outputs."""
    db_path = Path(existing_db)
    if not db_path.exists():
        st.sidebar.error(f"File not found: {db_path}")
        return

    result = PipelineResult(db_path=db_path, success=True)

    # Scan for existing skill output JSONs
    search_dirs = [db_path.parent / "skill_results"]
    for skill_dir_candidate in (_PROJECT_ROOT / "skills").iterdir():
        outputs_dir = skill_dir_candidate / "outputs"
        if outputs_dir.is_dir():
            search_dirs.append(outputs_dir)

    skill_map = {
        "benfords-analysis": ["benfords.json", "sweep.json", "sweep_mistral_v2_raw.json"],
        "duplicate-detector": ["duplicates.json", "sweep.json"],
        "ratio-analyzer": ["ratios.json", "sweep.json"],
        "anomaly-detector": ["anomalies.json", "sweep.json"],
        "network-analyzer": ["network.json", "sweep.json"],
    }
    for skill_name, filenames in skill_map.items():
        for search_dir in search_dirs:
            if skill_name in result.skill_outputs:
                break
            for filename in filenames:
                p = search_dir / filename
                if p.exists():
                    result.skill_outputs[skill_name] = p
                    result.skill_statuses[skill_name] = "OK"
                    break

    st.session_state.pipeline_result = result
    _init_from_result(result)
    pipeline_status.success(f"Loaded DB: {db_path}")


def _init_from_result(result: PipelineResult):
    """Initialize state from a pipeline result."""
    if result.db_path and result.db_path.exists():
        st.session_state.db_path = str(result.db_path)

    # Load all available skill JSONs
    skill_data = {}
    for name, path in result.skill_outputs.items():
        if Path(path).exists():
            try:
                skill_data[name] = load_skill_json(path)
            except Exception:
                pass
    st.session_state.skill_data = skill_data


# Trigger pipeline or DB load
if run_pipeline_btn:
    _handle_pipeline_run()
if use_existing:
    _handle_existing_db()


# ---------------------------------------------------------------------------
# Main area — Dashboard + Chat
# ---------------------------------------------------------------------------

result: PipelineResult | None = st.session_state.pipeline_result

# ── Dashboard tabs (always show, even without pipeline result) ────────────
tab_chat, tab_benford, tab_dup, tab_ratio, tab_anomaly, tab_network, tab_logs = st.tabs([
    "Chat", "Benford's", "Duplicates", "Ratios", "Anomalies", "Network", "Logs",
])

skill_data: dict = st.session_state.skill_data

# ── Benford's tab ────────────────────────────────────────────────────────
with tab_benford:
    bdata = skill_data.get("benfords-analysis")
    if bdata:
        overview = render_skill_overview(bdata)
        st.markdown(
            risk_badge(overview["risk_score"], "Benford's Risk"),
            unsafe_allow_html=True,
        )
        st.markdown(f"**Overall Verdict:** {bdata.get('overall_verdict', 'N/A')}")

        available_tests = list(bdata.get("tests", {}).keys())
        if available_tests:
            selected_test = st.selectbox(
                "Select test", available_tests, key="benford_test"
            )
            fig = benford_chart(bdata, selected_test)
            if fig:
                st.plotly_chart(fig, width="stretch")

        st.subheader("Test Summary")
        st.dataframe(
            benford_summary_table(bdata), width="stretch", hide_index=True
        )

        if overview["suggestions"]:
            st.subheader("Investigation Suggestions")
            for s in overview["suggestions"]:
                st.markdown(f"- {s}")
    else:
        st.info("No Benford's analysis results. Run the pipeline or load a DB.")

# ── Duplicates tab ───────────────────────────────────────────────────────
with tab_dup:
    ddata = skill_data.get("duplicate-detector")
    if ddata:
        overview = render_skill_overview(ddata)
        st.markdown(
            risk_badge(overview["risk_score"], "Duplicate Risk"),
            unsafe_allow_html=True,
        )

        st.subheader("Summary")
        st.dataframe(
            duplicate_summary_table(ddata), width="stretch", hide_index=True
        )

        finding_types = [
            "exact_duplicates", "near_amount_duplicates",
            "fuzzy_name_duplicates", "cross_period_duplicates",
        ]
        for ft in finding_types:
            df = duplicate_details_table(ddata, ft)
            if df is not None and not df.empty:
                st.subheader(ft.replace("_", " ").title())
                st.dataframe(df, width="stretch", hide_index=True)

        if overview["suggestions"]:
            st.subheader("Investigation Suggestions")
            for s in overview["suggestions"]:
                st.markdown(f"- {s}")
    else:
        st.info("No duplicate detection results available.")

# ── Ratios tab ───────────────────────────────────────────────────────────
with tab_ratio:
    rdata = skill_data.get("ratio-analyzer")
    if rdata:
        overview = render_skill_overview(rdata)
        st.markdown(
            risk_badge(overview["risk_score"], "Ratio Risk"),
            unsafe_allow_html=True,
        )

        fig = ratio_bar_chart(rdata)
        if fig:
            st.plotly_chart(fig, width="stretch")

        yoy_df = ratio_yoy_table(rdata)
        if yoy_df is not None:
            st.subheader("Year-on-Year Growth")
            st.dataframe(yoy_df, width="stretch", hide_index=True)

        flagged = rdata.get("flagged_changes", [])
        if flagged:
            st.subheader("Flagged Changes")
            st.dataframe(
                pd.DataFrame(flagged), width="stretch", hide_index=True
            )

        if overview["suggestions"]:
            st.subheader("Investigation Suggestions")
            for s in overview["suggestions"]:
                st.markdown(f"- {s}")
    else:
        st.info("No ratio analysis results available.")

# ── Anomalies tab ────────────────────────────────────────────────────────
with tab_anomaly:
    adata = skill_data.get("anomaly-detector")
    if adata:
        overview = render_skill_overview(adata)
        st.markdown(
            risk_badge(overview["risk_score"], "Anomaly Risk"),
            unsafe_allow_html=True,
        )

        st.subheader("Method Summary")
        st.dataframe(
            anomaly_summary_table(adata), width="stretch", hide_index=True
        )

        fig = anomaly_scatter(adata)
        if fig:
            st.plotly_chart(fig, width="stretch")

        anomalies = adata.get("anomalies", [])
        if anomalies:
            st.subheader(f"Anomaly Records ({len(anomalies)})")
            anom_df = pd.DataFrame(anomalies)
            if "is_consensus_anomaly" in anom_df.columns:
                anom_df = anom_df.sort_values("is_consensus_anomaly", ascending=False)
            st.dataframe(anom_df, width="stretch", hide_index=True)

        if overview["suggestions"]:
            st.subheader("Investigation Suggestions")
            for s in overview["suggestions"]:
                st.markdown(f"- {s}")
    else:
        st.info("No anomaly detection results available.")

# ── Network tab ──────────────────────────────────────────────────────────
with tab_network:
    ndata = skill_data.get("network-analyzer")
    if ndata:
        overview = render_skill_overview(ndata)
        st.markdown(
            risk_badge(overview["risk_score"], "Network Risk"),
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns([2, 1])
        with col1:
            fig = network_graph_plotly(ndata)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("No network graph to display.")
        with col2:
            st.subheader("Graph Stats")
            st.dataframe(
                network_stats_table(ndata), width="stretch", hide_index=True
            )

        communities = ndata.get("communities", [])
        if communities:
            st.subheader("Communities")
            st.dataframe(
                pd.DataFrame(communities), width="stretch", hide_index=True
            )

        if overview["suggestions"]:
            st.subheader("Investigation Suggestions")
            for s in overview["suggestions"]:
                st.markdown(f"- {s}")
    else:
        st.info("No network analysis results available.")

# ── Logs tab ─────────────────────────────────────────────────────────────
with tab_logs:
    st.subheader("Pipeline Log")
    if result and result.logs:
        for line in result.logs:
            st.text(line)
    else:
        st.info("No pipeline logs (DB was loaded directly or no pipeline run yet).")

    st.subheader("Skill Statuses")
    if result and result.skill_statuses:
        for name, status in result.skill_statuses.items():
            icon = "✅" if status == "OK" else "❌"
            st.text(f"  {icon} {name}: {status}")


# ── Chat tab ─────────────────────────────────────────────────────────────
with tab_chat:
    st.subheader("Chat with Forensic Analyst AI")

    # Risk score overview bar (if skill data available)
    if skill_data:
        risk_cols = st.columns(5)
        skill_labels = [
            ("benfords-analysis", "Benford's"),
            ("duplicate-detector", "Duplicates"),
            ("ratio-analyzer", "Ratios"),
            ("anomaly-detector", "Anomalies"),
            ("network-analyzer", "Network"),
        ]
        for col, (sname, slabel) in zip(risk_cols, skill_labels):
            sd = skill_data.get(sname, {})
            score = sd.get("risk_score") or sd.get("overall_risk_score", 0)
            col.metric(slabel, f"{score}/10")
        st.divider()

    # Chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Ask the forensic analyst..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build agent (fresh each turn to pick up db_path changes)
        agent = _get_agent()

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            tool_status_container = st.container()
            active_tool_status = None

            try:
                for event in agent.run(prompt, stream=True):
                    event_type = getattr(event, "event", None)

                    if isinstance(event, RunContentEvent):
                        content = getattr(event, "content", None)
                        if content:
                            full_response += str(content)
                            response_placeholder.markdown(full_response + "▌")

                    elif isinstance(event, ToolCallStartedEvent):
                        tool = getattr(event, "tool", None)
                        tool_name = (
                            getattr(tool, "tool_name", "tool") if tool else "tool"
                        )
                        with tool_status_container:
                            active_tool_status = st.status(
                                f"Running {tool_name}...", state="running"
                            )

                    elif isinstance(event, ToolCallCompletedEvent):
                        tool = getattr(event, "tool", None)
                        tool_name = (
                            getattr(tool, "tool_name", "tool") if tool else "tool"
                        )
                        if active_tool_status:
                            active_tool_status.update(
                                label=f"{tool_name} complete", state="complete"
                            )
                            active_tool_status = None

                    elif isinstance(event, RunCompletedEvent):
                        content = getattr(event, "content", None)
                        if content:
                            full_response = str(content)

                # Final render (remove cursor)
                response_placeholder.markdown(full_response)

                # Update toolkit db_path in session state if pipeline ran
                # (the toolkit may have set self.db_path during run_pipeline)
                if hasattr(agent, "tools"):
                    for t in agent.tools:
                        if isinstance(t, ForensicToolkit) and t.db_path:
                            st.session_state.db_path = t.db_path

            except Exception as exc:
                full_response = f"Agent error: {exc}"
                response_placeholder.markdown(full_response)

            st.session_state.messages.append(
                {"role": "assistant", "content": full_response}
            )
