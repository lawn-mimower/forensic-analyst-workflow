"""
LLM Registry — loads model_config.yaml and provides role-based provider access.

Usage:
    from skills.shared.llm_registry import get_role, reload_config
    provider = get_role("kg_llm")
    result = await provider.generate("Hello")

Set MODEL_CONFIG_PATH to use a config file other than <repo>/model_config.yaml
(the benchmark runs use this to switch every role to one model).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skills.shared.llm_providers import LLMProvider

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "model_config.yaml"

# Provider settings passed through to the provider class, besides model and rpm
_PROVIDER_OPTION_KEYS = {
    "openai_compat": ("base_url", "api_key_env", "timeout_s", "reasoning_effort"),
}


def config_path() -> Path:
    """The active config file: $MODEL_CONFIG_PATH if set, else model_config.yaml."""
    override = os.environ.get("MODEL_CONFIG_PATH")
    return Path(override) if override else _CONFIG_PATH

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_config: dict | None = None
_providers: dict[str, "LLMProvider"] = {}

# Hardcoded defaults (used when model_config.yaml is missing)
_DEFAULT_CONFIG = {
    "providers": {
        "mistral": {
            "api_key_env": "MISTRAL_API_KEY",
            "default_model": "ministral-14b-2512",
            "rate_limit_rpm": 30,
        },
        "gemini": {
            "api_key_env": "GEMINI_API_KEY",
            "default_model": "gemini-3-flash-preview",
            "rate_limit_rpm": 60,
        },
    },
    "roles": {
        "kg_llm": {"provider": "mistral"},
        "reasoning_llm": {"provider": "gemini"},
        "agent_llm": {"provider": "gemini"},
        "embedding": {"provider": "local", "model": "all-MiniLM-L6-v2", "dim": 384},
    },
}


def _load_config() -> dict:
    """Load YAML config or fall back to hardcoded defaults."""
    global _config
    if _config is not None:
        return _config

    path = config_path()
    if os.environ.get("MODEL_CONFIG_PATH") and not path.exists():
        raise FileNotFoundError(f"MODEL_CONFIG_PATH points to a missing file: {path}")
    if path.exists():
        import yaml

        with open(path, "r") as f:
            _config = yaml.safe_load(f)
    else:
        _config = _DEFAULT_CONFIG

    return _config


def reload_config() -> None:
    """Reload config from disk and clear cached providers (hot-swap)."""
    global _config, _providers
    _config = None
    _providers.clear()
    _load_config()


def get_role(role_name: str) -> "LLMProvider":
    """Return the LLMProvider instance for the given role.

    Creates providers lazily on first access. Subsequent calls return
    the same instance (per role→provider mapping).
    """
    from skills.shared.llm_providers import create_provider

    config = _load_config()
    roles = config.get("roles", {})
    providers_cfg = config.get("providers", {})

    role_cfg = roles.get(role_name)
    if role_cfg is None:
        raise KeyError(
            f"Unknown role '{role_name}'. Available: {list(roles.keys())}"
        )

    provider_name = role_cfg["provider"]

    # Local embeddings don't need a provider wrapper
    if provider_name == "local":
        raise ValueError(
            f"Role '{role_name}' uses local provider (not an LLM). "
            "Use the embedding function directly."
        )

    # Cache key: provider_name (one instance per provider)
    if provider_name in _providers:
        return _providers[provider_name]

    prov_cfg = providers_cfg.get(provider_name, {})
    model = role_cfg.get("model") or prov_cfg.get("default_model", "")
    rpm = prov_cfg.get("rate_limit_rpm", 30)

    # Ensure API key env var is set
    api_key_env = prov_cfg.get("api_key_env")
    if api_key_env and not os.environ.get(api_key_env):
        raise EnvironmentError(
            f"Provider '{provider_name}' requires env var '{api_key_env}' to be set."
        )

    options = {
        key: prov_cfg[key]
        for key in _PROVIDER_OPTION_KEYS.get(provider_name, ())
        if prov_cfg.get(key) is not None
    }
    provider = create_provider(provider_name, model=model, rpm=rpm, **options)
    _providers[provider_name] = provider
    return provider


def get_embedding_config() -> dict:
    """Return the embedding role config (model name, dim)."""
    config = _load_config()
    role_cfg = config.get("roles", {}).get("embedding", {})
    return {
        "model": role_cfg.get("model", "all-MiniLM-L6-v2"),
        "dim": role_cfg.get("dim", 384),
    }
