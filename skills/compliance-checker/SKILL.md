---
name: compliance-checker
description: Check an indexed financial document against Indian compliance laws using a 5-phase pipeline
triggers:
  - check compliance
  - run compliance audit
  - verify against laws
  - compliance check
---

# Compliance Checker Skill

Systematically checks an indexed financial document against applicable Indian financial/compliance laws using a 5-phase pipeline.

## Pipeline Overview

| Phase | Script | Description |
|---|---|---|
| 0 | `profile_document.py` | Global query → document summary → select applicable law categories |
| 1 | `atomise_laws.py` | Break applicable laws into atomic yes/no compliance questions |
| 2 | `batch_retrieve.py` | Parallel LightRAG context-only queries for each question |
| 3 | `adjudicate.py` | Gemini verdicts: COMPLIANT / VIOLATION / INSUFFICIENT_EVIDENCE |
| 4 | `generate_report.py` | Score aggregation → JSON + Markdown compliance report |

## Usage

### Full Pipeline (recommended)

```bash
python skills/compliance-checker/scripts/run_pipeline.py --storage ./rag_storage
```

### Phase-by-Phase

Run each phase independently (each reads the previous phase's output):

```bash
# Phase 0: Profile the document
python skills/compliance-checker/scripts/profile_document.py --storage ./rag_storage

# Phase 1: Generate atomic questions
python skills/compliance-checker/scripts/atomise_laws.py

# Phase 2: Retrieve contexts
python skills/compliance-checker/scripts/batch_retrieve.py --storage ./rag_storage

# Phase 3: Adjudicate
python skills/compliance-checker/scripts/adjudicate.py

# Phase 4: Generate report
python skills/compliance-checker/scripts/generate_report.py
```

### Common Arguments

| Arg | Default | Description |
|---|---|---|
| `--storage` | `./rag_storage` | Path to LightRAG storage directory |
| `--output-dir` | `skills/compliance-checker/outputs/` | Where intermediate + final outputs go |
| `--max-concurrent` | `4` | Max parallel API calls (Phases 2, 3) |

## Output Files

All outputs go to `skills/compliance-checker/outputs/`:

| File | Phase | Description |
|---|---|---|
| `document_profile.json` | 0 | Document summary + applicable categories |
| `atomic_questions.json` | 1 | All generated compliance questions |
| `retrieved_contexts.json` | 2 | Retrieved KG context per question |
| `verdicts.json` | 3 | Per-question compliance verdicts |
| `compliance_report.json` | 4 | Full structured report with scores |
| `compliance_report.md` | 4 | Human-readable Markdown report |

## Prerequisites

- A LightRAG knowledge graph must already be built (via `rag_chatbot.ipynb`)
- `indian_financial_fraud_compliance_laws.json` must exist in the project root
- `.env` must contain `GEMINI_API_KEY` and `MISTRAL_API_KEY`
