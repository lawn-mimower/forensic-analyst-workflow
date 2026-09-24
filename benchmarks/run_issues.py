#!/usr/bin/env python3
"""
Issue-detection benchmark: does each system flag the issues planted in the
synthetic companies? Scored as precision/recall over (company, issue type)
pairs against benchmarks/data/ground_truth.json.

Systems (--systems, comma-separated):
    floor               simple deterministic rules (benchmarks/floor_rules.py); no LLM
    workbench_raw       the repo's table pipeline and five forensic tests on the raw tables
                        (the path `python -m pipeline.test_normalization --run-skills` takes); no LLM
    workbench_curated   the same after the repo's auto-curation (frontend.pipeline_runner.run_pipeline,
                        the path the Streamlit app and the agent take); no LLM
    llm_whole_doc       Baseline B: one LLM call per company with the whole report and ledger,
                        asked to list red flags in the benchmark's categories
    compliance_audit    the repo's five-phase compliance audit on the company's LightRAG store,
                        restricted to three law sections (see COMPLIANCE_SECTIONS)

    python benchmarks/run_issues.py --systems floor,workbench_raw,workbench_curated --run-label deterministic
    python benchmarks/run_issues.py --systems llm_whole_doc,compliance_audit \\
        --config benchmarks/configs/ollama-llama3.2.yaml --run-label local-llama3.2

How each system's output becomes flags is fixed in this file (workbench_flags,
compliance_flags, llm_flags) and was set before the systems were run.
Results: benchmarks/results/issues_<run-label>.json. Per-company outputs are kept
in benchmarks/.work/<run-label>/issues/; --resume reuses them.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
ROOT = BENCH_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks import kg  # noqa: E402
from benchmarks.generate_dataset import ISSUE_TYPES  # noqa: E402
from benchmarks.scoring import precision_recall  # noqa: E402

DATA_DIR = BENCH_DIR / "data"
RESULTS_DIR = BENCH_DIR / "results"
FISCAL_YEAR = "2024-25"

# Law sections for the compliance audit and the issue type a VIOLATION on each maps to.
# The repo's law file has no entry for Section 188 or for CARO itself, so the closest
# sections are used; no section maps to rpt_threshold_no_approval or to the numeric types.
COMPLIANCE_SECTIONS = [
    ("companies_act_2013", "Companies Act, 2013", "section_143", "caro_missing"),
    ("income_tax_act_1961", "Income Tax Act, 1961", "section_269SS", "cash_loan_269ss"),
    ("icai_standards_on_auditing", "ICAI Standards on Auditing", "sa_550", "rp_omitted_from_schedule"),
]

LLM_SYSTEM_PROMPT = "You are a forensic accountant reviewing the financial statements of an Indian private company."


def ground_truth() -> dict:
    return json.loads((DATA_DIR / "ground_truth.json").read_text())


# ---------------------------------------------------------------------------
# Output -> flag mappings
# ---------------------------------------------------------------------------
def workbench_flags(outputs: dict[str, dict]) -> tuple[list[str], dict]:
    """Map the five skill reports to issue types using each skill's own flags."""
    flags: set[str] = set()
    b = outputs.get("benfords-analysis", {})
    first = b.get("tests", {}).get("first_digit", {}).get("verdict")
    if first == "NON_CONFORMING":
        flags.add("benford_nonconformity")
    d = outputs.get("duplicate-detector", {}).get("findings", {})
    groups = d.get("exact_duplicates", {}).get("duplicate_groups", 0)
    if groups >= 1:
        flags.add("duplicate_entries")
    ends_00 = d.get("round_number_concentration", {}).get("concentrations", {}).get("ends_00", {}).get("pct", 0)
    if ends_00 >= 15:  # the duplicate detector's own lowest round-number risk tier
        flags.add("round_number_entries")
    r = outputs.get("ratio-analyzer", {})
    if r.get("flagged_changes"):
        flags.add("ratio_anomaly")
    a = outputs.get("anomaly-detector", {})
    consensus = a.get("summary", {}).get("consensus_anomalies", 0)
    if consensus >= 1:
        flags.add("unusual_large_payment")
    n = outputs.get("network-analyzer", {})
    detail = {
        "benford_first_digit_verdict": first,
        "benford_overall_verdict": b.get("overall_verdict"),
        "benford_records": b.get("meta", {}).get("records_analyzed"),
        "exact_duplicate_groups": groups,
        "exact_duplicate_examples": [(x.get("account_name"), x.get("amount"), x.get("count"))
                                     for x in d.get("exact_duplicates", {}).get("details", [])[:5]],
        "round_ends_00_pct": round(ends_00, 1),
        "ratio_flags": [f.get("ratio") or f.get("account_category") for f in r.get("flagged_changes", [])],
        "ratio_risk_score": r.get("risk_score"),
        "anomaly_consensus": consensus,
        "anomaly_top": [(x.get("account_name"), x.get("amount")) for x in a.get("anomalies", [])[:3]],
        "network_cycles": len(n.get("cycles", []) or []),
        "network_risk_score": n.get("risk_score"),
        "risk_scores": {k: v.get("risk_score", v.get("overall_risk_score")) for k, v in outputs.items()},
        "not_mapped": "network-analyzer (no planted issue type corresponds to its cycle/hub findings)",
    }
    return sorted(flags), detail


def compliance_flags(out_dir: Path) -> tuple[list[str], dict]:
    questions = json.loads((out_dir / "atomic_questions.json").read_text())
    verdicts = {v["question_id"]: v for v in json.loads((out_dir / "verdicts.json").read_text())}
    profile = json.loads((out_dir / "document_profile.json").read_text())
    section_type = {sec: t for _, _, sec, t in COMPLIANCE_SECTIONS}
    flags: set[str] = set()
    per_section: dict[str, dict] = {}
    for q in questions:
        v = verdicts.get(q["question_id"], {}).get("verdict", "MISSING")
        s = per_section.setdefault(q["source_section"], {"questions": 0, "VIOLATION": 0, "COMPLIANT": 0,
                                                         "INSUFFICIENT_EVIDENCE": 0, "violations": []})
        s["questions"] += 1
        s[v] = s.get(v, 0) + 1
        if v == "VIOLATION":
            s["violations"].append({"question": q["question_text"],
                                    "reasoning": verdicts[q["question_id"]].get("reasoning", "")[:300]})
            flags.add(section_type[q["source_section"]])
    detail = {"applicable_categories": profile.get("applicable_category_keys"),
              "n_questions": len(questions), "per_section": per_section}
    return sorted(flags), detail


def llm_prompt(company: dict) -> str:
    d = DATA_DIR / company["slug"]
    cats = "\n".join(f"- {k}: {v}" for k, v in ISSUE_TYPES.items())
    return (f"Below are the annual report (directors' report extract, financial statements, notes and "
            f"auditor's report) and the expense-voucher ledger for FY 2024-25 of {company['name']}.\n\n"
            f"=== ANNUAL REPORT ===\n{(d / 'annual_report.md').read_text(encoding='utf-8')}\n"
            f"=== EXPENSE-VOUCHER LEDGER (CSV, amounts in rupees) ===\n"
            f"{(d / 'general_ledger.csv').read_text(encoding='utf-8')}\n"
            f"=== TASK ===\nList the compliance and forensic red flags you find in these documents. "
            f"Use only these categories:\n{cats}\n\n"
            "Return only JSON of the form {\"red_flags\": [{\"category\": \"<one of the categories above>\", "
            "\"evidence\": \"<one sentence>\"}]}. Return an empty list if you find no red flags.")


def llm_flags(raw: str) -> tuple[list[str], dict]:
    from benchmarks.llm import parse_json_block

    parsed = parse_json_block(raw)
    items = parsed.get("red_flags") if isinstance(parsed, dict) else parsed if isinstance(parsed, list) else None
    if not isinstance(items, list):
        return [], {"parse_error": True}
    flags, unknown = set(), []
    for it in items:
        cat = str(it.get("category", "") if isinstance(it, dict) else it).strip().lower()
        if cat in ISSUE_TYPES:
            flags.add(cat)
        else:
            unknown.append(cat)
    cats = [str(it.get("category", "") if isinstance(it, dict) else it).strip().lower() for it in items]
    return sorted(flags), {"parse_error": False, "n_red_flags": len(items), "unknown_categories": unknown,
                           "red_flag_categories": cats, "red_flags": items}


# ---------------------------------------------------------------------------
# Systems
# ---------------------------------------------------------------------------
def company_files(slug: str) -> list[Path]:
    return [DATA_DIR / slug / "financials.xlsx", DATA_DIR / slug / "general_ledger.csv"]


def run_workbench_raw(company: dict, work: Path) -> dict:
    from frontend.pipeline_runner import _skill_commands
    from pipeline.data_normalizer import DataNormalizer
    from pipeline.test_normalization import extract_tables

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    t0 = time.perf_counter()
    tables = [t for f in company_files(company["slug"]) for t in extract_tables(f)]
    db = work / "workbench.duckdb"
    normalizer = DataNormalizer(db_path=str(db))
    normalizer.initialize_schema()
    res = normalizer.normalize_and_load(tables, entity_name=company["name"], fiscal_year=FISCAL_YEAR)
    normalizer.close()
    outputs = {}
    for skill in _skill_commands(str(db), work / "skill_results", curated=False):
        cmd = [sys.executable, str(skill["script"]), *skill["args"], "--output", str(skill["output"])]
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(ROOT))
        if Path(skill["output"]).exists():
            outputs[skill["name"]] = json.loads(Path(skill["output"]).read_text())
    flags, detail = workbench_flags(outputs)
    return {"flags": flags, "detail": {**detail, "line_items": res.line_items_loaded,
                                       "related_party_rows": res.related_parties_loaded},
            "seconds": round(time.perf_counter() - t0, 1), "llm_calls": 0}


def run_workbench_curated(company: dict, work: Path) -> dict:
    from frontend.pipeline_runner import run_pipeline

    if work.exists():
        shutil.rmtree(work)
    t0 = time.perf_counter()
    res = run_pipeline(company_files(company["slug"]), extractor="docling", entity_name=company["name"],
                       fiscal_year=FISCAL_YEAR, output_dir=work, case_id=f"BENCH-{company['slug']}")
    if res.error:
        return {"flags": [], "detail": {"error": res.error}, "seconds": round(time.perf_counter() - t0, 1),
                "llm_calls": 0}
    outputs = {name: json.loads(Path(p).read_text()) for name, p in res.skill_outputs.items() if Path(p).exists()}
    flags, detail = workbench_flags(outputs)
    curation = [ln for ln in res.logs if "Curation:" in ln or "curat" in ln.lower()]
    return {"flags": flags, "detail": {**detail, "curation_log": curation},
            "seconds": round(time.perf_counter() - t0, 1), "llm_calls": 0}


async def run_llm_whole_doc(company: dict, llm) -> dict:
    from benchmarks.llm import Meter

    llm.meter = Meter()
    t0 = time.perf_counter()
    raw = await llm.generate(llm_prompt(company), system_prompt=LLM_SYSTEM_PROMPT, temperature=0)
    wall = time.perf_counter() - t0
    flags, detail = llm_flags(raw)
    return {"flags": flags, "detail": {**detail, "raw_response": raw},
            "seconds": round(wall + llm.meter.replayed_seconds, 1), **llm.meter.as_dict()}


async def compliance_worker(args) -> None:
    from benchmarks.llm import Meter, setup_registry
    from skills.shared import lightrag_init

    llms = setup_registry(args.config, max_new_calls=args.max_new_calls, min_interval_s=args.min_interval,
                          base_url=args.base_url, model=args.model)
    company = next(c for c in ground_truth()["companies"] if c["slug"] == args.company)
    index = await kg.ensure_index(company["slug"], llms["kg"])
    if index.get("doc_status") != ["processed"]:
        raise SystemExit(f"indexing {company['slug']} did not finish: {index}")

    # Restrict the laws to the benchmark subset (same approach as the test suite's small_laws fixture)
    full = lightrag_init.get_laws_data()
    subset = {"metadata": dict(full["metadata"], categories=[name for _, name, _, _ in COMPLIANCE_SECTIONS])}
    for cat, _, sec, _ in COMPLIANCE_SECTIONS:
        subset[cat] = {sec: full[cat][sec]}
    lightrag_init._laws_data = subset

    # Route LightRAG's own response cache off so every call is metered by benchmarks/llm.py
    original = lightrag_init.get_rag_instance

    async def get_rag_instance_uncached(storage_path=None):
        rag = await original(storage_path)
        rag.llm_response_cache.global_config["enable_llm_cache"] = False
        rag.llm_response_cache.global_config["enable_llm_cache_for_entity_extract"] = False
        return rag

    lightrag_init.get_rag_instance = get_rag_instance_uncached
    scripts = ROOT / "skills" / "compliance-checker" / "scripts"
    spec = importlib.util.spec_from_file_location("bench_compliance_pipeline", scripts / "run_pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out_dir = Path(args.work) / "compliance_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in (llms["kg"], llms["reasoning"]):
        p.meter = Meter()
    t0 = time.perf_counter()
    await mod.run_pipeline(storage=str(kg.store_dir(llms["kg"].model, company["slug"])),
                           output_dir=str(out_dir), max_concurrent=1)
    wall = time.perf_counter() - t0
    flags, detail = compliance_flags(out_dir)
    meters = [llms["kg"].meter] if llms["kg"] is llms["reasoning"] else [llms["kg"].meter, llms["reasoning"].meter]
    cost = {k: sum(m.as_dict()[k] for m in meters) for k in meters[0].as_dict()}
    replay = sum(m.replayed_seconds for m in meters)
    result = {"flags": flags, "detail": {**detail, "index": index}, "seconds": round(wall + replay, 1), **cost}
    (Path(args.work) / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
RAW_TEXT_KEYS = ("raw_response", "red_flags", "violations")


def public_result(r: dict) -> dict:
    """Committed form of a per-company result: model free text is left out (it stays in
    benchmarks/.work/<run-label>/issues/)."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in RAW_TEXT_KEYS}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return strip(r)


def score(per_company: dict[str, dict], truth: dict) -> dict:
    gold = {(c["slug"], t) for c in truth["companies"] for t in c["planted_issues"]}
    done = set(per_company)
    gold_done = {g for g in gold if g[0] in done}
    flags = {(slug, t) for slug, r in per_company.items() for t in r.get("flags", [])}
    per_type = {}
    for t in ISSUE_TYPES:
        g = {x for x in gold_done if x[1] == t}
        f = {x for x in flags if x[1] == t}
        per_type[t] = {"planted_in": sorted(s for s, _ in g), "flagged_in": sorted(s for s, _ in f),
                       "tp": len(g & f), "fp": len(f - g), "fn": len(g - f)}
    return {"companies_scored": sorted(done), **precision_recall(flags, gold_done), "per_type": per_type}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--systems", default="floor,workbench_raw,workbench_curated")
    ap.add_argument("--run-label", required=True)
    ap.add_argument("--config", default=None, help="model config, needed for llm_whole_doc and compliance_audit")
    ap.add_argument("--companies", default=None)
    ap.add_argument("--resume", action="store_true", help="reuse per-company results from an earlier run")
    ap.add_argument("--aggregate-only", action="store_true",
                    help="make no new runs; rewrite the results file from the per-company results so far")
    ap.add_argument("--max-new-calls", type=int, default=None)
    ap.add_argument("--model", default=None, help="override the model named in the config")
    ap.add_argument("--base-url", default=None,
                    help="override base_url of the openai_compat provider (e.g. a second Ollama server)")
    ap.add_argument("--min-interval", type=float, default=0.0)
    ap.add_argument("--worker", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--company", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--work", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.worker == "compliance":
        import os

        from benchmarks.llm import BudgetExhausted, QuotaExhausted

        code = 0
        try:
            asyncio.run(compliance_worker(args))
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
        # LightRAG can leave non-daemon threads behind; do not wait for them
        sys.stdout.flush()
        os._exit(code)

    truth = ground_truth()
    companies = [c for c in truth["companies"] if not args.companies or c["slug"] in args.companies.split(",")]
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    work_root = kg.WORK_DIR / args.run_label / "issues"
    llms = None
    if any(s in ("llm_whole_doc", "compliance_audit") for s in systems):
        if not args.config:
            ap.error("--config is required for llm_whole_doc and compliance_audit")
        from benchmarks.llm import setup_registry

        llms = setup_registry(args.config, max_new_calls=args.max_new_calls, min_interval_s=args.min_interval,
                          base_url=args.base_url, model=args.model)

    results: dict = {}
    stopped = None
    for system in systems:
        per_company: dict[str, dict] = {}
        for c in companies:
            work = work_root / system / c["slug"]
            cached = work.parent / f"{c['slug']}.json"
            if (args.resume or args.aggregate_only) and cached.exists():
                per_company[c["slug"]] = json.loads(cached.read_text())
                continue
            if stopped or args.aggregate_only:
                break
            print(f"[{system}] {c['slug']}", flush=True)
            try:
                if system == "floor":
                    from benchmarks import floor_rules

                    t0 = time.perf_counter()
                    r = floor_rules.evaluate(DATA_DIR / c["slug"])
                    r = {"flags": r["flags"], "detail": r["evidence"],
                         "seconds": round(time.perf_counter() - t0, 1), "llm_calls": 0}
                elif system == "workbench_raw":
                    r = run_workbench_raw(c, work)
                elif system == "workbench_curated":
                    r = run_workbench_curated(c, work)
                elif system == "llm_whole_doc":
                    r = asyncio.run(run_llm_whole_doc(c, llms["reasoning"]))
                elif system == "compliance_audit":
                    work.mkdir(parents=True, exist_ok=True)
                    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "compliance",
                           "--company", c["slug"], "--config", args.config, "--run-label", args.run_label,
                           "--work", str(work), "--min-interval", str(args.min_interval)]
                    if args.base_url:
                        cmd += ["--base-url", args.base_url]
                    if args.model:
                        cmd += ["--model", args.model]
                    if args.max_new_calls is not None:
                        cmd += ["--max-new-calls", str(max(0, args.max_new_calls - llms["budget"].used))]
                    rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
                    if rc != 0:
                        stopped = f"compliance worker for {c['slug']} exited with code {rc}"
                        break
                    r = json.loads((work / "result.json").read_text())
                else:
                    ap.error(f"unknown system {system}")
            except Exception as exc:
                from benchmarks.llm import BudgetExhausted, QuotaExhausted

                if isinstance(exc, (BudgetExhausted, QuotaExhausted)):
                    stopped = f"{type(exc).__name__}: {exc}"
                    print(f"STOPPED: {stopped}")
                    break
                raise
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(r, indent=2, ensure_ascii=False))
            per_company[c["slug"]] = r
            print(f"   flags: {r['flags']}", flush=True)
        results[system] = {"per_company": {k: public_result(v) for k, v in per_company.items()},
                           "metrics": score(per_company, truth)}

    out = {
        "benchmark": "issue_detection",
        "run_label": args.run_label,
        "complete": all(len(v["per_company"]) == len(companies) for v in results.values()),
        "stopped_early": stopped,
        "conditions": {
            "llm_model": llms["model"] if llms else None,
            "llm_provider": llms["provider"] if llms else None,
            "llm_endpoint": llms.get("base_url") if llms else None,
            "config": str(Path(args.config).resolve().relative_to(ROOT)) if args.config else None,
            "companies": [c["slug"] for c in companies],
            "unit_of_scoring": "(company, issue type) pairs; micro-averaged precision and recall",
            "compliance_sections": [f"{cat}/{sec} -> {t}" for cat, _, sec, t in COMPLIANCE_SECTIONS],
            "workbench_inputs": "financials.xlsx and general_ledger.csv (the report text is not used)",
            "llm_inputs": "annual_report.md and general_ledger.csv in one prompt",
            "compliance_inputs": "LightRAG store built from annual_report.md",
        },
        "gold": {c["slug"]: c["planted_issues"] for c in companies},
        "systems": results,
    }
    if llms:
        out["new_llm_calls_main_process"] = llms["budget"].used
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"issues_{args.run_label}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {path.relative_to(ROOT)} (complete: {out['complete']})")
    for s, v in results.items():
        m = v["metrics"]
        print(f"  {s:18s} P={m['precision']} R={m['recall']} F1={m['f1']} tp={m['tp']} fp={m['fp']} fn={m['fn']}")


if __name__ == "__main__":
    main()
