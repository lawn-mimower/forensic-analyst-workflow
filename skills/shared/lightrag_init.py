"""
Shared LightRAG factory, RateLimiter, Gemini helper, and embedding/LLM functions.
Every compliance-checker and lightrag-query script imports from here.
Uses lazy singletons so models load once even across multiple phases.
"""

import os
import json
import time as _time
import asyncio
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Resolve PROJECT_ROOT from this file's location:
#   skills/shared/lightrag_init.py  →  ../../  →  Forensic_workflow/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LAWS_JSON_PATH = PROJECT_ROOT / "indian_financial_fraud_compliance_laws.json"
DEFAULT_STORAGE = PROJECT_ROOT / "rag_storage"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "skills" / "compliance-checker" / "outputs"

# Load .env from project root
load_dotenv(PROJECT_ROOT / ".env")

# Agno's Gemini model reads GOOGLE_API_KEY
if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


# ---------------------------------------------------------------------------
# Rate Limiter (token-bucket style)
# ---------------------------------------------------------------------------
class RateLimiter:
    """Enforces a minimum delay between API calls across all concurrent workers."""

    def __init__(self, requests_per_minute: int = 30):
        self._delay = 60.0 / requests_per_minute
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self):
        async with self._lock:
            now = _time.monotonic()
            wait_time = self._delay - (now - self._last_call)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_call = _time.monotonic()


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------
_rate_limiter: RateLimiter | None = None
_embed_model = None
_mistral_client = None
_gemini_model_cache: dict = {}
_laws_data: dict | None = None


def get_rate_limiter(rpm: int = 30) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(requests_per_minute=rpm)
    return _rate_limiter


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _get_mistral_client():
    global _mistral_client
    if _mistral_client is None:
        from mistralai import Mistral
        _mistral_client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    return _mistral_client


# ---------------------------------------------------------------------------
# Embedding function (384d, normalized, no API cost)
# ---------------------------------------------------------------------------
async def embedding_func(texts: list[str]) -> np.ndarray:
    model = _get_embed_model()
    return model.encode(texts, normalize_embeddings=True)


# ---------------------------------------------------------------------------
# LLM function for LightRAG internals (Mistral ministral-14b-2512)
# ---------------------------------------------------------------------------
async def llm_model_func(
    prompt, system_prompt=None, history_messages=None, keyword_extraction=False, **kwargs
) -> str:
    from mistralai import UserMessage, SystemMessage, AssistantMessage

    client = _get_mistral_client()
    rl = get_rate_limiter()

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    if history_messages:
        for msg in history_messages:
            if msg["role"] == "assistant":
                messages.append(AssistantMessage(content=msg["content"]))
            else:
                messages.append(UserMessage(content=msg["content"]))
    messages.append(UserMessage(content=prompt))

    await rl.wait()
    response = await client.chat.complete_async(
        model="ministral-14b-2512",
        messages=messages,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# LightRAG factory → async initialised instance
# ---------------------------------------------------------------------------
async def get_rag_instance(storage_path: str | Path | None = None) -> "LightRAG":
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    working_dir = str(storage_path or DEFAULT_STORAGE)
    os.makedirs(working_dir, exist_ok=True)

    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_model_func,
        llm_model_max_async=4,
        embedding_func=EmbeddingFunc(
            embedding_dim=384,
            max_token_size=8192,
            func=embedding_func,
        ),
        chunk_token_size=1200,
        chunk_overlap_token_size=100,
    )
    await rag.initialize_storages()
    return rag


# ---------------------------------------------------------------------------
# Gemini model helper
# ---------------------------------------------------------------------------
def get_gemini_model(model_id: str = "gemini-2.5-flash") -> "GenerativeModel":
    """Return a configured google.generativeai GenerativeModel (cached)."""
    if model_id not in _gemini_model_cache:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        _gemini_model_cache[model_id] = genai.GenerativeModel(model_id)
    return _gemini_model_cache[model_id]


# ---------------------------------------------------------------------------
# Compliance laws loader
# ---------------------------------------------------------------------------
def get_laws_data() -> dict:
    """Load and cache the compliance laws JSON. Returns the full dict."""
    global _laws_data
    if _laws_data is None:
        with open(LAWS_JSON_PATH, "r") as f:
            _laws_data = json.load(f)
    return _laws_data


def get_category_keys() -> list[str]:
    """Return the top-level category keys (excluding 'metadata')."""
    data = get_laws_data()
    return [k for k in data.keys() if k != "metadata"]


def get_category_display_names() -> dict[str, str]:
    """Map category_key → display name from metadata.categories."""
    data = get_laws_data()
    keys = get_category_keys()
    display_names = data.get("metadata", {}).get("categories", [])
    # Build mapping by position (keys and display_names are in the same order)
    mapping = {}
    for i, key in enumerate(keys):
        if i < len(display_names):
            mapping[key] = display_names[i]
        else:
            mapping[key] = key.replace("_", " ").title()
    return mapping


def ensure_output_dir(output_dir: str | Path | None = None) -> Path:
    """Ensure the output directory exists and return it."""
    d = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d
