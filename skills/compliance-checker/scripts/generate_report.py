#!/usr/bin/env python3
"""
Phase 4 — Report Generation.

Aggregates verdicts by category and section, computes compliance scores,
and produces both JSON and Markdown reports.

Input:  outputs/document_profile.json, outputs/atomic_questions.json, outputs/verdicts.json
Output: outputs/compliance_report.json, outputs/compliance_report.md
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.lightrag_init import ensure_output_dir, get_category_display_names


def _compute_score(compliant: int, violation: int) -> float | None:
    """Compute compliance score. Returns None if no judgeable items."""
    total = compliant + violation
    if total == 0:
        return None
    return compliant / total


async def generate_report(output_dir: str | None = None) -> dict:
    """Run Phase 4: aggregate verdicts into a compliance report."""
    out_dir = ensure_output_dir(output_dir)

    # Load all inputs
    profile_path = out_dir / "document_profile.json"
    questions_path = out_dir / "atomic_questions.json"
    verdicts_path = out_dir / "verdicts.json"

    for p, name in [(profile_path, "Phase 0"), (questions_path, "Phase 1"), (verdicts_path, "Phase 3")]:
        if not p.exists():
            raise FileNotFoundError(f"{name} output not found: {p}")

    with open(profile_path) as f:
        profile = json.load(f)
    with open(questions_path) as f:
        questions = json.load(f)
    with open(verdicts_path) as f:
        verdicts = json.load(f)

    cat_display = get_category_display_names()

    # Index questions and verdicts by question_id
    q_map = {q["question_id"]: q for q in questions}
    v_map = {v["question_id"]: v for v in verdicts}

    # Group by category → section
    categories = {}
    for q in questions:
        qid = q["question_id"]
        cat_key = q["source_category"]
        sec_key = q["source_section"]
        sec_name = q.get("source_section_name", sec_key)
        verdict_data = v_map.get(qid, {"verdict": "INSUFFICIENT_EVIDENCE", "reasoning": "", "excerpt": ""})

        if cat_key not in categories:
            categories[cat_key] = {
                "category_name": cat_display.get(cat_key, cat_key),
                "sections": {},
                "totals": {"COMPLIANT": 0, "VIOLATION": 0, "INSUFFICIENT_EVIDENCE": 0},
            }

        cat = categories[cat_key]
        if sec_key not in cat["sections"]:
            cat["sections"][sec_key] = {
                "section_name": sec_name,
                "questions": [],
                "totals": {"COMPLIANT": 0, "VIOLATION": 0, "INSUFFICIENT_EVIDENCE": 0},
            }

        sec = cat["sections"][sec_key]
        entry = {
            "question_id": qid,
            "question_text": q["question_text"],
            "verdict": verdict_data["verdict"],
            "reasoning": verdict_data.get("reasoning", ""),
            "excerpt": verdict_data.get("excerpt", ""),
        }
        sec["questions"].append(entry)
        sec["totals"][verdict_data["verdict"]] += 1
        cat["totals"][verdict_data["verdict"]] += 1

    # Compute scores
    overall = {"COMPLIANT": 0, "VIOLATION": 0, "INSUFFICIENT_EVIDENCE": 0}
    for cat_key, cat in categories.items():
        for sec_key, sec in cat["sections"].items():
            t = sec["totals"]
            sec["score"] = _compute_score(t["COMPLIANT"], t["VIOLATION"])
            sec["total_questions"] = sum(t.values())
        t = cat["totals"]
        cat["score"] = _compute_score(t["COMPLIANT"], t["VIOLATION"])
        cat["total_questions"] = sum(t.values())
        for k in overall:
            overall[k] += t[k]

    overall_score = _compute_score(overall["COMPLIANT"], overall["VIOLATION"])

    report = {
        "report_metadata": {
            "generated_at": datetime.now().isoformat(),
            "document_summary": profile.get("document_summary", ""),
            "total_categories": len(categories),
            "total_questions": len(questions),
        },
        "overall": {
            "score": overall_score,
            "score_pct": f"{overall_score * 100:.1f}%" if overall_score is not None else "N/A",
            "totals": overall,
        },
        "categories": categories,
    }

    # Write JSON report
    json_path = out_dir / "compliance_report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Write Markdown report
    md_path = out_dir / "compliance_report.md"
    md = _generate_markdown(report, profile)
    with open(md_path, "w") as f:
        f.write(md)

    print(f"[Phase 4] Overall score: {report['overall']['score_pct']}")
    print(f"[Phase 4] Verdicts: {overall}")
    print(f"[Phase 4] JSON report: {json_path}")
    print(f"[Phase 4] Markdown report: {md_path}")

    return report


def _generate_markdown(report: dict, profile: dict) -> str:
    """Generate the Markdown compliance report."""
    overall = report["overall"]
    meta = report["report_metadata"]
    lines = []

    # Extract entity name from summary (first line heuristic)
    summary = meta.get("document_summary", "")
    entity = "Unknown Entity"
    for keyword in ["ExampleCo", "EXAMPLECO", "EXCO"]:
        if keyword.lower() in summary.lower():
            entity = "Example Engineering Private Limited"
            break

    lines.append(f"# Compliance Report: {entity}")
    lines.append("")
    lines.append(f"**Generated**: {meta['generated_at']}")
    lines.append(f"**Overall Score**: {overall['score_pct']} | "
                 f"**Questions**: {meta['total_questions']} | "
                 f"**Compliant**: {overall['totals']['COMPLIANT']} | "
                 f"**Violations**: {overall['totals']['VIOLATION']} | "
                 f"**Insufficient Evidence**: {overall['totals']['INSUFFICIENT_EVIDENCE']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for cat_key, cat in report["categories"].items():
        cat_score = f"{cat['score'] * 100:.1f}%" if cat["score"] is not None else "N/A"
        lines.append(f"## {cat['category_name']}")
        lines.append(f"**Category Score**: {cat_score} | "
                     f"**Compliant**: {cat['totals']['COMPLIANT']} | "
                     f"**Violations**: {cat['totals']['VIOLATION']} | "
                     f"**Insufficient**: {cat['totals']['INSUFFICIENT_EVIDENCE']}")
        lines.append("")

        for sec_key, sec in cat["sections"].items():
            t = sec["totals"]
            judgeable = t["COMPLIANT"] + t["VIOLATION"]
            sec_score = f"{t['COMPLIANT']}/{judgeable} ({sec['score'] * 100:.0f}%)" if sec["score"] is not None else "N/A"
            insuf = f" | {t['INSUFFICIENT_EVIDENCE']} INSUFFICIENT" if t["INSUFFICIENT_EVIDENCE"] > 0 else ""

            lines.append(f"### {sec['section_name']}")
            lines.append(f"**Score**: {sec_score}{insuf}")
            lines.append("")
            lines.append("| # | Question | Verdict | Reasoning | Excerpt |")
            lines.append("|---|---|---|---|---|")

            for i, q in enumerate(sec["questions"], 1):
                # Escape pipes in cell content
                question_text = q["question_text"].replace("|", "\\|")
                reasoning = q["reasoning"].replace("|", "\\|").replace("\n", " ")
                excerpt = q["excerpt"].replace("|", "\\|").replace("\n", " ")
                verdict_icon = {"COMPLIANT": "COMPLIANT", "VIOLATION": "VIOLATION", "INSUFFICIENT_EVIDENCE": "INSUFFICIENT"}
                verdict = verdict_icon.get(q["verdict"], q["verdict"])
                lines.append(f"| {i} | {question_text} | {verdict} | {reasoning} | {excerpt} |")

            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Phase 4: Report Generation")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    args = parser.parse_args()

    asyncio.run(generate_report(output_dir=args.output_dir))


if __name__ == "__main__":
    main()
