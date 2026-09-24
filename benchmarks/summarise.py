#!/usr/bin/env python3
"""Print Markdown tables from benchmarks/results/*.json (used to write RESULTS.md).

    python benchmarks/summarise.py                                   # everything that was run
    python benchmarks/summarise.py --companies kestrel,northfield    # restrict to a subset

Scores are recomputed from the per-question and per-company records in the
results files, so a subset table compares every system on the same items.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
if str(BENCH.parent) not in sys.path:
    sys.path.insert(0, str(BENCH.parent))

from benchmarks.scoring import summarise_qa  # noqa: E402

RESULTS = BENCH / "results"
CATS = ("lookup", "calculation", "related_party", "multi_hop")
SYSTEM_NAMES = {
    "lightrag:hybrid": "LightRAG hybrid", "lightrag:mix": "LightRAG mix", "lightrag:naive": "LightRAG naive",
    "lightrag:local": "LightRAG local", "lightrag:global": "LightRAG global",
    "bm25": "A: basic RAG (BM25 top-4)", "dense": "A: basic RAG (MiniLM top-4)",
    "whole_doc": "B: whole report, 1 call per question", "whole_doc_batched": "B: whole report, 1 call per company",
    "floor": "Floor: simple rules", "workbench_raw": "Workbench (raw tables)",
    "workbench_curated": "Workbench (auto-curated)", "llm_whole_doc": "B: one LLM call per company",
    "compliance_audit": "Compliance audit (3 sections)",
}


def pct(k: int, n: int) -> str:
    return f"{k}/{n} ({round(100 * k / n)}%)" if n else "–"


def qa_tables(path: Path, companies: set[str] | None) -> str:
    r = json.loads(path.read_text())
    items = [x for x in r["items"] if not companies or x["company"] in companies]
    lines = [f"**{r['run_label']}** (model: {r['conditions']['llm_model']})", "",
             "| System | Correct, strict [95% CI] | Lenient | " + " | ".join(CATS)
             + " | LLM calls / q | Prompt tokens / q | Median latency / q (s) |",
             "|---|---|---|" + "---|" * len(CATS) + "---|---|---|"]
    for system in r["summary"]:
        rows = [x for x in items if x["system"] == system]
        if not rows:
            continue
        s = summarise_qa(rows)
        lo, hi = s["accuracy_95ci"]
        cat_cells = [pct(sum(x["correct"] for x in rows if x["category"] == c),
                         sum(1 for x in rows if x["category"] == c)) for c in CATS]
        lenient = sum(x["lenient"] for x in rows)
        lines.append(f"| {SYSTEM_NAMES.get(system, system)} | {pct(s['correct'], s['n'])} "
                     f"[{round(100 * lo)}–{round(100 * hi)}%] | {pct(lenient, s['n'])} | " + " | ".join(cat_cells)
                     + f" | {s['llm_calls_per_q']:g} | {s['prompt_tokens_per_q']:,} | {s['latency_median_s']:.1f} |")
    stats = {k: v for k, v in r.get("index_stats", {}).items() if not companies or k in companies}
    if stats:
        lines += ["", "Knowledge-graph indexing (one store per company):", "",
                  "| Company | Status | Entities | Relations | LLM calls | Prompt tokens | Completion tokens | Wall time (s) |",
                  "|---|---|---|---|---|---|---|---|"]
        for slug, st in stats.items():
            lines.append(f"| {slug} | {','.join(st['doc_status'])} | {st['entities']} | {st['relations']} | "
                         f"{st['llm_calls']} | {st['prompt_tokens_est']:,} | {st['completion_tokens_est']:,} | "
                         f"{st['wall_seconds']:.1f} |")
    return "\n".join(lines)


def issue_tables(paths: list[Path], companies: set[str] | None) -> str:
    from benchmarks.run_issues import ground_truth, score

    truth = ground_truth()
    if companies:
        truth = {**truth, "companies": [c for c in truth["companies"] if c["slug"] in companies]}
    lines = ["| System | LLM | Companies | TP | FP | FN | Precision | Recall | F1 |",
             "|---|---|---|---|---|---|---|---|---|"]
    per_type: dict[str, dict[str, str]] = {}
    fmt = lambda x: "–" if x is None else f"{x:.2f}"  # noqa: E731
    for path in paths:
        r = json.loads(path.read_text())
        llm = r["conditions"].get("llm_model") or "none"
        for system, v in r["systems"].items():
            per_company = {k: x for k, x in v["per_company"].items() if not companies or k in companies}
            if not per_company:
                continue
            m = score(per_company, truth)
            name = SYSTEM_NAMES.get(system, system)
            label = f"{name} [{llm}]" if llm != "none" else name
            lines.append(f"| {name} | {llm} | {len(m['companies_scored'])} | {m['tp']} | {m['fp']} | {m['fn']} | "
                         f"{fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} |")
            for t, pt in m["per_type"].items():
                planted = len(pt["planted_in"])
                per_type.setdefault(t, {})[label] = f"{pt['tp']}/{planted}" + (f", {pt['fp']} FP" if pt["fp"] else "")
    systems = list(dict.fromkeys(k for d in per_type.values() for k in d))
    lines += ["", "Per issue type (planted issues found / planted; false positives):", "",
              "| Issue type | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
    for t, d in per_type.items():
        lines.append(f"| {t} | " + " | ".join(d.get(s, "–") for s in systems) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--companies", default=None, help="comma-separated company slugs")
    args = ap.parse_args()
    companies = set(args.companies.split(",")) if args.companies else None
    for p in sorted(RESULTS.glob("qa_*.json")):
        print(qa_tables(p, companies), "\n")
    issues = sorted(RESULTS.glob("issues_*.json"))
    if issues:
        print(issue_tables(issues, companies))


if __name__ == "__main__":
    main()
