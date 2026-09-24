"""Tests for the benchmark harness: answer scoring, issue scoring, the floor rules,
the output-to-flag mappings, the LLM cache and the dataset generator.
No LLM calls are made."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import floor_rules, generate_dataset, scoring
from benchmarks.basic_rag import BM25, chunk_text
from benchmarks.llm import BudgetExhausted, CachedProvider, CallBudget, Meter, parse_json_block
from benchmarks.run_issues import compliance_flags, llm_flags, public_result, score, workbench_flags

DATA = Path(__file__).resolve().parent.parent / "benchmarks" / "data"


def q_num(gold, unit="lakhs"):
    return {"answer_type": "number", "gold": gold, "unit": unit}


def q_text(*aliases):
    return {"answer_type": "text", "gold": aliases[0], "aliases": list(aliases)}


# ---------------------------------------------------------------------------
# Answer extraction and matching
# ---------------------------------------------------------------------------
def test_answer_span_prefers_last_marker():
    resp = "Revenue was 3,978.25 last year.\nANSWER: 4386.40\n\n### References\n- [1] report"
    assert scoring.answer_span(resp) == ("4386.40", True)
    assert scoring.answer_span("**ANSWER:** Rohan Kulkarni") == ("Rohan Kulkarni", True)
    assert scoring.answer_span("Some text\n\n612.35\n") == ("612.35", False)
    assert scoring.answer_span(None) == ("", False)


def test_numbers_skip_fiscal_years_dates_and_notes():
    assert scoring.numbers_in("FY 2024-25: Rs. 4,386.40 lakhs") == [4386.40]
    assert scoring.numbers_in("as at 31 March 2025, 1,102.80") == [1102.80]
    assert scoring.numbers_in("see Note 27; 1,85,00,000") == [18500000.0]
    assert scoring.numbers_in("(51.15) and -3") == [-51.15, -3.0]


@pytest.mark.parametrize("span,gold,unit,ok", [
    ("4386.40", 4386.40, "lakhs", True),
    ("Rs. 4,386.4 lakhs", 4386.40, "lakhs", True),
    ("4386", 4386.40, "lakhs", True),                 # rounded to the rupee lakh
    ("4390", 4386.40, "lakhs", False),                # not a rounding of 4386.40
    ("51.2", 51.15, "lakhs", True),
    ("51.35", 51.15, "lakhs", False),                 # wrong subtraction
    ("43.86 crore", 4386.40, "lakhs", True),
    ("Rs. 4,80,00,000", 480.00, "lakhs", True),       # rupees
    ("480", 4.80, "lakhs", False),
    ("9.07%", 9.07, "percent", True),
    ("9.1", 9.07, "percent", True),
    ("9.3", 9.07, "percent", False),
    ("95.046", 95.05, "percent", True),               # gold is itself rounded to 2 places
    ("0.0907", 9.07, "percent", True),
    ("FY 2024-25", 51.15, "lakhs", False),
    ("", 51.15, "lakhs", False),
])
def test_number_matching(span, gold, unit, ok):
    assert scoring.number_matches(span, gold, unit) is ok


def test_first_number_is_scored_but_lenient_checks_all():
    q = q_num(51.15)
    s = scoring.score_answer(q, "It went from 561.20 to 612.35.\nANSWER: 612.35 (increase of 51.15)")
    assert s["correct"] is False and s["lenient"] is True and s["format_ok"] is True


def test_text_matching_normalises():
    aliases = ["Kestrel Estates LLP", "Kestrel Estates"]
    assert scoring.text_matches("M/s. Kestrel Estates LLP", aliases)
    assert scoring.text_matches("kestrel estates", aliases)
    assert not scoring.text_matches("Kestrel Polymers", aliases)
    assert scoring.text_matches("Mrs. Anjali Hegde", ["Anjali Hegde"])
    assert scoring.text_matches("Kaveri Assurance and Co", ["Kaveri Assurance & Co."])
    assert not scoring.text_matches("Hegde", ["Anjali Hegde"])


@pytest.mark.parametrize("span", ["20 August 2024", "20th Aug, 2024", "August 20, 2024",
                                  "2024-08-20", "20/08/2024", "20.08.2024"])
def test_dates(span):
    q = {"answer_type": "date", "gold": "2024-08-20"}
    assert scoring.score_answer(q, f"ANSWER: {span}")["correct"]


def test_date_mismatch():
    q = {"answer_type": "date", "gold": "2024-08-20"}
    assert not scoring.score_answer(q, "ANSWER: 30 July 2024")["correct"]


def test_parsed_answer_is_compact():
    assert scoring.parsed_answer(q_num(1.0), "Rs. 4,386.40 lakhs") == "4386.400"
    assert scoring.parsed_answer(q_text("x"), "M/s. Kestrel Estates LLP.") == "kestrel estates llp"
    assert scoring.parsed_answer({"answer_type": "date"}, "on 20 August 2024") == "2024-08-20"
    assert scoring.parsed_answer(q_num(1.0), "not stated") is None


def test_summarise_qa():
    items = [
        {"category": "lookup", "correct": True, "lenient": True, "format_ok": True, "latency_s": 2.0,
         "llm_calls": 1, "prompt_tokens_est": 100, "completion_tokens_est": 10},
        {"category": "multi_hop", "correct": False, "lenient": True, "format_ok": False, "latency_s": 4.0,
         "llm_calls": 2, "prompt_tokens_est": 300, "completion_tokens_est": 30},
    ]
    s = scoring.summarise_qa(items)
    assert (s["n"], s["correct"], s["accuracy"], s["lenient_accuracy"]) == (2, 1, 0.5, 1.0)
    assert s["by_category"] == {"lookup": {"n": 1, "accuracy": 1.0}, "multi_hop": {"n": 1, "accuracy": 0.0}}
    assert (s["llm_calls_per_q"], s["prompt_tokens_per_q"], s["latency_median_s"]) == (1.5, 200, 3.0)
    assert scoring.summarise_qa([]) == {"n": 0}


def test_wilson_interval():
    assert scoring.wilson_interval(0, 0) is None
    lo, hi = scoring.wilson_interval(15, 30)
    assert lo < 0.5 < hi and round(hi - lo, 2) == 0.34
    assert scoring.wilson_interval(30, 30)[1] == 1.0


# ---------------------------------------------------------------------------
# Issue scoring
# ---------------------------------------------------------------------------
def test_precision_recall():
    gold = {("a", "x"), ("a", "y"), ("b", "x")}
    flags = {("a", "x"), ("b", "y")}
    m = scoring.precision_recall(flags, gold)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 2)
    assert (m["precision"], m["recall"], m["f1"]) == (0.5, 0.333, 0.4)
    assert scoring.precision_recall(set(), gold)["precision"] is None
    assert scoring.precision_recall(set(), gold)["recall"] == 0.0


def test_score_counts_only_completed_companies():
    truth = {"companies": [{"slug": "a", "planted_issues": ["duplicate_entries"]},
                           {"slug": "b", "planted_issues": ["caro_missing"]}]}
    out = score({"a": {"flags": ["duplicate_entries", "ratio_anomaly"]}}, truth)
    assert out["companies_scored"] == ["a"]
    assert (out["tp"], out["fp"], out["fn"]) == (1, 1, 0)
    assert out["per_type"]["duplicate_entries"] == {"planted_in": ["a"], "flagged_in": ["a"], "tp": 1, "fp": 0, "fn": 0}


def test_workbench_flag_mapping():
    outputs = {
        "benfords-analysis": {"tests": {"first_digit": {"verdict": "NON_CONFORMING"}}},
        "duplicate-detector": {"findings": {
            "exact_duplicates": {"duplicate_groups": 2, "details": []},
            "round_number_concentration": {"concentrations": {"ends_00": {"pct": 14.9}}}}},
        "ratio-analyzer": {"flagged_changes": [{"type": "ratio_change", "ratio": "gross_margin"}]},
        "anomaly-detector": {"summary": {"consensus_anomalies": 0}},
        "network-analyzer": {"cycles": [["a", "b"]]},
    }
    flags, detail = workbench_flags(outputs)
    assert flags == ["benford_nonconformity", "duplicate_entries", "ratio_anomaly"]
    assert detail["network_cycles"] == 1
    outputs["benfords-analysis"]["tests"]["first_digit"]["verdict"] = "MARGINALLY_NON_CONFORMING"
    outputs["duplicate-detector"]["findings"]["round_number_concentration"]["concentrations"]["ends_00"]["pct"] = 15
    outputs["anomaly-detector"]["summary"]["consensus_anomalies"] = 3
    flags, _ = workbench_flags(outputs)
    assert flags == ["duplicate_entries", "ratio_anomaly", "round_number_entries", "unusual_large_payment"]


def test_llm_flag_parsing():
    raw = ('```json\n{"red_flags": [{"category": "caro_missing", "evidence": "No CARO."},'
           ' {"category": "Duplicate_Entries", "evidence": "x"}, {"category": "going_concern"}]}\n```')
    flags, detail = llm_flags(raw)
    assert flags == ["caro_missing", "duplicate_entries"]
    assert detail["unknown_categories"] == ["going_concern"] and not detail["parse_error"]
    assert llm_flags("I found nothing wrong.") == ([], {"parse_error": True})
    assert public_result({"flags": flags, "detail": detail})["detail"].get("red_flags") is None


def test_compliance_flag_mapping(tmp_path):
    (tmp_path / "document_profile.json").write_text(json.dumps({"applicable_category_keys": ["companies_act_2013"]}))
    (tmp_path / "atomic_questions.json").write_text(json.dumps([
        {"question_id": "Q1", "question_text": "CARO?", "source_section": "section_143"},
        {"question_id": "Q2", "question_text": "Cash loan?", "source_section": "section_269SS"},
        {"question_id": "Q3", "question_text": "RP disclosed?", "source_section": "sa_550"},
    ]))
    (tmp_path / "verdicts.json").write_text(json.dumps([
        {"question_id": "Q1", "verdict": "VIOLATION", "reasoning": "No CARO annexure."},
        {"question_id": "Q2", "verdict": "COMPLIANT", "reasoning": ""},
        {"question_id": "Q3", "verdict": "INSUFFICIENT_EVIDENCE", "reasoning": ""},
    ]))
    flags, detail = compliance_flags(tmp_path)
    assert flags == ["caro_missing"]
    assert detail["per_section"]["section_143"]["VIOLATION"] == 1


# ---------------------------------------------------------------------------
# Baselines, cache and dataset
# ---------------------------------------------------------------------------
def test_bm25_ranks_the_matching_chunk_first():
    docs = ["revenue from operations grew", "related party rent paid to a director", "cash and bank"]
    scores = BM25(docs).scores("rent paid to director")
    assert max(range(3), key=scores.__getitem__) == 1


def test_chunking_overlaps():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk_text(text, size=256, overlap=32)
    assert len(chunks) > 5
    assert chunks[0].split()[-1] in chunks[1]


def test_parse_json_block():
    assert parse_json_block('Here you go: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    assert parse_json_block("```json\n[1, 2]\n```") == [1, 2]
    assert parse_json_block("no json here") is None


class _Echo:
    model = "echo-model"

    def __init__(self):
        self.calls = 0

    async def generate(self, prompt, **kwargs):
        self.calls += 1
        return f"echo: {prompt}"


async def test_cached_provider_meters_and_replays(tmp_path):
    inner = _Echo()
    llm = CachedProvider(inner, cache_dir=tmp_path, budget=CallBudget(1))
    assert await llm.generate("hello", temperature=0) == "echo: hello"
    llm.meter = Meter()
    assert await llm.generate("hello", temperature=0) == "echo: hello"   # served from the cache
    assert inner.calls == 1
    assert (llm.meter.calls, llm.meter.new_calls) == (1, 0)
    assert llm.total.calls == 2 and llm.total.prompt_tokens > 0
    with pytest.raises(BudgetExhausted):
        await llm.generate("a different prompt")


def test_floor_rules_on_the_committed_dataset():
    truth = json.loads((DATA / "ground_truth.json").read_text())
    for c in truth["companies"]:
        flags = set(floor_rules.evaluate(DATA / c["slug"])["flags"])
        assert set(c["planted_issues"]) <= flags, c["slug"]
    # the control company has two decoys the simple rules cannot tell apart
    assert floor_rules.evaluate(DATA / "vardhan")["flags"] == ["cash_loan_269ss", "rpt_threshold_no_approval"]


def test_generator_reproduces_the_committed_text_files(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["generate_dataset.py", str(tmp_path)])
    generate_dataset.main()
    for rel in ["ground_truth.json", "qa.json"] + [f"{c['slug']}/{f}" for c in generate_dataset.COMPANIES
                                                  for f in ("annual_report.md", "general_ledger.csv")]:
        assert (tmp_path / rel).read_bytes() == (DATA / rel).read_bytes(), rel


def test_questions_cover_every_company_and_category():
    qs = json.loads((DATA / "qa.json").read_text())
    assert len(qs) == 30 and len({q["id"] for q in qs}) == 30
    assert {q["company"] for q in qs} == {c["slug"] for c in generate_dataset.COMPANIES}
    assert {q["category"] for q in qs} == {"lookup", "calculation", "related_party", "multi_hop"}
