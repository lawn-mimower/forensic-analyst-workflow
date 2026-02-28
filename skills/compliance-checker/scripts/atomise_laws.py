#!/usr/bin/env python3
"""
Phase 1 — Law Atomisation.

For each applicable law section, uses Gemini (JSON mode) to generate
atomic yes/no compliance questions with suggested retrieval modes.

Input:  outputs/document_profile.json
Output: outputs/atomic_questions.json
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.lightrag_init import (
    get_gemini_model,
    generate_with_thinking,
    get_laws_data,
    ensure_output_dir,
    DEFAULT_OUTPUT_DIR,
)


async def atomise_laws(output_dir: str | None = None) -> list[dict]:
    """Run Phase 1: generate atomic compliance questions for applicable law sections."""
    out_dir = ensure_output_dir(output_dir)

    # Load Phase 0 output
    profile_path = out_dir / "document_profile.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Phase 0 output not found: {profile_path}. Run profile_document.py first.")

    with open(profile_path) as f:
        profile = json.load(f)

    doc_summary = profile["document_summary"]
    applicable_keys = profile["applicable_category_keys"]

    laws = get_laws_data()
    model = get_gemini_model()

    all_questions = []
    question_counter = 0

    for cat_key in applicable_keys:
        if cat_key not in laws:
            print(f"[Phase 1] Warning: category key '{cat_key}' not found in laws JSON, skipping.")
            continue

        category_data = laws[cat_key]
        cat_display = laws.get("metadata", {}).get("categories", [])
        # Find display name for this category
        all_keys = [k for k in laws if k != "metadata"]
        cat_idx = all_keys.index(cat_key) if cat_key in all_keys else -1
        cat_name = cat_display[cat_idx] if 0 <= cat_idx < len(cat_display) else cat_key

        print(f"[Phase 1] Processing category: {cat_name} ({len(category_data)} sections)")

        for section_key, section_data in category_data.items():
            section_name = section_data.get("name", section_key)
            section_statement = section_data.get("statement", "")

            prompt = f"""You are a financial compliance expert. Given a law section and a document summary,
generate specific, atomic yes/no compliance questions that can be answered by searching
the document's knowledge graph.

DOCUMENT SUMMARY:
{doc_summary}

LAW SECTION: {section_name}
SECTION TEXT: {section_statement}

INSTRUCTIONS:
- Generate 1-5 specific, verifiable questions per section.
- Each question should be answerable as COMPLIANT, VIOLATION, or INSUFFICIENT_EVIDENCE.
- Questions should be concrete and specific to what the document should contain or disclose.
- For each question, suggest the best LightRAG retrieval mode:
  * "local" for specific entity/fact lookups (names, amounts, dates)
  * "global" for broad themes and cross-document patterns
  * "hybrid" for questions needing both specific facts and context
- Include relevant keywords for retrieval.
- If the section is clearly not applicable to this document type, return an empty array.

Return ONLY a valid JSON array where each element has:
{{"question_text": "...", "suggested_mode": "local|global|hybrid", "keywords": ["..."]}}

Return ONLY the JSON array, no explanation."""

            try:
                response_text = generate_with_thinking(
                    model, prompt,
                    debug_label=f"phase1_{cat_key}_{section_key}",
                    debug_dir=out_dir / "debug_thoughts",
                ).strip()

                # Handle markdown code blocks
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    response_text = "\n".join(lines[1:-1])

                questions = json.loads(response_text)

                for q in questions:
                    question_counter += 1
                    q["question_id"] = f"Q{question_counter:04d}"
                    q["source_category"] = cat_key
                    q["source_category_name"] = cat_name
                    q["source_section"] = section_key
                    q["source_section_name"] = section_name
                    all_questions.append(q)

            except (json.JSONDecodeError, Exception) as e:
                print(f"  [Phase 1] Error processing {section_name}: {e}")
                continue

        print(f"  [Phase 1] Generated {question_counter} questions so far")

    output_path = out_dir / "atomic_questions.json"
    with open(output_path, "w") as f:
        json.dump(all_questions, f, indent=2, ensure_ascii=False)

    print(f"\n[Phase 1] Total atomic questions: {len(all_questions)}")
    print(f"[Phase 1] Output saved to {output_path}")

    return all_questions


def main():
    parser = argparse.ArgumentParser(description="Phase 1: Law Atomisation")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    args = parser.parse_args()

    asyncio.run(atomise_laws(output_dir=args.output_dir))


if __name__ == "__main__":
    main()
