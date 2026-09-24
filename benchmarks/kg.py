"""
Knowledge-graph helpers shared by the QA and issue-detection runs.

One LightRAG store per company (the README advises one storage directory per
process, so callers run each company in its own subprocess). Stores are built
with the repo's own factory, skills.shared.lightrag_init.get_rag_instance
(1200-token chunks, 100 overlap, all-MiniLM-L6-v2 embeddings), under
benchmarks/.work/rag/<kg model>/<company>/.

LightRAG's own response cache is switched off so that every LLM call goes
through benchmarks/llm.py, which caches and meters it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
DATA_DIR = BENCH_DIR / "data"
WORK_DIR = BENCH_DIR / ".work"

# Local CPU inference can be slow; LightRAG's defaults (180 s LLM, 30 s embedding)
# would cancel calls. Must be set before lightrag is imported.
os.environ.setdefault("LLM_TIMEOUT", "3600")
os.environ.setdefault("EMBEDDING_TIMEOUT", "600")


def store_dir(kg_model: str, slug: str) -> Path:
    return WORK_DIR / "rag" / kg_model.replace("/", "_").replace(":", "_") / slug


async def open_store(path: Path):
    from skills.shared.lightrag_init import get_rag_instance

    rag = await get_rag_instance(path)
    cfg = rag.llm_response_cache.global_config
    cfg["enable_llm_cache"] = False
    cfg["enable_llm_cache_for_entity_extract"] = False
    return rag


def _doc_status(path: Path) -> dict:
    f = path / "kv_store_doc_status.json"
    return json.loads(f.read_text()) if f.exists() else {}


def graph_size(path: Path) -> dict:
    gf = path / "graph_chunk_entity_relation.graphml"
    if not gf.exists():
        return {"entities": 0, "relations": 0}
    import networkx as nx

    g = nx.read_graphml(gf)
    return {"entities": g.number_of_nodes(), "relations": g.number_of_edges()}


async def ensure_index(slug: str, kg_provider) -> dict:
    """Index benchmarks/data/<slug>/annual_report.md once; return indexing stats."""
    from benchmarks.llm import Meter

    path = store_dir(kg_provider.model, slug)
    stats_file = path / "benchmark_index_stats.json"
    if stats_file.exists():
        return json.loads(stats_file.read_text())

    path.mkdir(parents=True, exist_ok=True)
    text = (DATA_DIR / slug / "annual_report.md").read_text(encoding="utf-8")
    rag = await open_store(path)
    kg_provider.meter = Meter()
    t0 = time.perf_counter()
    await rag.ainsert(text, file_paths=f"{slug}/annual_report.md")
    wall = time.perf_counter() - t0
    await rag.finalize_storages()
    statuses = sorted({v.get("status", "?") for v in _doc_status(path).values()})
    m = kg_provider.meter
    stats = {"company": slug, "kg_model": kg_provider.model, "doc_status": statuses,
             "wall_seconds": round(wall + m.replayed_seconds, 1), **m.as_dict(), **graph_size(path)}
    if statuses == ["processed"]:
        stats_file.write_text(json.dumps(stats, indent=2))
    return stats
