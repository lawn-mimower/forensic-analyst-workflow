#!/usr/bin/env python3
"""Print Markdown tables from benchmarks/results/*.json (used to write RESULTS.md).

    python benchmarks/summarise.py
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
CATS = ("lookup", "calculation", "related_party", "multi_hop")
SYSTEM_NAMES = {
    "lightrag:hybrid": "LightRAG hybrid", "lightrag:mix": "LightRAG mix", "lightrag:naive": "LightRAG naive",
    "lightrag:local": "LightRAG local", "lightrag:global": "LightRAG global",
    "bm25": "A: basic RAG (BM25)", "dense": "A: basic RAG (MiniLM)",
    "whole_doc": "B: whole report, 1 call per question", "whole_doc_batched": "B: whole report, 1 call per company",
    "floor": "Floor: simple rules", "workbench_raw": "Workbench (raw tables)",
    "workbench_curated": "Workbench (auto-curated)", "llm_whole_doc": "B: one LLM call per company",
    "compliance_audit": "Compliance audit (3 sections)",
}


def pct(k: int, n: int) -> str:
    return f"{k}/{n} ({round(100 * k / n)}%)" if n else "–"


def qa_tables(path: Path) -> str:
    r = json.loads(path.read_text())
    items = r["items"]
    lines = [f"### {r['run_label']} ({r['conditions']['llm_model']})", ""]
    if not r["complete"]:
        lines += [f"Incomplete run; missing items: { {k: len(v) for k, v in r['missing'].items()} }", ""]
    lines += ["| System | Correct (strict) [95% CI, %] | Lenient | " + " | ".join(CATS)
              + " | LLM calls / q | Prompt tokens / q | Median latency / q (s) |",
              "|---|---|---|" + "---|" * len(CATS) + "---|---|---|"]
    for system, s in r["summary"].items():
        if not s.get("n"):
            continue
        rows = [x for x in items if x["system"] == system]
        cat_cells = []
        for c in CATS:
            xs = [x for x in rows if x["category"] == c]
            cat_cells.append(pct(sum(x["correct"] for x in xs), len(xs)))
        lenient = sum(x["lenient"] for x in rows)
        ci = s.get("accuracy_95ci")
        strict = pct(s["correct"], s["n"]) + (f" [{round(100 * ci[0])}–{round(100 * ci[1])}]" if ci else "")
        lines.append(f"| {SYSTEM_NAMES.get(system, system)} | {strict} | {pct(lenient, s['n'])} | "
                     + " | ".join(cat_cells)
                     + f" | {s['llm_calls_per_q']:g} | {s['prompt_tokens_per_q']:,} | {s['latency_median_s']:.1f} |")
    if r.get("index_stats"):
        lines += ["", "Knowledge-graph indexing (one store per company):", "",
                  "| Company | Status | Entities | Relations | LLM calls | Prompt tokens | Completion tokens | Wall time (s) |",
                  "|---|---|---|---|---|---|---|---|"]
        tot = {"llm_calls": 0, "prompt_tokens_est": 0, "completion_tokens_est": 0, "wall_seconds": 0.0}
        for slug, st in r["index_stats"].items():
            lines.append(f"| {slug} | {','.join(st['doc_status'])} | {st['entities']} | {st['relations']} | "
                         f"{st['llm_calls']} | {st['prompt_tokens_est']:,} | {st['completion_tokens_est']:,} | "
                         f"{st['wall_seconds']:.1f} |")
            for k in tot:
                tot[k] += st[k]
        lines.append(f"| total | | | | {tot['llm_calls']} | {tot['prompt_tokens_est']:,} | "
                     f"{tot['completion_tokens_est']:,} | {tot['wall_seconds']:.1f} |")
    return "\n".join(lines)


def issue_tables(paths: list[Path]) -> str:
    lines = ["| System | LLM | Companies | TP | FP | FN | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|---|---|"]
    per_type: dict[str, dict[str, str]] = {}
    for path in paths:
        r = json.loads(path.read_text())
        llm = r["conditions"].get("llm_model") or "none"
        for system, v in r["systems"].items():
            m = v["metrics"]
            name = SYSTEM_NAMES.get(system, system)
            label = f"{name} [{llm}]" if llm != "none" else name
            fmt = lambda x: "–" if x is None else f"{x:.2f}"  # noqa: E731
            lines.append(f"| {name} | {llm} | {len(m['companies_scored'])} | {m['tp']} | {m['fp']} | {m['fn']} | "
                         f"{fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} |")
            for t, pt in m["per_type"].items():
                planted = len(pt["planted_in"])
                per_type.setdefault(t, {})[label] = f"{pt['tp']}/{planted}" + (f", {pt['fp']} FP" if pt["fp"] else "")
    systems = list(dict.fromkeys(k for d in per_type.values() for k in d))
    lines += ["", "Per issue type (planted issues found / planted, false positives):", "",
              "| Issue type | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
    for t, d in per_type.items():
        lines.append(f"| {t} | " + " | ".join(d.get(s, "–") for s in systems) + " |")
    return "\n".join(lines)


def main() -> None:
    for p in sorted(RESULTS.glob("qa_*.json")):
        print(qa_tables(p), "\n")
    issues = sorted(RESULTS.glob("issues_*.json"))
    if issues:
        print(issue_tables(issues))


if __name__ == "__main__":
    main()
