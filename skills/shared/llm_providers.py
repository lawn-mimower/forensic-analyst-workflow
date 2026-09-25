"""
Unified LLM provider wrappers with lazy SDK imports and per-provider rate limiting.

Each provider implements a common async interface:
    generate(prompt, *, system_prompt, messages, temperature, max_tokens) -> str

Gemini additionally supports:
    generate_json(prompt, *, schema, system_prompt) -> dict

Gemini and Anthropic additionally support:
    generate_with_thinking(prompt, *, debug_label, debug_dir) -> str

OpenAICompatProvider talks to any OpenAI-compatible server (for example a
local Ollama at http://localhost:11434/v1) and supports generate_json via
the server's json_schema response format.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from skills.shared.rate_limiter import get_rate_limiter

if TYPE_CHECKING:
    from skills.shared.rate_limiter import RateLimiter


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, model: str, rate_limiter: RateLimiter):
        self.model = model
        self._rl = rate_limiter

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        messages: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict,
        system_prompt: str | None = None,
    ) -> dict:
        """Generate a response constrained to a JSON schema.

        Returns a parsed dict — callers never touch json.loads().
        Override in providers that support native JSON mode.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support generate_json()"
        )


# ---------------------------------------------------------------------------
# Mistral
# ---------------------------------------------------------------------------
class MistralProvider(LLMProvider):
    """Wraps the Mistral SDK (mistralai)."""

    _client = None

    def _get_client(self):
        if self._client is None:
            from mistralai import Mistral

            self.__class__._client = Mistral(
                api_key=os.environ["MISTRAL_API_KEY"]
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        messages: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        from mistralai import UserMessage, SystemMessage, AssistantMessage

        client = self._get_client()

        msg_list: list = []
        if system_prompt:
            msg_list.append(SystemMessage(content=system_prompt))
        if messages:
            for msg in messages:
                if msg["role"] == "assistant":
                    msg_list.append(AssistantMessage(content=msg["content"]))
                else:
                    msg_list.append(UserMessage(content=msg["content"]))
        msg_list.append(UserMessage(content=prompt))

        kwargs: dict = {"model": self.model, "messages": msg_list}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        await self._rl.wait()
        response = await client.chat.complete_async(**kwargs)
        return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Gemini (new google-genai SDK)
# ---------------------------------------------------------------------------
class GeminiProvider(LLMProvider):
    """Wraps the google-genai SDK."""

    _client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self.__class__._client = genai.Client(
                api_key=os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        messages: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        from google.genai import types

        client = self._get_client()

        contents: list = []
        if messages:
            for msg in messages:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part(text=msg["content"])],
                ))
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        ))

        config_kwargs: dict = {}
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if max_tokens is not None:
            config_kwargs["max_output_tokens"] = max_tokens

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        await self._rl.wait()
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return response.text

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict,
        system_prompt: str | None = None,
    ) -> dict:
        """Generate a response constrained to a JSON schema.

        Uses Gemini's native response_mime_type + response_schema to guarantee
        valid JSON output — no post-hoc parsing or cleanup needed.
        """
        from google.genai import types

        client = self._get_client()

        config_kwargs: dict = {
            "response_mime_type": "application/json",
            "response_schema": schema,
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        config = types.GenerateContentConfig(**config_kwargs)

        await self._rl.wait()
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return json.loads(response.text)

    async def generate_with_thinking(
        self,
        prompt: str,
        *,
        debug_label: str = "",
        debug_dir: Path | None = None,
    ) -> str:
        """Call Gemini with extended thinking enabled (budget=-1 = dynamic).

        Separates thought parts from answer parts. If debug_label and debug_dir
        are given, saves the thoughts to debug_dir/<debug_label>.txt.
        Returns only the answer text.
        """
        from google.genai import types

        client = self._get_client()

        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=-1),
        )

        await self._rl.wait()
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        thoughts: list[str] = []
        answer_parts: list[str] = []
        for part in response.candidates[0].content.parts:
            if getattr(part, "thought", False):
                thoughts.append(part.text)
            else:
                answer_parts.append(part.text)

        if thoughts and debug_dir and debug_label:
            debug_path = Path(debug_dir)
            debug_path.mkdir(parents=True, exist_ok=True)
            (debug_path / f"{debug_label}.txt").write_text(
                "\n\n".join(thoughts), encoding="utf-8"
            )

        return "".join(answer_parts)


# ---------------------------------------------------------------------------
# Anthropic (optional)
# ---------------------------------------------------------------------------
class AnthropicProvider(LLMProvider):
    """Wraps the Anthropic SDK."""

    _client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self.__class__._client = anthropic.AsyncAnthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"]
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        messages: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        client = self._get_client()

        msg_list: list[dict] = []
        if messages:
            for msg in messages:
                msg_list.append({"role": msg["role"], "content": msg["content"]})
        msg_list.append({"role": "user", "content": prompt})

        kwargs: dict = {
            "model": self.model,
            "messages": msg_list,
            "max_tokens": max_tokens or 4096,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if temperature is not None:
            kwargs["temperature"] = temperature

        await self._rl.wait()
        response = await client.messages.create(**kwargs)
        return response.content[0].text

    async def generate_with_thinking(
        self,
        prompt: str,
        *,
        debug_label: str = "",
        debug_dir: Path | None = None,
    ) -> str:
        """Call Anthropic with extended thinking enabled."""
        client = self._get_client()

        await self._rl.wait()
        response = await client.messages.create(
            model=self.model,
            max_tokens=16000,
            thinking={
                "type": "enabled",
                "budget_tokens": 10000,
            },
            messages=[{"role": "user", "content": prompt}],
        )

        thoughts: list[str] = []
        answer_parts: list[str] = []
        for block in response.content:
            if block.type == "thinking":
                thoughts.append(block.thinking)
            elif block.type == "text":
                answer_parts.append(block.text)

        if thoughts and debug_dir and debug_label:
            debug_path = Path(debug_dir)
            debug_path.mkdir(parents=True, exist_ok=True)
            (debug_path / f"{debug_label}.txt").write_text(
                "\n\n".join(thoughts), encoding="utf-8"
            )

        return "".join(answer_parts)


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp server, LM Studio, ...)
# ---------------------------------------------------------------------------
class OpenAICompatProvider(LLMProvider):
    """Wraps any server that speaks the OpenAI chat-completions API.

    ``base_url`` points at the server (for Ollama: http://localhost:11434/v1).
    Local servers usually ignore the API key, so ``api_key_env`` is optional.
    ``reasoning_effort`` ("low", "medium" or "high") is passed on every call for
    servers and models that support it (Ollama with gpt-oss, for example); it is
    left out when not set. There is no separate thinking mode:
    ``generate_with_thinking`` is a plain ``generate`` call.
    """

    def __init__(
        self,
        model: str,
        rate_limiter: RateLimiter,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
        timeout_s: float = 600.0,
        reasoning_effort: str | None = None,
    ):
        super().__init__(model, rate_limiter)
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.timeout_s = timeout_s
        self.reasoning_effort = reasoning_effort
        self._client = None

    def _common_kwargs(self) -> dict:
        kwargs: dict = {"model": self.model}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            key = os.environ.get(self.api_key_env) if self.api_key_env else None
            self._client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=key or "not-needed",
                timeout=self.timeout_s,
            )
        return self._client

    @staticmethod
    def _messages(prompt, system_prompt, messages) -> list[dict]:
        msg_list: list[dict] = []
        if system_prompt:
            msg_list.append({"role": "system", "content": system_prompt})
        for msg in messages or []:
            role = "assistant" if msg["role"] == "assistant" else "user"
            msg_list.append({"role": role, "content": msg["content"]})
        msg_list.append({"role": "user", "content": prompt})
        return msg_list

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        messages: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        kwargs = self._common_kwargs()
        kwargs["messages"] = self._messages(prompt, system_prompt, messages)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        await self._rl.wait()
        response = await self._get_client().chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: dict,
        system_prompt: str | None = None,
    ) -> dict:
        """Structured output via ``response_format`` (json_schema)."""
        await self._rl.wait()
        response = await self._get_client().chat.completions.create(
            **self._common_kwargs(),
            messages=self._messages(prompt, system_prompt, None),
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema},
            },
        )
        return json.loads(response.choices[0].message.content)

    async def generate_with_thinking(
        self,
        prompt: str,
        *,
        debug_label: str = "",
        debug_dir: Path | None = None,
    ) -> str:
        return await self.generate(prompt)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
PROVIDER_CLASSES: dict[str, type[LLMProvider]] = {
    "mistral": MistralProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "openai_compat": OpenAICompatProvider,
}


def create_provider(
    provider_name: str, model: str, rpm: int = 30, **options
) -> LLMProvider:
    """Instantiate a provider with its rate limiter.

    ``options`` are passed to providers that take extra settings
    (``base_url``, ``api_key_env`` and ``timeout_s`` for ``openai_compat``).
    """
    cls = PROVIDER_CLASSES.get(provider_name)
    if cls is None:
        raise ValueError(
            f"Unknown provider '{provider_name}'. "
            f"Available: {list(PROVIDER_CLASSES.keys())}"
        )
    rl = get_rate_limiter(provider=provider_name, rpm=rpm)
    return cls(model=model, rate_limiter=rl, **options)
