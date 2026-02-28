#!/usr/bin/env python3
"""
Phase 3 — Adjudication.

For each (question, context) pair, uses Gemini to produce a verdict:
COMPLIANT, VIOLATION, or INSUFFICIENT_EVIDENCE.

Input:  outputs/atomic_questions.json, outputs/retrieved_contexts.json
Output: outputs/verdicts.json
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.lightrag_init import get_gemini_model, generate_with_thinking, ensure_output_dir, DEFAULT_OUTPUT_DIR

VALID_VERDICTS = {"COMPLIANT", "VIOLATION", "INSUFFICIENT_EVIDENCE"}


async def _adjudicate_single(
    model,
    question: dict,
    context: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Adjudicate a single question against its retrieved context."""
    qid = question["question_id"]

    async with semaphore:
        # Empty context → immediate INSUFFICIENT_EVIDENCE
        if context.get("is_empty", True):
            return {
                "question_id": qid,
                "verdict": "INSUFFICIENT_EVIDENCE",
                "reasoning": "No relevant context was retrieved from the knowledge graph for this question.",
                "excerpt": "",
            }

        context_text = context["context_text"]
        question_text = question["question_text"]
        section_name = question.get("source_section_name", "")

        prompt = f"""You are a financial compliance auditor. Using ONLY the provided context,
determine whether the document complies with the given requirement.

COMPLIANCE REQUIREMENT (from {section_name}):
{question_text}

RETRIEVED CONTEXT FROM DOCUMENT:
{context_text}

INSTRUCTIONS:
- Base your verdict ONLY on the provided context. Do not use external knowledge.
- If the context clearly shows compliance, verdict is COMPLIANT.
- If the context shows a clear violation or non-compliance, verdict is VIOLATION.
- If the context is insufficient, ambiguous, or does not address the question, verdict is INSUFFICIENT_EVIDENCE.
- Provide brief reasoning (1-3 sentences).
- Quote the most relevant excerpt from the context (if any).

Return ONLY a valid JSON object with exactly these fields:
{{"verdict": "COMPLIANT|VIOLATION|INSUFFICIENT_EVIDENCE", "reasoning": "...", "excerpt": "..."}}

Return ONLY the JSON object, no explanation."""

        try:
            response_text = generate_with_thinking(
                model, prompt,
                debug_label=f"phase3_{qid}",
                debug_dir=DEFAULT_OUTPUT_DIR / "debug_thoughts",
            ).strip()

            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])

            result = json.loads(response_text)

            # Validate verdict
            verdict = result.get("verdict", "").upper().replace(" ", "_")
            if verdict not in VALID_VERDICTS:
                verdict = "INSUFFICIENT_EVIDENCE"

            return {
                "question_id": qid,
                "verdict": verdict,
                "reasoning": result.get("reasoning", ""),
                "excerpt": result.get("excerpt", ""),
            }

        except (json.JSONDecodeError, Exception) as e:
            return {
                "question_id": qid,
                "verdict": "INSUFFICIENT_EVIDENCE",
                "reasoning": f"Error during adjudication: {e}",
                "excerpt": "",
            }


async def adjudicate(
    output_dir: str | None = None,
    max_concurrent: int = 4,
) -> list[dict]:
    """Run Phase 3: adjudicate all questions against their contexts."""
    out_dir = ensure_output_dir(output_dir)

    # Load inputs
    questions_path = out_dir / "atomic_questions.json"
    contexts_path = out_dir / "retrieved_contexts.json"

    if not questions_path.exists():
        raise FileNotFoundError(f"Phase 1 output not found: {questions_path}")
    if not contexts_path.exists():
        raise FileNotFoundError(f"Phase 2 output not found: {contexts_path}")

    with open(questions_path) as f:
        questions = json.load(f)
    with open(contexts_path) as f:
        contexts = json.load(f)

    print(f"[Phase 3] Adjudicating {len(questions)} questions (max_concurrent={max_concurrent})")

    model = get_gemini_model()
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = []
    for q in questions:
        qid = q["question_id"]
        ctx = contexts.get(qid, {"is_empty": True, "context_text": ""})
        tasks.append(_adjudicate_single(model, q, ctx, semaphore))

    verdicts = await asyncio.gather(*tasks)

    # Summary stats
    counts = {"COMPLIANT": 0, "VIOLATION": 0, "INSUFFICIENT_EVIDENCE": 0}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1

    output_path = out_dir / "verdicts.json"
    with open(output_path, "w") as f:
        json.dump(verdicts, f, indent=2, ensure_ascii=False)

    print(f"[Phase 3] Verdicts: {counts}")
    print(f"[Phase 3] Output saved to {output_path}")

    return verdicts


def main():
    parser = argparse.ArgumentParser(description="Phase 3: Adjudication")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--max-concurrent", type=int, default=4, help="Max concurrent Gemini calls")
    args = parser.parse_args()

    asyncio.run(adjudicate(output_dir=args.output_dir, max_concurrent=args.max_concurrent))


if __name__ == "__main__":
    main()
