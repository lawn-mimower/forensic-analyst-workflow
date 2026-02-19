#!/usr/bin/env python3
"""
Phase 2 — Batch Retrieval.

For each atomic question, runs a context-only LightRAG query using the
suggested retrieval mode. Uses asyncio.gather with a semaphore for parallelism.

Input:  outputs/atomic_questions.json
Output: outputs/retrieved_contexts.json
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from lightrag import QueryParam
from skills.shared.lightrag_init import get_rag_instance, ensure_output_dir


async def _retrieve_single(
    rag,
    question: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Retrieve context for a single question."""
    qid = question["question_id"]
    query_text = question["question_text"]
    mode = question.get("suggested_mode", "hybrid")

    async with semaphore:
        try:
            param = QueryParam(mode=mode, top_k=40, only_need_context=True)
            context = await rag.aquery(query_text, param=param)

            is_empty = not context or not context.strip() or context.strip().lower() == "none"

            return {
                "question_id": qid,
                "context_text": context if not is_empty else "",
                "is_empty": is_empty,
                "mode_used": mode,
            }
        except Exception as e:
            print(f"  [Phase 2] Error retrieving {qid}: {e}")
            return {
                "question_id": qid,
                "context_text": "",
                "is_empty": True,
                "mode_used": mode,
                "error": str(e),
            }


async def batch_retrieve(
    storage: str = "./rag_storage",
    output_dir: str | None = None,
    max_concurrent: int = 4,
) -> dict:
    """Run Phase 2: retrieve contexts for all atomic questions."""
    out_dir = ensure_output_dir(output_dir)

    # Load Phase 1 output
    questions_path = out_dir / "atomic_questions.json"
    if not questions_path.exists():
        raise FileNotFoundError(f"Phase 1 output not found: {questions_path}. Run atomise_laws.py first.")

    with open(questions_path) as f:
        questions = json.load(f)

    print(f"[Phase 2] Retrieving contexts for {len(questions)} questions (max_concurrent={max_concurrent})")

    rag = await get_rag_instance(storage)
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [_retrieve_single(rag, q, semaphore) for q in questions]
    results = await asyncio.gather(*tasks)

    # Build dict keyed by question_id
    contexts = {}
    empty_count = 0
    for r in results:
        contexts[r["question_id"]] = r
        if r["is_empty"]:
            empty_count += 1

    output_path = out_dir / "retrieved_contexts.json"
    with open(output_path, "w") as f:
        json.dump(contexts, f, indent=2, ensure_ascii=False)

    print(f"[Phase 2] Retrieved contexts: {len(contexts)} total, {empty_count} empty")
    print(f"[Phase 2] Output saved to {output_path}")

    return contexts


def main():
    parser = argparse.ArgumentParser(description="Phase 2: Batch Retrieval")
    parser.add_argument("--storage", default="./rag_storage", help="LightRAG storage dir")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--max-concurrent", type=int, default=4, help="Max concurrent queries")
    args = parser.parse_args()

    asyncio.run(batch_retrieve(
        storage=args.storage,
        output_dir=args.output_dir,
        max_concurrent=args.max_concurrent,
    ))


if __name__ == "__main__":
    main()
