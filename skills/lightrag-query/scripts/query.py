#!/usr/bin/env python3
"""
Standalone CLI for querying a LightRAG knowledge graph.

Usage:
    python query.py --query "What is ExampleCo's total revenue?" --mode local
    python query.py --query "Related parties" --context-only --output out.json
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

# Ensure project root is on sys.path for shared imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from lightrag import QueryParam
from skills.shared.lightrag_init import get_rag_instance


async def run_query(
    query: str,
    mode: str = "hybrid",
    storage: str = "./rag_storage",
    top_k: int = 40,
    context_only: bool = False,
) -> dict:
    """Execute a LightRAG query and return structured results."""
    rag = await get_rag_instance(storage)

    param = QueryParam(mode=mode, top_k=top_k, only_need_context=context_only)
    result = await rag.aquery(query, param=param)

    return {
        "query": query,
        "mode": mode,
        "top_k": top_k,
        "context_only": context_only,
        "result": result,
    }


def main():
    parser = argparse.ArgumentParser(description="Query a LightRAG knowledge graph")
    parser.add_argument("--query", required=True, help="Query string")
    parser.add_argument(
        "--mode",
        default="hybrid",
        choices=["local", "global", "hybrid", "mix", "naive"],
        help="Retrieval mode (default: hybrid)",
    )
    parser.add_argument("--storage", default="./rag_storage", help="LightRAG storage dir")
    parser.add_argument("--top-k", type=int, default=40, help="Top-K results (default: 40)")
    parser.add_argument("--context-only", action="store_true", help="Return raw context only")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    args = parser.parse_args()

    result = asyncio.run(
        run_query(
            query=args.query,
            mode=args.mode,
            storage=args.storage,
            top_k=args.top_k,
            context_only=args.context_only,
        )
    )

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
