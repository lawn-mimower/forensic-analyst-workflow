"""
Visualization Helpers — Streamlit-compatible charts for forensic skill outputs.

Each function takes the parsed JSON output from a skill and returns a
Streamlit-renderable object (plotly figure, dataframe, or markdown).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_skill_json(path: Path | str) -> dict[str, Any]:
    """Load and return a skill output JSON file."""
    with open(path) as f:
        return json.load(f)


def _risk_color(score: int) -> str:
    """Return a color string based on risk score 1-10."""
    if score <= 3:
        return "#2ecc71"  # green
    if score <= 6:
        return "#f39c12"  # orange
    return "#e74c3c"  # red


def risk_badge(score: int, label: str = "Risk Score") -> str:
    """Return an HTML badge for the risk score."""
    color = _risk_color(score)
    return (
        f'<span style="background:{color};color:white;padding:4px 12px;'
        f'border-radius:12px;font-weight:bold;font-size:1.1em;">'
        f'{label}: {score}/10</span>'
    )


# ---------------------------------------------------------------------------
# Benford's Analysis
# ---------------------------------------------------------------------------

def benford_chart(data: dict[str, Any], test_name: str = "first_digit") -> go.Figure | None:
    """Create a bar chart comparing observed vs expected digit frequencies."""
    tests = data.get("tests", {})
    test = tests.get(test_name)
    if not test or "error" in test:
        return None

    observed = test.get("observed", {})
    expected = test.get("expected", {})
    if not observed:
        return None

    digits = sorted(observed.keys(), key=lambda k: int(k))
    obs_vals = [observed[d] for d in digits]
    exp_vals = [expected.get(d, 0) for d in digits]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=digits, y=obs_vals, name="Observed",
        marker_color="#3498db", opacity=0.8,
    ))
    fig.add_trace(go.Bar(
        x=digits, y=exp_vals, name="Expected (Benford)",
        marker_color="#e74c3c", opacity=0.6,
    ))

    verdict = test.get("verdict", "")
    mad = test.get("mad", 0)
    fig.update_layout(
        title=f"Benford's {test_name.replace('_', ' ').title()} Test — {verdict} (MAD={mad:.4f})",
        xaxis_title="Digit",
        yaxis_title="Proportion",
        barmode="group",
        template="plotly_white",
        height=400,
    )
    return fig


def benford_summary_table(data: dict[str, Any]) -> pd.DataFrame:
    """Create a summary DataFrame of all Benford's tests."""
    tests = data.get("tests", {})
    rows = []
    for name, test in tests.items():
        if "error" in test:
            rows.append({"Test": name, "Verdict": test["error"], "MAD": None,
                         "p-value": None, "Flagged": 0})
        else:
            rows.append({
                "Test": name.replace("_", " ").title(),
                "Verdict": test.get("verdict", ""),
                "MAD": test.get("mad"),
                "p-value": test.get("p_value"),
                "Flagged Digits": len(test.get("flagged_digits", [])),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Duplicate Detector
# ---------------------------------------------------------------------------

def duplicate_summary_table(data: dict[str, Any]) -> pd.DataFrame:
    """Create a summary of duplicate detection findings."""
    summary = data.get("summary", {})
    rows = [
        {"Metric": "Total Records Analyzed", "Value": summary.get("total_records_analyzed", 0)},
        {"Metric": "Exact Duplicate Groups", "Value": summary.get("exact_duplicate_groups", 0)},
        {"Metric": "Exact Duplicate Rows", "Value": summary.get("exact_duplicate_rows", 0)},
        {"Metric": "Near-Amount Matches", "Value": summary.get("near_amount_matches", 0)},
        {"Metric": "Fuzzy-Name Matches", "Value": summary.get("fuzzy_name_matches", 0)},
        {"Metric": "Cross-Period Matches", "Value": summary.get("cross_period_matches", 0)},
        {"Metric": "Round Number % (ends 00)", "Value": f"{summary.get('round_number_pct_ends_00', 0):.1f}%"},
    ]
    return pd.DataFrame(rows)


def duplicate_details_table(data: dict[str, Any], finding_type: str) -> pd.DataFrame | None:
    """Return details for a specific duplicate finding type as a DataFrame."""
    findings = data.get("findings", {})
    finding = findings.get(finding_type, {})
    details = finding.get("details", [])
    if not details:
        return None
    return pd.DataFrame(details)


# ---------------------------------------------------------------------------
# Ratio Analyzer
# ---------------------------------------------------------------------------

def ratio_bar_chart(data: dict[str, Any]) -> go.Figure | None:
    """Create a grouped bar chart of financial ratios by period."""
    ratios_by_period = data.get("ratios_by_period", {})
    if not ratios_by_period:
        return None

    # Collect all ratio names that have at least one non-None value
    all_ratios = set()
    for period_ratios in ratios_by_period.values():
        for name, val in period_ratios.items():
            if val is not None:
                all_ratios.add(name)

    if not all_ratios:
        return None

    ratio_names = sorted(all_ratios)
    fig = go.Figure()

    for period, period_ratios in ratios_by_period.items():
        values = [period_ratios.get(r) for r in ratio_names]
        # Replace None with 0 for display
        display_vals = [v if v is not None else 0 for v in values]
        fig.add_trace(go.Bar(
            x=[r.replace("_", " ").title() for r in ratio_names],
            y=display_vals,
            name=str(period),
        ))

    fig.update_layout(
        title="Financial Ratios by Period",
        xaxis_title="Ratio",
        yaxis_title="Value",
        barmode="group",
        template="plotly_white",
        height=450,
        xaxis_tickangle=-45,
    )
    return fig


def ratio_yoy_table(data: dict[str, Any]) -> pd.DataFrame | None:
    """Create a DataFrame of year-on-year growth figures."""
    yoy = data.get("yoy_growth", {})
    if not yoy:
        return None
    rows = []
    for cat, g in yoy.items():
        rows.append({
            "Category": cat.replace("_", " ").title(),
            "Current": f"{g.get('current_amount', 0):,.2f}",
            "Prior": f"{g.get('prior_amount', 0):,.2f}",
            "Change": f"{g.get('absolute_change', 0):,.2f}",
            "% Change": f"{(g.get('pct_change') or 0) * 100:.1f}%",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Anomaly Detector
# ---------------------------------------------------------------------------

def anomaly_scatter(data: dict[str, Any]) -> go.Figure | None:
    """Create a scatter plot of anomalies: amount vs anomaly score."""
    anomalies = data.get("anomalies", [])
    if not anomalies:
        return None

    df = pd.DataFrame(anomalies)
    if "amount" not in df.columns or "anomaly_score" not in df.columns:
        return None

    # Filter to items with a score
    df = df.dropna(subset=["anomaly_score"])
    if df.empty:
        return None

    fig = px.scatter(
        df,
        x="amount",
        y="anomaly_score",
        color="is_consensus_anomaly",
        hover_data=["account_name", "n_methods", "methods_flagged"],
        color_discrete_map={True: "#e74c3c", False: "#3498db"},
        title="Anomaly Detection — Amount vs Anomaly Score",
        labels={
            "amount": "Amount",
            "anomaly_score": "Anomaly Score (IForest)",
            "is_consensus_anomaly": "Consensus Anomaly",
        },
    )
    fig.update_layout(template="plotly_white", height=450)
    return fig


def anomaly_summary_table(data: dict[str, Any]) -> pd.DataFrame:
    """Summary table for anomaly detection methods."""
    summary = data.get("summary", {})
    method_counts = summary.get("anomalies_per_method", {})
    rows = [
        {"Method": k.upper(), "Flagged": v}
        for k, v in method_counts.items()
    ]
    rows.append({
        "Method": "CONSENSUS",
        "Flagged": summary.get("consensus_anomalies", 0),
    })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Network Analyzer
# ---------------------------------------------------------------------------

def network_graph_plotly(data: dict[str, Any]) -> go.Figure | None:
    """Create a plotly network graph from network analyzer output."""
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    if not nodes:
        return None

    try:
        import networkx as nx
    except ImportError:
        return None

    G = nx.Graph()
    for node in nodes:
        G.add_node(node["entity"], **{k: v for k, v in node.items() if k != "entity"})
    for edge in edges:
        G.add_edge(edge["source"], edge["target"], weight=edge.get("total_amount", 1))

    pos = nx.spring_layout(G, seed=42, k=2.0)

    # Edge traces
    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1, color="#888"),
        hoverinfo="none",
    )

    # Node traces
    node_x = [pos[n["entity"]][0] for n in nodes]
    node_y = [pos[n["entity"]][1] for n in nodes]
    node_text = [
        f"{n['entity']}<br>Degree: {n['degree']}<br>"
        f"Betweenness: {n.get('betweenness_centrality', 0):.3f}<br>"
        f"Amount: {n.get('total_amount', 0):,.0f}"
        for n in nodes
    ]
    node_colors = [n.get("degree", 1) for n in nodes]
    node_sizes = [max(15, min(50, n.get("degree", 1) * 8)) for n in nodes]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        text=[n["entity"][:20] for n in nodes],
        textposition="top center",
        textfont=dict(size=9),
        hovertext=node_text,
        hoverinfo="text",
        marker=dict(
            size=node_sizes,
            color=node_colors,
            colorscale="YlOrRd",
            showscale=True,
            colorbar=dict(title="Degree"),
            line=dict(width=2, color="white"),
        ),
    )

    stats = data.get("graph_stats", {})
    fig = go.Figure(
        data=[edge_trace, node_trace],
        layout=go.Layout(
            title=f"Entity Network — {stats.get('n_nodes', 0)} nodes, "
                  f"{stats.get('n_edges', 0)} edges",
            showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            template="plotly_white",
            height=500,
        ),
    )
    return fig


def network_stats_table(data: dict[str, Any]) -> pd.DataFrame:
    """Network graph statistics as a DataFrame."""
    stats = data.get("graph_stats", {})
    rows = [
        {"Metric": "Nodes", "Value": stats.get("n_nodes", 0)},
        {"Metric": "Edges", "Value": stats.get("n_edges", 0)},
        {"Metric": "Density", "Value": f"{stats.get('density', 0):.4f}"},
        {"Metric": "Connected", "Value": stats.get("is_connected", False)},
        {"Metric": "Components", "Value": stats.get("n_components", 0)},
        {"Metric": "Communities", "Value": len(data.get("communities", []))},
        {"Metric": "Cycles", "Value": len(data.get("cycles", []))},
        {"Metric": "Hubs", "Value": len(data.get("hubs", []))},
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Universal: Render any skill output's suggestions and risk
# ---------------------------------------------------------------------------

def render_skill_overview(data: dict[str, Any]) -> dict[str, Any]:
    """Extract common fields from any skill output for display.

    Returns dict with: risk_score, suggestions, error (if any).
    """
    return {
        "risk_score": data.get("risk_score") or data.get("overall_risk_score", 0),
        "suggestions": (
            data.get("investigation_suggestions", [])
        ),
        "error": data.get("error"),
    }
