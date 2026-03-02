# /// script
# dependencies = ["duckdb", "networkx", "numpy", "python-louvain"]
# ///
"""
Network Analyzer for Forensic Accounting
==========================================

Builds entity relationship graphs from the ``related_parties`` DuckDB table,
applies community detection (Louvain), centrality metrics, and cycle detection
to reveal hidden connections and suspicious structures.

  Pass 1 (Sweep):  Build full graph from all related parties, all metrics.
  Pass 2 (Investigate):  Re-run with --filter to focus on a subset.

All output is structured JSON written to --output.
Diagnostics and progress messages go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np

# ---------------------------------------------------------------------------
# Project root on sys.path so shared utilities are importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.forensic_utils import load_db, build_meta, write_output  # noqa: E402

# ---------------------------------------------------------------------------
# Optional: python-louvain community detection
# ---------------------------------------------------------------------------
try:
    import community as community_louvain  # python-louvain
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False
    print("[network] python-louvain not installed -- community detection skipped",
          file=sys.stderr)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graphs(
    rows: list[dict],
    subject_entity: str,
) -> tuple[nx.Graph, nx.DiGraph]:
    """Build undirected and directed graphs from related_parties rows.

    Undirected graph: edge weight = sum of |amount_inr| between the pair.
    Directed graph:   direction follows money flow based on amount sign.
    """
    G = nx.Graph()
    D = nx.DiGraph()

    # Accumulate edge data keyed by (source, target) for undirected,
    # and directed edges for cycle detection.
    edge_accum: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        party = row["party_name"]
        amt = row.get("amount_inr") or row.get("amount") or 0.0
        rel_cat = row.get("relationship_category") or "unknown"
        txn_type = row.get("transaction_type") or "unknown"

        # Undirected key: alphabetical order to avoid duplication
        key = tuple(sorted([subject_entity, party]))
        if key not in edge_accum:
            edge_accum[key] = {
                "relationship_types": set(),
                "total_amount": 0.0,
            }
        edge_accum[key]["relationship_types"].add(f"{rel_cat}/{txn_type}")
        edge_accum[key]["total_amount"] += abs(amt)

        # Directed edge: positive amount = money flows entity -> subject,
        # negative amount = money flows subject -> entity.
        if amt > 0:
            D.add_edge(party, subject_entity, weight=abs(amt))
        elif amt < 0:
            D.add_edge(subject_entity, party, weight=abs(amt))
        else:
            # Zero amount -- add both directions so cycle detection can find it
            D.add_edge(party, subject_entity, weight=0.0)

    # Build undirected graph from accumulated edges
    for (u, v), data in edge_accum.items():
        G.add_edge(
            u, v,
            weight=data["total_amount"],
            relationship_type="; ".join(sorted(data["relationship_types"])),
            total_amount=data["total_amount"],
        )

    # Also add inter-party edges: parties sharing the same relationship_category
    # may themselves be connected (e.g. all subsidiaries form a clique).
    cat_groups: dict[str, list[str]] = {}
    for row in rows:
        cat = row.get("relationship_category") or "unknown"
        party = row["party_name"]
        cat_groups.setdefault(cat, []).append(party)

    for cat, members in cat_groups.items():
        unique_members = list(set(members))
        if len(unique_members) < 2:
            continue
        for i in range(len(unique_members)):
            for j in range(i + 1, len(unique_members)):
                u, v = unique_members[i], unique_members[j]
                if not G.has_edge(u, v):
                    G.add_edge(
                        u, v,
                        weight=0.0,
                        relationship_type=f"same_category/{cat}",
                        total_amount=0.0,
                    )

    return G, D


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _compute_centralities(G: nx.Graph) -> dict[str, dict[str, float]]:
    """Compute degree, betweenness, and closeness centrality for all nodes."""
    return {
        "degree": nx.degree_centrality(G),
        "betweenness": nx.betweenness_centrality(G, weight="weight"),
        "closeness": nx.closeness_centrality(G),
    }


def _detect_communities(G: nx.Graph) -> dict[str, int]:
    """Run Louvain community detection.  Returns node -> community_id map."""
    if not HAS_LOUVAIN or G.number_of_nodes() == 0:
        return {}
    try:
        return community_louvain.best_partition(G, weight="weight")
    except Exception as exc:
        print(f"[network] Community detection failed: {exc}", file=sys.stderr)
        return {}


def _detect_cycles(D: nx.DiGraph, max_length: int = 5) -> list[list[str]]:
    """Find simple cycles up to *max_length* in the directed graph."""
    cycles: list[list[str]] = []
    try:
        for cycle in nx.simple_cycles(D):
            if len(cycle) <= max_length:
                cycles.append(cycle)
            # Safety cap: don't enumerate forever on dense graphs
            if len(cycles) >= 200:
                print("[network] Cycle enumeration capped at 200", file=sys.stderr)
                break
    except Exception as exc:
        print(f"[network] Cycle detection failed: {exc}", file=sys.stderr)
    return cycles


def _detect_hubs(G: nx.Graph) -> list[str]:
    """Flag nodes with degree > mean + 2*std of the degree distribution."""
    if G.number_of_nodes() < 3:
        return []
    degrees = np.array([d for _, d in G.degree()])
    mean_deg = float(np.mean(degrees))
    std_deg = float(np.std(degrees))
    threshold = mean_deg + 2 * std_deg
    hub_nodes = [node for node, d in G.degree() if d > threshold]
    return hub_nodes


# ---------------------------------------------------------------------------
# Risk score
# ---------------------------------------------------------------------------

def _compute_risk_score(
    G: nx.Graph,
    cycles: list[list[str]],
    hubs: list[str],
    centralities: dict[str, dict[str, float]],
    n_communities: int,
) -> int:
    """Compute a 1--10 risk score for the network structure."""
    score = 1  # base for simple graphs

    # +2 if cycles detected
    if cycles:
        score += 2

    # +2 if high-betweenness non-obvious entities exist
    # "non-obvious" = not a hub (i.e. not highest-degree) but top betweenness
    betweenness = centralities.get("betweenness", {})
    if betweenness:
        bc_values = sorted(betweenness.values(), reverse=True)
        # An entity is "non-obvious high-betweenness" if it is in the top 20%
        # of betweenness but NOT in the hub list.
        if len(bc_values) >= 3:
            threshold_bc = bc_values[max(0, len(bc_values) // 5)]
            non_obvious = [
                n for n, bc in betweenness.items()
                if bc >= threshold_bc and n not in hubs
            ]
            if non_obvious:
                score += 2

    # +1 per community beyond 2
    if n_communities > 2:
        score += (n_communities - 2)

    # +1 if density > 0.5
    if G.number_of_nodes() >= 2 and nx.density(G) > 0.5:
        score += 1

    return max(1, min(10, score))


# ---------------------------------------------------------------------------
# Investigation suggestions
# ---------------------------------------------------------------------------

def _generate_suggestions(
    cycles: list[list[str]],
    hubs: list[str],
    n_communities: int,
    G: nx.Graph,
    centralities: dict[str, dict[str, float]],
) -> list[str]:
    """Generate actionable follow-up suggestions based on network analysis."""
    suggestions: list[str] = []

    if cycles:
        cycle_strs = [" -> ".join(c + [c[0]]) for c in cycles[:5]]
        suggestions.append(
            f"Detected {len(cycles)} circular relationship chain(s). "
            f"Sample: {cycle_strs[0]}. Circular chains are indicators of "
            f"round-tripping, layering, or fund diversion. Cross-reference "
            f"transaction amounts in these cycles with Benford's analysis."
        )

    if hubs:
        suggestions.append(
            f"Hub entities detected: {', '.join(hubs)}. These entities have "
            f"significantly more connections than average. Verify whether they "
            f"are legitimate holding companies or potential shell entities used "
            f"to route transactions."
        )

    betweenness = centralities.get("betweenness", {})
    if betweenness and len(betweenness) >= 3:
        # Entities with high betweenness but not hubs -> gatekeepers
        bc_sorted = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)
        gatekeepers = [n for n, _ in bc_sorted[:3] if n not in hubs]
        if gatekeepers:
            suggestions.append(
                f"Gatekeeper entities (high betweenness, not hubs): "
                f"{', '.join(gatekeepers)}. These entities bridge otherwise "
                f"disconnected groups and may be routing funds between them."
            )

    if n_communities > 2:
        suggestions.append(
            f"Network splits into {n_communities} communities. Investigate "
            f"whether inter-community transactions represent legitimate "
            f"business or related-party tunneling."
        )

    if G.number_of_nodes() >= 2 and nx.density(G) > 0.5:
        suggestions.append(
            "High network density (>0.5) indicates many entities transact "
            "with each other. This may signal a tightly-knit group where "
            "transactions can be easily fabricated or inflated."
        )

    if not suggestions:
        suggestions.append(
            "Network structure appears simple with no immediate red flags. "
            "Consider cross-referencing with duplicate detection or Benford's "
            "analysis on transaction amounts for deeper investigation."
        )

    return suggestions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Network analysis on related-party entity graphs",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--table", default="related_parties",
                        help="Table or view to query (default: related_parties)")
    parser.add_argument("--filter", default=None,
                        help="SQL WHERE clause for related_parties")
    parser.add_argument("--case-id", default=None, help="Case identifier")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    meta = build_meta(
        skill_name="network-analyzer",
        db_path=args.db,
        table=args.table,
        filter_sql=args.filter,
        case_id=args.case_id,
    )

    con = load_db(args.db)

    # ------------------------------------------------------------------
    # Validate related_parties table exists
    # ------------------------------------------------------------------
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    except Exception:
        tables = []

    if args.table not in tables:
        print(f"[network] {args.table} table/view not found", file=sys.stderr)
        write_output({
            "meta": meta,
            "error": f"{args.table} table/view not found in database",
            "graph_stats": {},
            "nodes": [], "edges": [], "communities": [], "cycles": [],
            "hubs": [], "risk_score": 0, "investigation_suggestions": [],
        }, args.output)
        con.close()
        return

    # ------------------------------------------------------------------
    # Infer subject entity from source_tables.entity_name
    # ------------------------------------------------------------------
    subject_entity = "Subject Entity"
    if "source_tables" in tables:
        try:
            row = con.execute(
                "SELECT entity_name FROM source_tables "
                "WHERE entity_name IS NOT NULL LIMIT 1"
            ).fetchone()
            if row and row[0]:
                subject_entity = row[0]
        except Exception:
            pass
    print(f"[network] Subject entity: {subject_entity}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Query related_parties
    # ------------------------------------------------------------------
    query = f'SELECT * FROM "{args.table}"'
    if args.filter:
        query += f" WHERE {args.filter}"
    print(f"[network] Query: {query}", file=sys.stderr)

    try:
        df = con.execute(query).df()
    except Exception as exc:
        con.close()
        print(f"[network] Query failed: {exc}", file=sys.stderr)
        write_output({
            "meta": meta,
            "error": f"Query failed: {exc}",
            "graph_stats": {},
            "nodes": [], "edges": [], "communities": [], "cycles": [],
            "hubs": [], "risk_score": 0, "investigation_suggestions": [],
        }, args.output)
        return

    con.close()
    rows = df.to_dict(orient="records")
    print(f"[network] {len(rows)} related_parties rows loaded", file=sys.stderr)

    # ------------------------------------------------------------------
    # Handle edge case: no data
    # ------------------------------------------------------------------
    if not rows:
        write_output({
            "meta": meta,
            "graph_stats": {"n_nodes": 0, "n_edges": 0, "density": 0.0,
                            "is_connected": False, "n_components": 0},
            "nodes": [], "edges": [], "communities": [], "cycles": [],
            "hubs": [], "risk_score": 1,
            "investigation_suggestions": [
                "No related-party records found. Ensure data has been "
                "normalized into the related_parties table before running "
                "network analysis."
            ],
        }, args.output)
        return

    # ------------------------------------------------------------------
    # Build graphs
    # ------------------------------------------------------------------
    G, D = _build_graphs(rows, subject_entity)
    print(f"[network] Graph: {G.number_of_nodes()} nodes, "
          f"{G.number_of_edges()} edges", file=sys.stderr)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    centralities = _compute_centralities(G)
    partition = _detect_communities(G)
    cycles = _detect_cycles(D, max_length=5)
    hubs = _detect_hubs(G)

    n_communities = len(set(partition.values())) if partition else 0

    # ------------------------------------------------------------------
    # Assemble node list
    # ------------------------------------------------------------------
    node_amounts: dict[str, float] = {}
    for row in rows:
        party = row["party_name"]
        amt = abs(row.get("amount_inr") or row.get("amount") or 0.0)
        node_amounts[party] = node_amounts.get(party, 0.0) + amt
        node_amounts[subject_entity] = node_amounts.get(subject_entity, 0.0) + amt

    nodes_out: list[dict[str, Any]] = []
    for node in G.nodes():
        nodes_out.append({
            "entity": node,
            "degree": G.degree(node),
            "degree_centrality": round(centralities["degree"].get(node, 0.0), 6),
            "betweenness_centrality": round(centralities["betweenness"].get(node, 0.0), 6),
            "closeness_centrality": round(centralities["closeness"].get(node, 0.0), 6),
            "community": partition.get(node, -1),
            "is_hub": node in hubs,
            "total_amount": round(node_amounts.get(node, 0.0), 2),
        })

    # ------------------------------------------------------------------
    # Assemble edge list
    # ------------------------------------------------------------------
    edges_out: list[dict[str, Any]] = []
    for u, v, data in G.edges(data=True):
        edges_out.append({
            "source": u,
            "target": v,
            "relationship_type": data.get("relationship_type", ""),
            "total_amount": round(data.get("total_amount", 0.0), 2),
            "weight": round(data.get("weight", 0.0), 2),
        })

    # ------------------------------------------------------------------
    # Assemble community summaries
    # ------------------------------------------------------------------
    communities_out: list[dict[str, Any]] = []
    if partition:
        comm_members: dict[int, list[str]] = {}
        for node, cid in partition.items():
            comm_members.setdefault(cid, []).append(node)

        for cid, members in sorted(comm_members.items()):
            subgraph = G.subgraph(members)
            internal_amount = sum(
                d.get("total_amount", 0.0) for _, _, d in subgraph.edges(data=True)
            )
            communities_out.append({
                "community_id": cid,
                "members": members,
                "internal_edges": subgraph.number_of_edges(),
                "total_internal_amount": round(internal_amount, 2),
            })

    # ------------------------------------------------------------------
    # Assemble hub details
    # ------------------------------------------------------------------
    hubs_out: list[dict[str, Any]] = []
    for h in hubs:
        hubs_out.append({
            "entity": h,
            "degree": G.degree(h),
            "degree_centrality": round(centralities["degree"].get(h, 0.0), 6),
            "betweenness_centrality": round(centralities["betweenness"].get(h, 0.0), 6),
            "closeness_centrality": round(centralities["closeness"].get(h, 0.0), 6),
            "total_amount": round(node_amounts.get(h, 0.0), 2),
        })

    # ------------------------------------------------------------------
    # Risk score and suggestions
    # ------------------------------------------------------------------
    risk_score = _compute_risk_score(G, cycles, hubs, centralities, n_communities)
    suggestions = _generate_suggestions(cycles, hubs, n_communities, G, centralities)

    # ------------------------------------------------------------------
    # Graph-level stats
    # ------------------------------------------------------------------
    graph_stats = {
        "n_nodes": G.number_of_nodes(),
        "n_edges": G.number_of_edges(),
        "density": round(nx.density(G), 6),
        "is_connected": nx.is_connected(G) if G.number_of_nodes() > 0 else False,
        "n_components": nx.number_connected_components(G) if G.number_of_nodes() > 0 else 0,
    }

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    result: dict[str, Any] = {
        "meta": meta,
        "graph_stats": graph_stats,
        "nodes": nodes_out,
        "edges": edges_out,
        "communities": communities_out,
        "cycles": cycles,
        "hubs": hubs_out,
        "risk_score": risk_score,
        "investigation_suggestions": suggestions,
    }

    write_output(result, args.output)
    print(f"[network] Risk score: {risk_score}/10", file=sys.stderr)
    print(f"[network] Nodes: {len(nodes_out)}, Edges: {len(edges_out)}, "
          f"Communities: {len(communities_out)}, Cycles: {len(cycles)}, "
          f"Hubs: {len(hubs_out)}", file=sys.stderr)


if __name__ == "__main__":
    main()
