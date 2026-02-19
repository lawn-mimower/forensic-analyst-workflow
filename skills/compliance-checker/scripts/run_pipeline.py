#!/usr/bin/env python3
"""
Compliance Checker — Full Pipeline Orchestrator.

Runs all five phases sequentially:
  Phase 0: Document Profiling
  Phase 1: Law Atomisation
  Phase 2: Batch Retrieval
  Phase 3: Adjudication
  Phase 4: Report Generation

Usage:
    python run_pipeline.py --storage ./rag_storage
    python run_pipeline.py --storage ./rag_storage --output-dir ./my_outputs
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from skills.shared.lightrag_init import ensure_output_dir

# Import sibling scripts directly (directory has a hyphen, so use importlib)
import importlib.util

def _import_phase(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_mod_profile = _import_phase("profile_document")
_mod_atomise = _import_phase("atomise_laws")
_mod_retrieve = _import_phase("batch_retrieve")
_mod_adjudicate = _import_phase("adjudicate")
_mod_report = _import_phase("generate_report")

profile_document = _mod_profile.profile_document
atomise_laws = _mod_atomise.atomise_laws
batch_retrieve = _mod_retrieve.batch_retrieve
adjudicate = _mod_adjudicate.adjudicate
generate_report = _mod_report.generate_report


async def run_pipeline(
    storage: str = "./rag_storage",
    output_dir: str | None = None,
    max_concurrent: int = 4,
):
    """Execute the full compliance checking pipeline."""
    out_dir = ensure_output_dir(output_dir)
    out_str = str(out_dir)

    print("=" * 60)
    print("COMPLIANCE CHECKER PIPELINE")
    print("=" * 60)

    # Phase 0
    print("\n" + "=" * 60)
    print("PHASE 0: Document Profiling")
    print("=" * 60)
    profile = await profile_document(storage=storage, output_dir=out_str)

    # Phase 1
    print("\n" + "=" * 60)
    print("PHASE 1: Law Atomisation")
    print("=" * 60)
    questions = await atomise_laws(output_dir=out_str)

    # Phase 2
    print("\n" + "=" * 60)
    print("PHASE 2: Batch Retrieval")
    print("=" * 60)
    contexts = await batch_retrieve(
        storage=storage, output_dir=out_str, max_concurrent=max_concurrent
    )

    # Phase 3
    print("\n" + "=" * 60)
    print("PHASE 3: Adjudication")
    print("=" * 60)
    verdicts = await adjudicate(output_dir=out_str, max_concurrent=max_concurrent)

    # Phase 4
    print("\n" + "=" * 60)
    print("PHASE 4: Report Generation")
    print("=" * 60)
    report = await generate_report(output_dir=out_str)

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Overall Score: {report['overall']['score_pct']}")
    print(f"Reports saved to: {out_dir}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Compliance Checker — Full Pipeline")
    parser.add_argument("--storage", default="./rag_storage", help="LightRAG storage dir")
    parser.add_argument("--output-dir", default=None, help="Output directory for all phases")
    parser.add_argument("--max-concurrent", type=int, default=4, help="Max concurrent API calls")
    args = parser.parse_args()

    asyncio.run(run_pipeline(
        storage=args.storage,
        output_dir=args.output_dir,
        max_concurrent=args.max_concurrent,
    ))


if __name__ == "__main__":
    main()
