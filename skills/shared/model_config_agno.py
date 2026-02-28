"""
Helper to create an Agno Model instance from environment variables.

Usage:
    from skills.shared.model_config_agno import get_agent_model
    model = get_agent_model()  # reads AGENT_MODEL_PROVIDER + AGENT_MODEL_ID
"""

from __future__ import annotations

import os


def get_agent_model(
    provider: str | None = None,
    model_id: str | None = None,
):
    """Return an Agno Model instance based on env vars or explicit args.

    Env vars (fallbacks):
        AGENT_MODEL_PROVIDER: google | mistral | anthropic | groq | openai
        AGENT_MODEL_ID: model identifier (e.g. gemini-3-flash-preview)
    """
    provider = provider or os.environ.get("AGENT_MODEL_PROVIDER", "google")
    model_id = model_id or os.environ.get("AGENT_MODEL_ID", "gemini-3-flash-preview")

    provider = provider.lower()

    if provider in ("google", "gemini"):
        from agno.models.google import Gemini
        return Gemini(id=model_id)

    if provider == "mistral":
        from agno.models.mistral import MistralChat
        return MistralChat(id=model_id)

    if provider == "anthropic":
        from agno.models.anthropic import Claude
        return Claude(id=model_id)

    if provider == "groq":
        from agno.models.groq import Groq
        return Groq(id=model_id)

    if provider == "openai":
        from agno.models.openai import OpenAIChat
        return OpenAIChat(id=model_id)

    raise ValueError(
        f"Unknown agent model provider '{provider}'. "
        "Supported: google, mistral, anthropic, groq, openai"
    )
