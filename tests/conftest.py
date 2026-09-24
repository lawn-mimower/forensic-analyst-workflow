"""
Shared fixtures for the test suite.

Offline tests replace the Mistral / Gemini providers with deterministic fakes
by seeding the provider cache in skills.shared.llm_registry, so no network
calls are made. The sample documents describe a fictional company,
Acme Widgets Private Limited.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
COMPLIANCE_SCRIPTS = PROJECT_ROOT / "skills" / "compliance-checker" / "scripts"
QUERY_SCRIPT = PROJECT_ROOT / "skills" / "lightrag-query" / "scripts" / "query.py"


def load_script(path: Path, name: str):
    """Import a script from a hyphenated skills directory."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_phase(name: str):
    return load_script(COMPLIANCE_SCRIPTS / f"{name}.py", f"test_phase_{name}")


# ---------------------------------------------------------------------------
# Sample documents
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def sample_md(fixtures_dir) -> Path:
    return fixtures_dir / "acme_widgets_fy2025.md"


@pytest.fixture(scope="session")
def sample_csv(fixtures_dir) -> Path:
    return fixtures_dir / "acme_widgets_trial_balance.csv"


@pytest.fixture(scope="session")
def _builders():
    return load_script(FIXTURES_DIR / "build_fixtures.py", "build_fixtures")


@pytest.fixture(scope="session")
def sample_xlsx(tmp_path_factory, _builders) -> Path:
    return _builders.build_xlsx(tmp_path_factory.mktemp("docs") / "acme_widgets_fy2025.xlsx")


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory, _builders) -> Path:
    pytest.importorskip("reportlab")
    return _builders.build_pdf(tmp_path_factory.mktemp("docs") / "acme_widgets_pnl_fy2025.pdf")


# ---------------------------------------------------------------------------
# Fake LLM providers
# ---------------------------------------------------------------------------
TD = "<|#|>"
EXTRACTION_OUTPUT = "\n".join([
    f"entity{TD}Acme Widgets Private Limited{TD}organization{TD}Acme Widgets Private Limited is an unlisted private company that manufactures plastic widgets in Pune.",
    f"entity{TD}Jane Doe{TD}person{TD}Jane Doe is a director of Acme Widgets Private Limited who received rent of Rs. 6.00 lakhs.",
    f"entity{TD}Sample & Co.{TD}organization{TD}Sample & Co. is the statutory auditor and issued an unmodified audit opinion.",
    f"entity{TD}Revenue From Operations{TD}data{TD}Revenue from operations was Rs. 850.00 lakhs in FY 2024-25.",
    f"relation{TD}Jane Doe{TD}Acme Widgets Private Limited{TD}related party, rent{TD}Acme Widgets Private Limited paid rent of Rs. 6.00 lakhs to its director Jane Doe.",
    f"relation{TD}Sample & Co.{TD}Acme Widgets Private Limited{TD}statutory audit{TD}Sample & Co. audited the financial statements of Acme Widgets Private Limited.",
    f"relation{TD}Acme Widgets Private Limited{TD}Revenue From Operations{TD}financial result{TD}Acme Widgets Private Limited reported revenue from operations of Rs. 850.00 lakhs.",
    "<|COMPLETE|>",
])

FAKE_ANSWER = (
    "Acme Widgets Private Limited is an unlisted private company. "
    "Revenue from operations for FY 2024-25 was Rs. 850.00 lakhs."
)


class FakeKGProvider:
    """Stands in for the Mistral kg_llm role used inside LightRAG."""

    model = "fake-kg"

    def __init__(self):
        self.calls: list[str] = []

    async def generate(self, prompt, *, system_prompt=None, messages=None,
                       temperature=None, max_tokens=None) -> str:
        self.calls.append(prompt)
        full = f"{system_prompt or ''}\n{prompt}"
        if "high_level_keywords" in full:
            return json.dumps({
                "high_level_keywords": ["financial statements", "related party transactions"],
                "low_level_keywords": ["Acme Widgets Private Limited", "revenue", "Jane Doe"],
            })
        if TD in full or "<|COMPLETE|>" in full:
            return EXTRACTION_OUTPUT
        return FAKE_ANSWER


class FakeReasoningProvider:
    """Stands in for the Gemini reasoning_llm role used by the compliance phases."""

    model = "fake-reasoning"

    def __init__(self):
        self.json_calls: list[str] = []
        self.thinking_calls: list[str] = []

    async def generate(self, prompt, **kwargs) -> str:
        return FAKE_ANSWER

    async def generate_json(self, prompt, *, schema, system_prompt=None):
        self.json_calls.append(prompt)
        if schema.get("type") == "array":
            # Phase 0: pick applicable categories by display name
            return ["Companies Act, 2013", "Income Tax Act, 1961"]
        # Phase 3: verdict. Violation for the cash-loan question, compliant otherwise.
        if "loan in cash" in prompt.lower():
            return {"verdict": "VIOLATION", "reasoning": "A cash loan was accepted.",
                    "excerpt": "accepted a cash loan of Rs. 3.00 lakhs"}
        return {"verdict": "COMPLIANT", "reasoning": "Disclosed in the notes.",
                "excerpt": "prepared on the accrual basis"}

    async def generate_with_thinking(self, prompt, *, debug_label="", debug_dir=None):
        self.thinking_calls.append(prompt)
        if "269SS" in prompt:
            return json.dumps([{
                "question_id": "ignored",
                "question_text": "Did the company accept any loan in cash of Rs. 20,000 or more?",
                "suggested_mode": "local",
                "keywords": ["cash loan"],
            }])
        # Wrapped in a code fence to exercise the fence-stripping logic
        return "```json\n" + json.dumps([
            {"question_text": "Are the books of account kept on accrual basis?",
             "suggested_mode": "hybrid", "keywords": ["accrual"]},
            {"question_text": "Is the auditor's opinion on the financial statements disclosed?",
             "suggested_mode": "naive", "keywords": ["audit opinion"]},
        ]) + "\n```"


@pytest.fixture
def fake_llms(monkeypatch):
    """Route every registry role to deterministic in-process fakes."""
    from skills.shared import llm_registry, lightrag_init

    kg = FakeKGProvider()
    reasoning = FakeReasoningProvider()
    monkeypatch.setattr(llm_registry, "_providers", {"mistral": kg, "gemini": reasoning})
    monkeypatch.setattr(lightrag_init, "_kg_provider", None)
    return kg, reasoning


@pytest.fixture
def small_laws(monkeypatch):
    """Limit the laws dataset to three sections across two categories."""
    from skills.shared import lightrag_init

    lightrag_init._laws_data = None
    full = lightrag_init.get_laws_data()
    trimmed = {
        "metadata": dict(full["metadata"], categories=["Companies Act, 2013", "Income Tax Act, 1961"]),
        "companies_act_2013": {"section_128": full["companies_act_2013"]["section_128"]},
        "income_tax_act_1961": {"section_269SS": full["income_tax_act_1961"]["section_269SS"]},
    }
    monkeypatch.setattr(lightrag_init, "_laws_data", trimmed)
    return trimmed
