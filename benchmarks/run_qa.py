#!/usr/bin/env python3
"""
Question-answering benchmark over the synthetic annual reports.

Systems (pick with --systems, comma-separated):
    lightrag:<mode>     the repo's LightRAG knowledge graph, mode in local, global, hybrid, mix, naive
                        (one store per company, built with skills.shared.lightrag_init)
    bm25, dense         Baseline A: fixed 256-token chunks, top-4 by BM25 or MiniLM cosine, one LLM call
    whole_doc           Baseline B: the whole report in one prompt, one call per question
    whole_doc_batched   Baseline B, cheapest form: the whole report and all of that company's
                        questions in one call per company (answers returned as JSON)

Every system in a run uses the same LLM, chosen with --config (a model_config.yaml variant):
the knowledge graph is built and queried with it, and it answers for the baselines.

    python benchmarks/run_qa.py --config benchmarks/configs/ollama-llama3.2.yaml \\
        --run-label local-llama3.2 --systems lightrag:hybrid,bm25,dense,whole_doc,whole_doc_batched

Results go to benchmarks/results/qa_<run-label>.json. Per-question records are
appended to benchmarks/.work/<run-label>/qa_items.jsonl; --resume skips the
ones already there. LLM responses are cached in benchmarks/.cache/.
--max-new-calls caps uncached LLM calls for the run (useful on free API tiers);
when the cap or a provider quota is hit, the partial results are still written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
ROOT = BENCH_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks import kg  # noqa: E402  (sets LightRAG timeouts before lightrag is imported)
from benchmarks.llm import BudgetExhausted, Meter, QuotaExhausted, parse_json_block, setup_registry  # noqa: E402
from benchmarks.scoring import parsed_answer, score_answer, summarise_qa  # noqa: E402

DATA_DIR = BENCH_DIR / "data"
RESULTS_DIR = BENCH_DIR / "results"
LIGHTRAG_MODES = ("local", "global", "hybrid", "mix", "naive")
TOP_K = 40  # the repo's query CLI default

SYSTEM_PROMPT = "You answer questions about a company's financial statements using only the text provided."
ANSWER_INSTRUCTION = (
    "Answer briefly and include one line that starts with 'ANSWER:' followed by only the answer itself: "
    "a number without units or thousands separators, in the unit the question asks for "
    "(e.g. 'ANSWER: 1520.75'), a name (e.g. 'ANSWER: Asha Rao') or a date (e.g. 'ANSWER: 5 June 2024')."
)


def load_questions(companies: list[str] | None) -> list[dict]:
    qs = json.loads((DATA_DIR / "qa.json").read_text())
    return [q for q in qs if not companies or q["company"] in companies]


def company_names() -> dict[str, str]:
    gt = json.loads((DATA_DIR / "ground_truth.json").read_text())
    return {c["slug"]: c["name"] for c in gt["companies"]}


def report_text(slug: str) -> str:
    return (DATA_DIR / slug / "annual_report.md").read_text(encoding="utf-8")


class ItemStore:
    def __init__(self, path: Path, resume: bool):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not resume and path.exists():
            path.unlink()
        self.done = set()
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.done.add((r["system"], r["qid"]))

    def has(self, system: str, qid: str) -> bool:
        return (system, qid) in self.done

    def add(self, rec: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.done.add((rec["system"], rec["qid"]))


def make_record(system: str, q: dict, response: str | None, meter: Meter, wall: float,
                share: float = 1.0, error: str | None = None) -> dict:
    s = score_answer(q, response)
    m = meter.as_dict()
    return {"system": system, "qid": q["id"], "company": q["company"], "category": q["category"],
            "response": response, **s, "error": error,
            "latency_s": round((wall + meter.replayed_seconds) * share, 1),
            **{k: (round(v * share, 1) if isinstance(v, (int, float)) else v) for k, v in m.items()}}


async def answer_with_context(llm, name: str, context: str, question: str) -> str:
    prompt = f"Document: {name}\n\n{context}\n\nQuestion: {question}\n\n{ANSWER_INSTRUCTION}"
    return await llm.generate(prompt, system_prompt=SYSTEM_PROMPT, temperature=0)


# ---------------------------------------------------------------------------
# Baselines (run in the main process)
# ---------------------------------------------------------------------------
async def run_baselines(systems: list[str], questions: list[dict], llm, store: ItemStore) -> None:
    from benchmarks.basic_rag import Retriever

    names = company_names()
    retrievers: dict[tuple[str, str], Retriever] = {}
    for system in systems:
        if system == "whole_doc_batched":
            await run_batched(questions, llm, store, names)
            continue
        for q in questions:
            if store.has(system, q["id"]):
                continue
            slug, text = q["company"], report_text(q["company"])
            llm.meter = Meter()
            t0 = time.perf_counter()
            if system == "whole_doc":
                context = text
            else:
                key = (system, slug)
                if key not in retrievers:
                    retrievers[key] = Retriever(text, method=system)
                context = "\n\n---\n\n".join(retrievers[key].retrieve(q["question"]))
            response = await answer_with_context(llm, names[slug], context, q["question"])
            store.add(make_record(system, q, response, llm.meter, time.perf_counter() - t0))
            print(f"  {system:18s} {q['id']:14s} {store_last_status(store)}", flush=True)


def store_last_status(store: ItemStore) -> str:
    last = store.path.read_text().splitlines()[-1]
    r = json.loads(last)
    return f"{'OK ' if r['correct'] else '-- '} {r['span'][:60]!r}"


async def run_batched(questions: list[dict], llm, store: ItemStore, names: dict) -> None:
    by_company: dict[str, list[dict]] = {}
    for q in questions:
        by_company.setdefault(q["company"], []).append(q)
    for slug, qs in by_company.items():
        todo = [q for q in qs if not store.has("whole_doc_batched", q["id"])]
        if not todo:
            continue
        listing = "\n".join(f"- id: {q['id']}\n  question: {q['question']}" for q in qs)
        prompt = (f"Document: {names[slug]}\n\n{report_text(slug)}\n\n"
                  f"Answer the following questions about {names[slug]} using only the document above.\n\n"
                  f"Questions:\n{listing}\n\n"
                  "Return only JSON of the form {\"answers\": [{\"id\": \"<question id>\", \"answer\": \"<value>\"}]}, "
                  "one entry per question, where each value is only the answer: a number without units or "
                  "thousands separators (in the unit the question asks for), a name, or a date.")
        llm.meter = Meter()
        t0 = time.perf_counter()
        raw = await llm.generate(prompt, system_prompt=SYSTEM_PROMPT, temperature=0)
        wall = time.perf_counter() - t0
        parsed = parse_json_block(raw)
        answers = {}
        if isinstance(parsed, dict) and isinstance(parsed.get("answers"), list):
            answers = {str(a.get("id")): str(a.get("answer")) for a in parsed["answers"] if isinstance(a, dict)}
        for q in qs:
            ans = answers.get(q["id"])
            response = None if ans is None else f"ANSWER: {ans}"
            rec = make_record("whole_doc_batched", q, response, llm.meter, wall, share=1 / len(qs),
                              error=None if ans is not None else "no answer parsed for this id")
            rec["batched_raw_response"] = raw
            store.add(rec)
        print(f"  whole_doc_batched  {slug}: {sum(q['id'] in answers for q in qs)}/{len(qs)} answers parsed", flush=True)


# ---------------------------------------------------------------------------
# LightRAG (one subprocess per company)
# ---------------------------------------------------------------------------
async def lightrag_worker(args) -> None:
    from lightrag import QueryParam

    llms = setup_registry(args.config, max_new_calls=args.max_new_calls, min_interval_s=args.min_interval,
                          base_url=args.base_url, model=args.model)
    kg_llm = llms["kg"]
    slug = args.company
    store = ItemStore(Path(args.items), resume=True)
    modes = [s.split(":", 1)[1] for s in args.systems.split(",") if s.startswith("lightrag:")]
    questions = [q for q in load_questions([slug])]
    todo = [(m, q) for m in modes for q in questions if not store.has(f"lightrag:{m}", q["id"])]
    stats = await kg.ensure_index(slug, kg_llm)
    stats_path = Path(args.items).parent / "index_stats" / f"{slug}.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2))
    print(f"  index {slug}: {stats}", flush=True)
    if stats.get("doc_status") != ["processed"]:
        raise SystemExit(f"indexing {slug} did not finish: {stats.get('doc_status')}")
    if not todo:
        return
    rag = await kg.open_store(kg.store_dir(kg_llm.model, slug))
    for mode, q in todo:
        kg_llm.meter = Meter()
        t0 = time.perf_counter()
        error = None
        try:
            response = await rag.aquery(q["question"], param=QueryParam(
                mode=mode, top_k=TOP_K, user_prompt=ANSWER_INSTRUCTION))
        except (BudgetExhausted, QuotaExhausted):
            raise
        except Exception as exc:  # LightRAG usually logs and returns None instead
            response, error = None, f"{type(exc).__name__}: {exc}"[:300]
        if response is None and error is None:
            error = "LightRAG returned no response"
        store.add(make_record(f"lightrag:{mode}", q, response, kg_llm.meter, time.perf_counter() - t0,
                              error=error))
        print(f"  lightrag:{mode:7s} {q['id']:14s} {store_last_status(store)}", flush=True)
    await rag.finalize_storages()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
PUBLIC_FIELDS = ("system", "qid", "company", "category", "correct", "lenient", "format_ok", "latency_s",
                 "llm_calls", "prompt_tokens_est", "completion_tokens_est")


def public_item(rec: dict, q: dict) -> dict:
    """The committed form of an item: scores, the parsed answer and costs, without raw model text
    (raw responses stay in benchmarks/.work/<run-label>/qa_items.jsonl)."""
    out = {k: rec.get(k) for k in PUBLIC_FIELDS}
    out["answer"] = parsed_answer(q, rec.get("span") or "")
    out["error"] = (rec.get("error") or "").split(":")[0] or None
    return out


def aggregate(args, systems: list[str], questions: list[dict], llm_info: dict, stopped: str | None) -> dict:
    items_path = Path(args.items)
    items = [json.loads(x) for x in items_path.read_text().splitlines() if x.strip()] if items_path.exists() else []
    qids = {q["id"] for q in questions}
    qmap = {q["id"]: q for q in questions}
    items = [r for r in items if r["qid"] in qids and r["system"] in systems]
    for r in items:  # score at aggregation time, so scoring fixes need no new LLM calls
        r.update(score_answer(qmap[r["qid"]], r.get("response")))
    by_system = {s: [r for r in items if r["system"] == s] for s in systems}
    index_stats = {}
    stats_dir = items_path.parent / "index_stats"
    if stats_dir.exists():
        for f in sorted(stats_dir.glob("*.json")):
            index_stats[f.stem] = json.loads(f.read_text())
    missing = {s: sorted(qids - {r["qid"] for r in rs}) for s, rs in by_system.items()}
    return {
        "benchmark": "qa",
        "run_label": args.run_label,
        "complete": not any(missing.values()),
        "stopped_early": stopped,
        "conditions": {
            "llm_provider": llm_info["provider"], "llm_model": llm_info["model"],
            "llm_endpoint": llm_info.get("base_url"),
            "config": str(Path(args.config).resolve().relative_to(ROOT)),
            "temperature": "0 for baseline calls; LightRAG calls use the model default "
                           "(0 for the local llama3.2-ctx32k variant)",
            "n_questions": len(questions),
            "lightrag": {"top_k": TOP_K, "chunk_token_size": 1200, "chunk_overlap_token_size": 100,
                         "embedding": "all-MiniLM-L6-v2", "store": "one per company"},
            "basic_rag": {"chunk_tokens": 256, "overlap": 32, "top_k": 4},
            "token_counts": "o200k_base estimates of prompt (system + history + user) and response text",
            "latency": "wall-clock per question on the machine that ran it; batched calls are split "
                       "evenly across that company's questions",
        },
        "summary": {s: summarise_qa(rs) for s, rs in by_system.items()},
        "index_stats": index_stats,
        "missing": {s: m for s, m in missing.items() if m},
        "items": [public_item(r, qmap[r["qid"]]) for r in items],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, help="model config (see benchmarks/configs/)")
    ap.add_argument("--run-label", required=True)
    ap.add_argument("--systems", default="lightrag:hybrid,bm25,dense,whole_doc,whole_doc_batched")
    ap.add_argument("--companies", default=None, help="comma-separated slugs (default: all)")
    ap.add_argument("--resume", action="store_true", help="keep finished items from an earlier run")
    ap.add_argument("--aggregate-only", action="store_true",
                    help="make no LLM calls; rewrite the results file from the items recorded so far")
    ap.add_argument("--max-new-calls", type=int, default=None, help="cap on uncached LLM calls")
    ap.add_argument("--model", default=None, help="override the model named in the config")
    ap.add_argument("--base-url", default=None,
                    help="override base_url of the openai_compat provider (e.g. a second Ollama server)")
    ap.add_argument("--min-interval", type=float, default=0.0,
                    help="seconds between uncached LLM calls (pacing for rate-limited APIs; not counted as latency)")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--company", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--items", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()
    args.items = args.items or str(kg.WORK_DIR / args.run_label / "qa_items.jsonl")

    if args.worker:
        code = 0
        try:
            asyncio.run(lightrag_worker(args))
        except (BudgetExhausted, QuotaExhausted) as exc:
            print(f"STOPPED: {type(exc).__name__}: {exc}", flush=True)
            code = 3
        except SystemExit as exc:
            print(exc, flush=True)
            code = 1
        except Exception:
            import traceback

            traceback.print_exc()
            code = 1
        finally:
            from skills.shared import lightrag_init

            used = getattr(getattr(lightrag_init._kg_provider, "budget", None), "used", 0)
            (Path(args.items).parent / f"worker_new_calls_{args.company}.txt").write_text(str(used))
        # LightRAG can leave non-daemon threads behind; do not wait for them
        sys.stdout.flush()
        os._exit(code)

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    for s in systems:
        if s.startswith("lightrag:"):
            if s.split(":", 1)[1] not in LIGHTRAG_MODES:
                ap.error(f"unknown LightRAG mode in {s}")
        elif s not in ("bm25", "dense", "whole_doc", "whole_doc_batched"):
            ap.error(f"unknown system {s}")
    companies = args.companies.split(",") if args.companies else None
    questions = load_questions(companies)
    store = ItemStore(Path(args.items), resume=args.resume or args.aggregate_only)
    llms = setup_registry(args.config, max_new_calls=args.max_new_calls, min_interval_s=args.min_interval,
                          base_url=args.base_url, model=args.model)
    stopped = None

    baseline_systems = [s for s in systems if not s.startswith("lightrag:")]
    if args.aggregate_only:
        stopped = "aggregated without running (--aggregate-only)"
    try:
        if baseline_systems and not stopped:
            asyncio.run(run_baselines(baseline_systems, questions, llms["reasoning"], store))
    except (BudgetExhausted, QuotaExhausted) as exc:
        stopped = f"{type(exc).__name__}: {exc}"
        print(f"STOPPED: {stopped}")

    lr_systems = [s for s in systems if s.startswith("lightrag:")]
    if lr_systems and not stopped:
        remaining = None if args.max_new_calls is None else max(0, args.max_new_calls - llms["budget"].used)
        for slug in sorted({q["company"] for q in questions}, key=[q["company"] for q in questions].index):
            cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--company", slug,
                   "--config", args.config, "--run-label", args.run_label, "--systems", ",".join(lr_systems),
                   "--items", args.items]
            if remaining is not None:
                cmd += ["--max-new-calls", str(remaining)]
            if args.min_interval:
                cmd += ["--min-interval", str(args.min_interval)]
            if args.base_url:
                cmd += ["--base-url", args.base_url]
            if args.model:
                cmd += ["--model", args.model]
            print(f"[lightrag] {slug}", flush=True)
            rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
            used_file = Path(args.items).parent / f"worker_new_calls_{slug}.txt"
            if remaining is not None and used_file.exists():
                remaining = max(0, remaining - int(used_file.read_text() or 0))
            if rc == 3:
                stopped = f"LLM call cap or quota reached during LightRAG ({slug})"
                break
            if rc != 0:
                stopped = f"LightRAG worker for {slug} exited with code {rc}"
                break

    result = aggregate(args, systems, questions, llms, None if args.aggregate_only else stopped)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"qa_{args.run_label}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {out.relative_to(ROOT)}  (complete: {result['complete']})")
    for s, summ in result["summary"].items():
        if summ.get("n"):
            print(f"  {s:18s} n={summ['n']:2d} acc={summ['accuracy']:.3f} lenient={summ['lenient_accuracy']:.3f} "
                  f"calls/q={summ['llm_calls_per_q']} ptok/q={summ['prompt_tokens_per_q']} "
                  f"lat_med={summ['latency_median_s']}s")
    print(f"  new LLM calls this run (main process): {llms['budget'].used}")


if __name__ == "__main__":
    main()
