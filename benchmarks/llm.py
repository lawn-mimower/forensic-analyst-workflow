"""
LLM access for the benchmark runs: a disk cache and call/token/latency meter
around the repo's own providers (skills/shared/llm_registry.py).

Every response is cached under benchmarks/.cache/llm/ (git-ignored), keyed by
model, call kind, prompts and parameters, so an interrupted run can resume
without repeating calls. A cached response still counts as a call in the
meter (with the latency recorded when it was first made), so per-question
cost figures do not depend on whether a run was resumed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
CACHE_DIR = BENCH_DIR / ".cache" / "llm"

_ENC = None


def count_tokens(text: str | None) -> int:
    """Token estimate with tiktoken's o200k_base (the encoding LightRAG chunks with)."""
    global _ENC
    if not text:
        return 0
    if _ENC is None:
        import tiktoken

        _ENC = tiktoken.get_encoding("o200k_base")
    return len(_ENC.encode(text, disallowed_special=()))


class BudgetExhausted(RuntimeError):
    """Raised when a run would exceed its cap on new (uncached) LLM calls."""


class QuotaExhausted(RuntimeError):
    """Raised when the provider reports a daily quota limit (HTTP 429), or keeps
    failing with rate-limit or overload errors after several retries."""


@dataclass
class Meter:
    calls: int = 0            # calls made by the system (cached or not)
    new_calls: int = 0        # calls that actually reached the provider
    prompt_tokens: int = 0    # o200k estimate of system + history + prompt
    completion_tokens: int = 0
    llm_seconds: float = 0.0  # provider latency as first measured
    replayed_seconds: float = 0.0  # original latency of calls served from the cache

    def as_dict(self) -> dict:
        return {"llm_calls": self.calls, "new_llm_calls": self.new_calls,
                "prompt_tokens_est": self.prompt_tokens,
                "completion_tokens_est": self.completion_tokens,
                "llm_seconds": round(self.llm_seconds, 1)}


@dataclass
class CallBudget:
    max_new_calls: int | None = None
    used: int = 0

    def take(self) -> None:
        if self.max_new_calls is not None and self.used >= self.max_new_calls:
            raise BudgetExhausted(f"cap of {self.max_new_calls} new LLM calls reached")
        self.used += 1


def _is_quota_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text or "rate limit" in text


class CachedProvider:
    """Drop-in stand-in for an LLMProvider that caches and meters every call."""

    def __init__(self, inner, *, budget: CallBudget | None = None, cache_dir: Path = CACHE_DIR,
                 label: str | None = None, min_interval_s: float = 0.0):
        self._inner = inner
        self.min_interval_s = min_interval_s  # pacing for new calls, outside the timed region
        self._last_new_call = 0.0
        self.model = inner.model
        self.label = label or inner.model
        self.budget = budget or CallBudget()
        self.cache_dir = Path(cache_dir) / self.model.replace("/", "_")
        self.meter = Meter()   # swap per item to attribute costs
        self.total = Meter()   # whole-process totals

    # -- cache ------------------------------------------------------------
    def _key(self, payload: dict) -> str:
        blob = json.dumps({"model": self.model, **payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _record(self, prompt_text: str, response_text: str, seconds: float, new: bool) -> None:
        pt, ct = count_tokens(prompt_text), count_tokens(response_text)
        for m in (self.meter, self.total):
            m.calls += 1
            m.new_calls += int(new)
            m.prompt_tokens += pt
            m.completion_tokens += ct
            m.llm_seconds += seconds
            if not new:
                m.replayed_seconds += seconds

    async def _cached(self, kind: str, payload: dict, prompt_text: str, call):
        key = self._key({"kind": kind, **payload})
        path = self._path(key)
        if path.exists():
            entry = json.loads(path.read_text(encoding="utf-8"))
            self._record(prompt_text, entry["response_text"], entry["seconds"], new=False)
            return entry["response"]
        self.budget.take()
        if self.min_interval_s:
            import asyncio

            wait = self._last_new_call + self.min_interval_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_new_call = time.monotonic()
        import asyncio

        for attempt in range(4):
            t0 = time.perf_counter()
            try:
                response = await call()
                break
            except Exception as exc:
                text = str(exc)
                if _is_quota_error(exc) and ("PerDay" in text or attempt == 3):
                    raise QuotaExhausted(text[:300]) from exc
                transient = _is_quota_error(exc) or any(
                    k in text for k in ("503", "UNAVAILABLE", "overloaded", "500 INTERNAL"))
                if transient and attempt == 3:
                    raise QuotaExhausted(f"provider still unavailable after retries: {text[:200]}") from exc
                if not transient:
                    raise
                await asyncio.sleep(30 * (attempt + 1))  # per-minute limit or overload: back off
        seconds = time.perf_counter() - t0
        response_text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kind": kind, "model": self.model, "seconds": round(seconds, 3),
                                   "response": response, "response_text": response_text},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        self._record(prompt_text, response_text, seconds, new=True)
        return response

    # -- LLMProvider interface ----------------------------------------------
    async def generate(self, prompt, *, system_prompt=None, messages=None, temperature=None,
                       max_tokens=None, **_ignored) -> str:
        payload = {"prompt": prompt, "system": system_prompt, "messages": messages or [],
                   "temperature": temperature, "max_tokens": max_tokens}
        history = "\n".join(m.get("content", "") for m in messages or [])
        text = "\n".join(x for x in (system_prompt, history, prompt) if x)
        return await self._cached("generate", payload, text, lambda: self._inner.generate(
            prompt, system_prompt=system_prompt, messages=messages,
            temperature=temperature, max_tokens=max_tokens))

    async def generate_json(self, prompt, *, schema, system_prompt=None) -> dict:
        payload = {"prompt": prompt, "system": system_prompt, "schema": schema}
        text = "\n".join(x for x in (system_prompt, prompt) if x)
        return await self._cached("generate_json", payload, text, lambda: self._inner.generate_json(
            prompt, schema=schema, system_prompt=system_prompt))

    async def generate_with_thinking(self, prompt, *, debug_label="", debug_dir=None) -> str:
        return await self._cached("generate_with_thinking", {"prompt": prompt}, prompt,
                                  lambda: self._inner.generate_with_thinking(prompt))


def parse_json_block(text: str):
    """Parse the first JSON object or array in a model response (code fences allowed)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    closer = "}" if t[start] == "{" else "]"
    end = t.rfind(closer)
    if end <= start:
        return None
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None


def setup_registry(config_path: str | Path, *, max_new_calls: int | None = None,
                   min_interval_s: float = 0.0, base_url: str | None = None,
                   model: str | None = None) -> dict:
    """Point the repo's registry at a benchmark config and wrap its providers.

    Returns {"kg": CachedProvider, "reasoning": CachedProvider}. The kg_llm
    wrapper is installed where LightRAG's llm_model_func looks for it, and
    the reasoning_llm wrapper replaces the registry's cached provider, so the
    compliance phases use it too.
    """
    os.environ["MODEL_CONFIG_PATH"] = str(Path(config_path).resolve())
    from skills.shared import lightrag_init, llm_registry

    llm_registry.reload_config()
    cfg = llm_registry._load_config()
    if base_url:  # point every openai_compat provider at another server (e.g. a second Ollama)
        for name, prov in cfg.get("providers", {}).items():
            if name == "openai_compat":
                prov["base_url"] = base_url
    if model:  # run every role on another model of the same provider(s)
        for prov in cfg.get("providers", {}).values():
            prov["default_model"] = model
        for role in cfg.get("roles", {}).values():
            role.pop("model", None)
    budget = CallBudget(max_new_calls)
    kg_inner = llm_registry.get_role("kg_llm")
    reasoning_inner = llm_registry.get_role("reasoning_llm")
    kg = CachedProvider(kg_inner, budget=budget, min_interval_s=min_interval_s)
    reasoning = kg if reasoning_inner is kg_inner else CachedProvider(
        reasoning_inner, budget=budget, min_interval_s=min_interval_s)
    for role, wrapped in (("kg_llm", kg), ("reasoning_llm", reasoning), ("agent_llm", reasoning)):
        llm_registry._providers[cfg["roles"][role]["provider"]] = wrapped
    lightrag_init._kg_provider = kg
    provider = cfg["roles"]["reasoning_llm"]["provider"]
    return {"kg": kg, "reasoning": reasoning, "budget": budget, "provider": provider,
            "model": reasoning.model, "base_url": cfg["providers"].get(provider, {}).get("base_url")}
