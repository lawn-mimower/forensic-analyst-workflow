"""
Dual-mode LightRAG client — HTTP server or direct library access.

Usage:
    from skills.shared.lightrag_client import create_lightrag_client

    client = await create_lightrag_client(storage_path="./rag_storage")
    result = await client.query("What is the company revenue?", mode="hybrid")
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class LightRAGClient(ABC):
    """Abstract interface for LightRAG operations."""

    @abstractmethod
    async def query(
        self, query: str, *, mode: str = "hybrid", top_k: int = 60, only_need_context: bool = False
    ) -> str: ...

    @abstractmethod
    async def insert_text(self, text: str) -> dict: ...

    @abstractmethod
    async def insert_file(self, file_path: str) -> dict: ...

    @abstractmethod
    async def delete(self, doc_id: str) -> dict: ...

    @abstractmethod
    async def health_check(self) -> dict: ...


# ---------------------------------------------------------------------------
# HTTP Client (connects to LightRAG server at :9621)
# ---------------------------------------------------------------------------
class LightRAGHttpClient(LightRAGClient):
    """HTTP client for LightRAG server API."""

    def __init__(self, base_url: str = "http://localhost:9621"):
        self._base_url = base_url.rstrip("/")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)
        return self._client

    async def query(
        self, query: str, *, mode: str = "hybrid", top_k: int = 60, only_need_context: bool = False
    ) -> str:
        client = self._get_client()
        payload = {
            "query": query,
            "mode": mode,
            "top_k": top_k,
            "only_need_context": only_need_context,
        }
        resp = await client.post("/query", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", data.get("result", str(data)))

    async def insert_text(self, text: str) -> dict:
        client = self._get_client()
        resp = await client.post("/documents/text", json={"text": text})
        resp.raise_for_status()
        return resp.json()

    async def insert_file(self, file_path: str) -> dict:
        client = self._get_client()
        with open(file_path, "rb") as f:
            resp = await client.post(
                "/documents/file",
                files={"file": (Path(file_path).name, f)},
            )
        resp.raise_for_status()
        return resp.json()

    async def delete(self, doc_id: str) -> dict:
        client = self._get_client()
        resp = await client.delete(f"/documents/{doc_id}")
        resp.raise_for_status()
        return resp.json()

    async def health_check(self) -> dict:
        client = self._get_client()
        resp = await client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Direct Client (wraps lightrag.LightRAG instance)
# ---------------------------------------------------------------------------
class LightRAGDirectClient(LightRAGClient):
    """Direct library client wrapping a LightRAG instance."""

    def __init__(self, rag_instance: Any):
        self._rag = rag_instance

    async def query(
        self, query: str, *, mode: str = "hybrid", top_k: int = 60, only_need_context: bool = False
    ) -> str:
        from lightrag import QueryParam

        param = QueryParam(mode=mode, top_k=top_k, only_need_context=only_need_context)
        return await self._rag.aquery(query, param=param)

    async def insert_text(self, text: str) -> dict:
        await self._rag.ainsert(text)
        return {"status": "ok", "chars_inserted": len(text)}

    async def insert_file(self, file_path: str) -> dict:
        text = Path(file_path).read_text(encoding="utf-8")
        await self._rag.ainsert(text)
        return {"status": "ok", "file": file_path, "chars_inserted": len(text)}

    async def delete(self, doc_id: str) -> dict:
        if hasattr(self._rag, "adelete_by_doc_id"):
            await self._rag.adelete_by_doc_id(doc_id)
            return {"status": "ok", "doc_id": doc_id}
        return {"status": "error", "message": "delete not supported by this LightRAG version"}

    async def health_check(self) -> dict:
        return {"status": "ok", "mode": "direct", "working_dir": self._rag.working_dir}

    @property
    def rag(self) -> Any:
        """Access the underlying LightRAG instance."""
        return self._rag


# ---------------------------------------------------------------------------
# Factory — auto-detect server or fall back to direct
# ---------------------------------------------------------------------------
async def create_lightrag_client(
    *,
    server_url: str = "http://localhost:9621",
    storage_path: str | Path | None = None,
    try_server: bool = True,
) -> LightRAGClient:
    """Create a LightRAG client, preferring HTTP server if available.

    Args:
        server_url: URL for the LightRAG HTTP server.
        storage_path: Path for direct LightRAG storage (used as fallback).
        try_server: If True, attempt HTTP connection first.

    Returns:
        LightRAGHttpClient if server is reachable, else LightRAGDirectClient.
    """
    if try_server:
        try:
            http_client = LightRAGHttpClient(base_url=server_url)
            await http_client.health_check()
            return http_client
        except Exception:
            pass

    # Fall back to direct library usage
    from skills.shared.lightrag_init import get_rag_instance
    rag = await get_rag_instance(storage_path)
    return LightRAGDirectClient(rag)
