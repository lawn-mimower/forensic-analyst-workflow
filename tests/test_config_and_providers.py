"""Tests for configuration, the LLM registry, provider wrappers and shared helpers."""

from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from skills.shared import lightrag_init, llm_registry
from skills.shared.llm_providers import (
    GeminiProvider,
    MistralProvider,
    create_provider,
)
from skills.shared.rate_limiter import RateLimiter, get_rate_limiter


# ---------------------------------------------------------------------------
# Laws dataset helpers
# ---------------------------------------------------------------------------
def test_category_keys_and_display_names():
    keys = lightrag_init.get_category_keys()
    names = lightrag_init.get_category_display_names()
    meta = lightrag_init.get_laws_data()["metadata"]["categories"]

    assert "metadata" not in keys
    assert len(keys) == len(meta) == 19
    assert set(names) == set(keys)
    assert names["companies_act_2013"] == "Companies Act, 2013"
    assert names["income_tax_act_1961"] == "Income Tax Act, 1961"
    assert names["company_secretaries_act_1980"] == "Company Secretaries Act, 1980"


def test_every_section_has_name_and_statement():
    laws = lightrag_init.get_laws_data()
    for key in lightrag_init.get_category_keys():
        assert laws[key], key
        for section in laws[key].values():
            assert section["name"] and section["statement"]


def test_ensure_output_dir(tmp_path):
    target = tmp_path / "a" / "b"
    assert lightrag_init.ensure_output_dir(target) == target
    assert target.is_dir()


async def test_llm_model_func_uses_kg_role(fake_llms):
    kg, _ = fake_llms
    out = await lightrag_init.llm_model_func(
        "Summarise the document",
        system_prompt="You are helpful",
        history_messages=[{"role": "user", "content": "hi"}],
        keyword_extraction=False,
        hashing_kv=None,
    )
    assert out.startswith("Acme Widgets Private Limited")
    assert kg.calls == ["Summarise the document"]


@pytest.mark.slow
async def test_embedding_func_shape():
    pytest.importorskip("sentence_transformers")
    vectors = await lightrag_init.embedding_func(["revenue", "trade payables"])
    assert vectors.shape == (2, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(llm_registry, "_providers", {})
    monkeypatch.setattr(llm_registry, "_config", None)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")


def test_registry_maps_roles_from_yaml(clean_registry):
    kg = llm_registry.get_role("kg_llm")
    reasoning = llm_registry.get_role("reasoning_llm")

    assert isinstance(kg, MistralProvider) and kg.model == "ministral-14b-2512"
    assert isinstance(reasoning, GeminiProvider) and reasoning.model == "gemini-3-flash-preview"
    # roles that share a provider share one instance
    assert llm_registry.get_role("agent_llm") is reasoning
    assert llm_registry.get_embedding_config() == {"model": "all-MiniLM-L6-v2", "dim": 384}


def test_registry_errors(clean_registry, monkeypatch):
    with pytest.raises(KeyError):
        llm_registry.get_role("no_such_role")
    with pytest.raises(ValueError):
        llm_registry.get_role("embedding")

    monkeypatch.delenv("MISTRAL_API_KEY")
    with pytest.raises(EnvironmentError, match="MISTRAL_API_KEY"):
        llm_registry.get_role("kg_llm")


def test_registry_defaults_without_yaml(clean_registry, monkeypatch, tmp_path):
    monkeypatch.setattr(llm_registry, "_CONFIG_PATH", tmp_path / "missing.yaml")
    assert llm_registry.get_role("kg_llm").model == "ministral-14b-2512"

    llm_registry.reload_config()
    assert llm_registry._providers == {}


def test_create_provider_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider("nope", model="x")


# ---------------------------------------------------------------------------
# Provider wrappers (SDK clients replaced with fakes)
# ---------------------------------------------------------------------------
class _FakeGeminiModels:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self.response


def _gemini_with(response):
    provider = GeminiProvider(model="gemini-test", rate_limiter=RateLimiter(6000))
    models = _FakeGeminiModels(response)
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return provider, models


async def test_gemini_generate():
    provider, models = _gemini_with(SimpleNamespace(text="pong"))
    out = await provider.generate(
        "ping", system_prompt="sys", temperature=0.1, max_tokens=10,
        messages=[{"role": "assistant", "content": "earlier"}],
    )
    assert out == "pong"
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert [c.role for c in call["contents"]] == ["model", "user"]
    assert call["config"].system_instruction == "sys"
    assert call["config"].max_output_tokens == 10


async def test_gemini_generate_json():
    provider, models = _gemini_with(SimpleNamespace(text='["Companies Act, 2013"]'))
    out = await provider.generate_json("pick", schema={"type": "array", "items": {"type": "string"}})
    assert out == ["Companies Act, 2013"]
    assert models.calls[0]["config"].response_mime_type == "application/json"


async def test_gemini_generate_with_thinking(tmp_path):
    parts = [
        SimpleNamespace(thought=True, text="thinking about it"),
        SimpleNamespace(thought=False, text='[{"question_text": "Q?"}]'),
    ]
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])
    provider, _ = _gemini_with(response)

    out = await provider.generate_with_thinking("atomise", debug_label="phase1_x", debug_dir=tmp_path)
    assert out == '[{"question_text": "Q?"}]'
    assert (tmp_path / "phase1_x.txt").read_text() == "thinking about it"


async def test_mistral_generate():
    calls = []

    async def complete_async(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    provider = MistralProvider(model="ministral-test", rate_limiter=RateLimiter(6000))
    provider._client = SimpleNamespace(chat=SimpleNamespace(complete_async=complete_async))

    out = await provider.generate("extract", system_prompt="sys",
                                  messages=[{"role": "assistant", "content": "prev"}])
    assert out == "ok"
    assert calls[0]["model"] == "ministral-test"
    assert [type(m).__name__ for m in calls[0]["messages"]] == [
        "SystemMessage", "AssistantMessage", "UserMessage",
    ]


# ---------------------------------------------------------------------------
# Rate limiter and agent model factory
# ---------------------------------------------------------------------------
async def test_rate_limiter_spacing():
    rl = RateLimiter(requests_per_minute=600)  # 0.1 s between calls
    start = time.monotonic()
    for _ in range(3):
        await rl.wait()
    assert time.monotonic() - start >= 0.19


def test_rate_limiter_registry_per_provider():
    assert get_rate_limiter("unit-a", 10) is get_rate_limiter("unit-a", 99)
    assert get_rate_limiter("unit-a") is not get_rate_limiter("unit-b")


def test_agent_model_factory(monkeypatch):
    pytest.importorskip("agno")
    from skills.shared.model_config_agno import get_agent_model

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "google")
    monkeypatch.setenv("AGENT_MODEL_ID", "gemini-3-flash-preview")
    model = get_agent_model()
    assert type(model).__name__ == "Gemini" and model.id == "gemini-3-flash-preview"

    with pytest.raises(ValueError, match="Unknown agent model provider"):
        get_agent_model(provider="unknown")
