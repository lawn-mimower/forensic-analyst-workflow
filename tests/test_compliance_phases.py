"""Unit tests for the individual compliance-checker phases (no LightRAG, no network)."""

from __future__ import annotations

import json

import pytest

from conftest import load_phase


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class _FakeRag:
    def __init__(self, answer):
        self.answer = answer
        self.queries = []

    async def aquery(self, query, param=None):
        self.queries.append((query, param))
        return self.answer


# ---------------------------------------------------------------------------
# Phase 0
# ---------------------------------------------------------------------------
async def test_profile_document_maps_names_to_keys(fake_llms, small_laws, monkeypatch, tmp_path):
    phase0 = load_phase("profile_document")
    rag = _FakeRag("Acme Widgets Private Limited is an unlisted private company.")

    async def fake_get_rag(storage=None):
        return rag

    monkeypatch.setattr(phase0, "get_rag_instance", fake_get_rag)
    _, reasoning = fake_llms

    async def partial_names(prompt, *, schema, system_prompt=None):
        # exact name, loose name and an unknown name
        return ["Companies Act, 2013", "income tax act", "Unknown Act"]

    monkeypatch.setattr(reasoning, "generate_json", partial_names)

    result = await phase0.profile_document(storage="unused", output_dir=str(tmp_path))

    assert rag.queries[0][1].mode == "global"
    assert result["applicable_category_keys"] == ["companies_act_2013", "income_tax_act_1961"]
    assert result["total_available"] == 2
    saved = json.loads((tmp_path / "document_profile.json").read_text())
    assert saved["document_summary"].startswith("Acme Widgets")


async def test_profile_document_fails_clearly_without_summary(fake_llms, small_laws, monkeypatch, tmp_path):
    phase0 = load_phase("profile_document")

    async def fake_get_rag(storage=None):
        return _FakeRag(None)  # what LightRAG returns when the query LLM call fails

    monkeypatch.setattr(phase0, "get_rag_instance", fake_get_rag)
    with pytest.raises(RuntimeError, match="no summary"):
        await phase0.profile_document(storage="unused", output_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------
async def test_atomise_laws(fake_llms, small_laws, tmp_path):
    phase1 = load_phase("atomise_laws")
    _write(tmp_path / "document_profile.json", {
        "document_summary": "Acme Widgets Private Limited P&L",
        "applicable_category_keys": ["companies_act_2013", "not_a_category", "income_tax_act_1961"],
    })

    questions = await phase1.atomise_laws(output_dir=str(tmp_path))

    assert [q["question_id"] for q in questions] == ["Q0001", "Q0002", "Q0003"]
    assert questions[0]["source_category_name"] == "Companies Act, 2013"
    assert questions[0]["source_section"] == "section_128"
    assert questions[2]["source_section"] == "section_269SS"
    assert questions[2]["suggested_mode"] == "local"
    assert json.loads((tmp_path / "atomic_questions.json").read_text()) == questions


async def test_atomise_laws_skips_bad_json(fake_llms, small_laws, monkeypatch, tmp_path):
    phase1 = load_phase("atomise_laws")
    _, reasoning = fake_llms

    async def not_json(prompt, **kwargs):
        return "I cannot answer that"

    monkeypatch.setattr(reasoning, "generate_with_thinking", not_json)
    _write(tmp_path / "document_profile.json", {
        "document_summary": "x", "applicable_category_keys": ["companies_act_2013"],
    })
    assert await phase1.atomise_laws(output_dir=str(tmp_path)) == []


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------
async def test_batch_retrieve(monkeypatch, tmp_path):
    phase2 = load_phase("batch_retrieve")

    class Rag:
        async def aquery(self, query, param=None):
            if "boom" in query:
                raise RuntimeError("storage offline")
            return "" if "empty" in query else f"context for {query} ({param.mode})"

    async def fake_get_rag(storage=None):
        return Rag()

    monkeypatch.setattr(phase2, "get_rag_instance", fake_get_rag)
    _write(tmp_path / "atomic_questions.json", [
        {"question_id": "Q0001", "question_text": "revenue", "suggested_mode": "local"},
        {"question_id": "Q0002", "question_text": "empty"},
        {"question_id": "Q0003", "question_text": "boom"},
    ])

    contexts = await phase2.batch_retrieve(storage="unused", output_dir=str(tmp_path), max_concurrent=2)

    assert contexts["Q0001"] == {
        "question_id": "Q0001", "context_text": "context for revenue (local)",
        "is_empty": False, "mode_used": "local",
    }
    assert contexts["Q0002"]["is_empty"] and contexts["Q0002"]["mode_used"] == "hybrid"
    assert contexts["Q0003"]["is_empty"] and contexts["Q0003"]["error"] == "storage offline"


# ---------------------------------------------------------------------------
# Phase 3
# ---------------------------------------------------------------------------
async def test_adjudicate(fake_llms, monkeypatch, tmp_path):
    phase3 = load_phase("adjudicate")
    _, reasoning = fake_llms
    original = reasoning.generate_json

    async def flaky(prompt, *, schema, system_prompt=None):
        if "Q-ERROR" in prompt:
            raise RuntimeError("quota exceeded")
        return await original(prompt, schema=schema)

    monkeypatch.setattr(reasoning, "generate_json", flaky)
    _write(tmp_path / "atomic_questions.json", [
        {"question_id": "Q0001", "question_text": "Did the company accept any loan in cash?"},
        {"question_id": "Q0002", "question_text": "Is the accrual basis followed?"},
        {"question_id": "Q0003", "question_text": "No context here"},
        {"question_id": "Q0004", "question_text": "Q-ERROR"},
    ])
    _write(tmp_path / "retrieved_contexts.json", {
        "Q0001": {"is_empty": False, "context_text": "accepted a cash loan"},
        "Q0002": {"is_empty": False, "context_text": "accrual basis"},
        "Q0004": {"is_empty": False, "context_text": "something"},
    })

    verdicts = await phase3.adjudicate(output_dir=str(tmp_path), max_concurrent=2)
    by_id = {v["question_id"]: v for v in verdicts}

    assert by_id["Q0001"]["verdict"] == "VIOLATION"
    assert by_id["Q0002"]["verdict"] == "COMPLIANT"
    assert by_id["Q0003"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert by_id["Q0004"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert "quota exceeded" in by_id["Q0004"]["reasoning"]
    # empty context never reaches the model
    assert len(reasoning.json_calls) == 2


# ---------------------------------------------------------------------------
# Phase 4
# ---------------------------------------------------------------------------
async def test_generate_report_scoring(small_laws, tmp_path):
    phase4 = load_phase("generate_report")
    _write(tmp_path / "document_profile.json", {"document_summary": "Acme Widgets FY 2024-25"})
    _write(tmp_path / "atomic_questions.json", [
        {"question_id": "Q1", "question_text": "a | b", "source_category": "companies_act_2013",
         "source_section": "section_128", "source_section_name": "Section 128"},
        {"question_id": "Q2", "question_text": "c", "source_category": "companies_act_2013",
         "source_section": "section_128", "source_section_name": "Section 128"},
        {"question_id": "Q3", "question_text": "d", "source_category": "companies_act_2013",
         "source_section": "section_128", "source_section_name": "Section 128"},
        {"question_id": "Q4", "question_text": "e", "source_category": "income_tax_act_1961",
         "source_section": "section_269SS", "source_section_name": "Section 269SS"},
    ])
    _write(tmp_path / "verdicts.json", [
        {"question_id": "Q1", "verdict": "COMPLIANT", "reasoning": "ok", "excerpt": "x"},
        {"question_id": "Q2", "verdict": "COMPLIANT", "reasoning": "ok", "excerpt": "y"},
        {"question_id": "Q3", "verdict": "VIOLATION", "reasoning": "bad\nline", "excerpt": "z"},
        # Q4 has no verdict -> counted as INSUFFICIENT_EVIDENCE
    ])

    report = await phase4.generate_report(output_dir=str(tmp_path))

    assert report["overall"]["totals"] == {"COMPLIANT": 2, "VIOLATION": 1, "INSUFFICIENT_EVIDENCE": 1}
    assert report["overall"]["score_pct"] == "66.7%"
    ca = report["categories"]["companies_act_2013"]
    assert ca["category_name"] == "Companies Act, 2013"
    assert ca["score"] == pytest.approx(2 / 3)
    assert ca["sections"]["section_128"]["total_questions"] == 3
    it = report["categories"]["income_tax_act_1961"]
    assert it["score"] is None

    md = (tmp_path / "compliance_report.md").read_text()
    assert "**Overall Score**: 66.7%" in md
    assert "**Category Score**: N/A" in md
    assert "a \\| b" in md  # pipes escaped inside table cells
    assert "bad line" in md


async def test_generate_report_no_judgeable_items(small_laws, tmp_path):
    phase4 = load_phase("generate_report")
    _write(tmp_path / "document_profile.json", {"document_summary": ""})
    _write(tmp_path / "atomic_questions.json", [])
    _write(tmp_path / "verdicts.json", [])
    report = await phase4.generate_report(output_dir=str(tmp_path))
    assert report["overall"]["score"] is None
    assert report["overall"]["score_pct"] == "N/A"


@pytest.mark.parametrize("phase,func,kwargs", [
    ("atomise_laws", "atomise_laws", {}),
    ("batch_retrieve", "batch_retrieve", {"storage": "unused"}),
    ("adjudicate", "adjudicate", {}),
    ("generate_report", "generate_report", {}),
])
async def test_phases_require_previous_output(phase, func, kwargs, tmp_path):
    mod = load_phase(phase)
    with pytest.raises(FileNotFoundError):
        await getattr(mod, func)(output_dir=str(tmp_path), **kwargs)
