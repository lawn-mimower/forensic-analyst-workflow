#!/usr/bin/env python3
"""
Phase 0 — Document Profiling & Applicability Filter.

Queries the knowledge graph for a comprehensive document summary, then uses
Gemini to select which compliance law categories are applicable.

Output: outputs/document_profile.json
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
from skills.shared.llm_registry import get_role
from skills.shared.lightrag_init import (
    get_rag_instance,
    get_category_display_names,
    ensure_output_dir,
)

CATEGORIES_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
}

PROFILE_QUERY = (
    "Provide a comprehensive summary of this document covering: "
    "document type, entity/company name, nature of business, "
    "financial period covered, key financial highlights, "
    "audit status, related party transactions, "
    "whether the entity is listed or unlisted, "
    "whether it is a public or private company, "
    "and any regulatory filings mentioned."
)


async def profile_document(
    storage: str = "./rag_storage",
    output_dir: str | None = None,
) -> dict:
    """Run Phase 0: profile the indexed document and filter applicable law categories."""
    out_dir = ensure_output_dir(output_dir)

    # Step 1: Global query for document summary
    rag = await get_rag_instance(storage)
    print("[Phase 0] Querying knowledge graph for document summary...")
    summary = await rag.aquery(PROFILE_QUERY, param=QueryParam(mode="global", top_k=60))
    print(f"[Phase 0] Summary length: {len(summary)} chars")

    # Step 2: Get all category display names
    cat_map = get_category_display_names()
    category_list = list(cat_map.values())

    # Step 3: Ask Gemini which categories apply
    print("[Phase 0] Asking Gemini for applicable categories...")
    provider = get_role("reasoning_llm")

    prompt = f"""You are a financial compliance expert. Given the following document summary,
determine which categories of Indian financial/compliance laws are applicable to this entity.

DOCUMENT SUMMARY:
{summary}

AVAILABLE LAW CATEGORIES:
{json.dumps(category_list, indent=2)}

INSTRUCTIONS:
- Select ONLY categories that are directly applicable to this type of entity and document.
- For example, SEBI regulations only apply to listed companies.
- RBI directions only apply to banking companies.
- Consider the entity type (public/private, listed/unlisted), industry, and document type.
- Return the exact category names that apply."""

    applicable_display_names = await provider.generate_json(
        prompt, schema=CATEGORIES_SCHEMA,
    )

    # Map display names back to category keys
    reverse_map = {v: k for k, v in cat_map.items()}
    applicable_keys = []
    for name in applicable_display_names:
        if name in reverse_map:
            applicable_keys.append(reverse_map[name])
        else:
            # Fuzzy fallback: check if any key contains the name
            for display, key in reverse_map.items():
                if name.lower() in display.lower() or display.lower() in name.lower():
                    applicable_keys.append(key)
                    break

    # Deduplicate while preserving order
    seen = set()
    unique_keys = []
    for k in applicable_keys:
        if k not in seen:
            seen.add(k)
            unique_keys.append(k)
    applicable_keys = unique_keys

    result = {
        "document_summary": summary,
        "applicable_category_keys": applicable_keys,
        "applicable_category_names": [cat_map.get(k, k) for k in applicable_keys],
        "total_applicable": len(applicable_keys),
        "total_available": len(cat_map),
    }

    output_path = out_dir / "document_profile.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[Phase 0] Document profile saved to {output_path}")
    print(f"[Phase 0] Applicable categories ({len(applicable_keys)}/{len(cat_map)}):")
    for k in applicable_keys:
        print(f"  - {cat_map.get(k, k)}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Document Profiling")
    parser.add_argument("--storage", default="./rag_storage", help="LightRAG storage dir")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    args = parser.parse_args()

    asyncio.run(profile_document(storage=args.storage, output_dir=args.output_dir))


if __name__ == "__main__":
    main()
