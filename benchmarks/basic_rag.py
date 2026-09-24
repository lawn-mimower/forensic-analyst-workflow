"""
Baseline A: a conventional retrieve-then-read pipeline.

The report is cut into fixed-size token windows (256 tokens, 32 overlap, the
o200k_base encoding LightRAG also uses). The top 4 windows for a question are
chosen either by Okapi BM25 (k1 = 1.5, b = 0.75) or by cosine similarity of
all-MiniLM-L6-v2 embeddings, the same local embedding model the repo's
knowledge graph uses. One LLM call then answers from those windows.
"""

from __future__ import annotations

import math
import re
from collections import Counter

CHUNK_TOKENS = 256
CHUNK_OVERLAP = 32
TOP_K = 4


def chunk_text(text: str, size: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    ids = enc.encode(text, disallowed_special=())
    step = size - overlap
    chunks = []
    for start in range(0, max(1, len(ids)), step):
        piece = ids[start:start + size]
        if not piece:
            break
        chunks.append(enc.decode(piece))
        if start + size >= len(ids):
            break
    return chunks


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [_tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avgdl = sum(len(d) for d in self.docs) / max(1, len(self.docs))
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, query: str) -> list[float]:
        q = _tokens(query)
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            out.append(s)
        return out


class Retriever:
    """Chunks one document and returns the top-k chunks for a question."""

    def __init__(self, text: str, method: str = "bm25", top_k: int = TOP_K):
        self.chunks = chunk_text(text)
        self.method = method
        self.top_k = top_k
        if method == "bm25":
            self._bm25 = BM25(self.chunks)
        elif method == "dense":
            self._emb = _embed(self.chunks)
        else:
            raise ValueError(method)

    def retrieve(self, question: str) -> list[str]:
        if self.method == "bm25":
            scores = self._bm25.scores(question)
        else:
            q = _embed([question])[0]
            scores = [float(sum(a * b for a, b in zip(q, c))) for c in self._emb]
        order = sorted(range(len(self.chunks)), key=lambda i: (-scores[i], i))[: self.top_k]
        return [self.chunks[i] for i in sorted(order)]  # keep document order


_MODEL = None


def _embed(texts: list[str]):
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _MODEL.encode(texts, normalize_embeddings=True).tolist()
