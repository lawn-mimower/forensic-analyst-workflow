# Forensic Analyst Workflow

A RAG-based financial document analysis system with automated compliance checking against Indian financial laws. Ingest PDF and Excel financial statements into a LightRAG knowledge graph, query them conversationally, and run a fully automated 5-phase compliance audit pipeline that scores documents against 17 categories of Indian regulatory requirements.

---

## Architecture Overview

The system uses a dual-LLM architecture built on top of a LightRAG knowledge graph:

- **Knowledge Graph Construction and Retrieval** -- [Mistral](https://mistral.ai/) (`ministral-14b-2512`) handles entity extraction, relation building, and internal LightRAG operations. This keeps the graph-building pipeline cost-effective while maintaining quality.
- **Reasoning and Adjudication** -- [Google Gemini](https://ai.google.dev/) (`gemini-2.5-flash`) powers the conversational chatbot agent (via [Agno](https://github.com/agno-agi/agno)) and compliance adjudication, where stronger reasoning is needed to render verdicts.
- **Embeddings** -- Local `all-MiniLM-L6-v2` (384-dimensional, via `sentence-transformers`) for all vector operations. No embedding API costs.
- **Document Parsing** -- [Docling](https://github.com/DS4SD/docling) converts PDF and Excel files to Markdown before indexing.

LightRAG provides five retrieval modes (`local`, `global`, `hybrid`, `mix`, `naive`) over a knowledge graph stored as a GraphML file with nano-vectordb indices, enabling both entity-level lookups and cross-document thematic queries.

---

## Project Structure

```
Forensic_workflow/
|-- rag_chatbot.ipynb                         # Main notebook: ingest documents, build KG, interactive chat
|-- model_config.yaml                         # LLM provider/role configuration (hot-swappable)
|-- indian_financial_fraud_compliance_laws.json # 17 categories of Indian financial/compliance laws
|-- requirements.txt                           # Python dependencies
|-- .env                                       # API keys (GEMINI_API_KEY, MISTRAL_API_KEY)
|
|-- user_documents/                            # Place input documents here (PDF, XLSX, CSV, images, etc.)
|   +sample_docs/sample_statement.pdf     # Example input document
|
|-- rag_storage/                               # LightRAG knowledge graph data
|   |-- graph_chunk_entity_relation.graphml    # Entity-relation graph
|   |-- vdb_entities.json                      # Entity vector index
|   |-- vdb_relationships.json                 # Relationship vector index
|   |-- vdb_chunks.json                        # Chunk vector index
|   +-- kv_store_*.json                        # Key-value stores (docs, chunks, cache)
|
|-- skills/
|   |-- shared/
|   |   |-- __init__.py
|   |   |-- lightrag_init.py                   # Shared LightRAG factory, rate limiter, LLM/embedding funcs
|   |   |-- rate_limiter.py                    # Per-provider rate limiting
|   |   |-- llm_providers.py                   # Unified LLM provider wrappers (Mistral, Gemini, Anthropic)
|   |   |-- llm_registry.py                    # YAML-driven role→provider mapping with hot-swap
|   |   |-- lightrag_client.py                 # Dual-mode LightRAG client (HTTP server / direct library)
|   |   |-- preprocessors.py                   # File-type-aware document preprocessing (Docling, openpyxl, pandas)
|   |   |-- agent_tools.py                     # ForensicToolkit (9 agent tools)
|   |   +-- model_config_agno.py               # Agno Model factory for agent LLM selection
|   |
|   |-- lightrag-query/
|   |   |-- SKILL.md
|   |   +-- scripts/
|   |       +-- query.py                       # CLI for querying the knowledge graph
|   |
|   +-- compliance-checker/
|       |-- SKILL.md
|       |-- references/
|       |   +-- output_format.md               # JSON schemas for all pipeline outputs
|       |-- scripts/
|       |   |-- run_pipeline.py                # Full pipeline runner (phases 0-4)
|       |   |-- profile_document.py            # Phase 0: document profiling
|       |   |-- atomise_laws.py                # Phase 1: generate atomic compliance questions
|       |   |-- batch_retrieve.py              # Phase 2: parallel LightRAG context retrieval
|       |   |-- adjudicate.py                  # Phase 3: Gemini compliance verdicts
|       |   +-- generate_report.py             # Phase 4: score aggregation and report generation
|       +-- outputs/
|           |-- document_profile.json          # Phase 0 output
|           |-- atomic_questions.json          # Phase 1 output
|           |-- retrieved_contexts.json        # Phase 2 output
|           |-- verdicts.json                  # Phase 3 output
|           |-- compliance_report.json         # Phase 4 structured report
|           +-- compliance_report.md           # Phase 4 human-readable report
|
+-- reports/                                   # Architecture documentation (HTML)
```

---

## Skills

### LightRAG Query

Query the indexed knowledge graph from the command line with configurable retrieval modes.

| Mode | Best For |
|---|---|
| `local` | Specific entity lookups (e.g., "What is ExampleCo's revenue?") |
| `global` | Broad summaries and cross-document themes |
| `hybrid` | Balanced -- combines local entity + global theme retrieval |
| `mix` | All retrieval strategies merged |
| `naive` | Simple vector similarity (baseline) |

Supports `--context-only` mode for raw retrieved chunks without LLM synthesis, which the compliance pipeline uses for Phase 2 retrieval.

### Compliance Checker

A 5-phase automated pipeline that checks an indexed financial document against applicable Indian financial and compliance laws.

| Phase | Script | Description |
|---|---|---|
| 0 | `profile_document.py` | Runs a global LightRAG query to summarize the document, then selects applicable law categories from the 17 available |
| 1 | `atomise_laws.py` | Breaks applicable laws into atomic yes/no compliance questions with suggested retrieval modes and keywords |
| 2 | `batch_retrieve.py` | Parallel LightRAG context-only queries for each question (rate-limited, max 4 concurrent) |
| 3 | `adjudicate.py` | Gemini renders per-question verdicts: `COMPLIANT`, `VIOLATION`, or `INSUFFICIENT_EVIDENCE` with reasoning and supporting excerpts |
| 4 | `generate_report.py` | Aggregates scores at section, category, and overall levels; produces both JSON and Markdown reports |

**Scoring formula**: `compliant / (compliant + violation)` -- questions marked `INSUFFICIENT_EVIDENCE` are excluded from the denominator so they do not inflate or deflate the score.

### Forensic Analytics Pipeline

A structured-data track next to the knowledge graph: tables are extracted from the financial statements, normalised into a DuckDB workbench and swept by five deterministic analysis skills (no LLM calls). A Streamlit app wraps the pipeline, the skill dashboards and a chat agent.

| Component | Description |
|---|---|
| `pipeline/table_extractor.py` | Context-aware table extraction: Docling for PDF/DOCX, openpyxl for Excel (merged cells, formulas, unit annotations), pandas for CSV |
| `pipeline/mistral_extractor.py` | Mistral OCR backend for PDFs with the same `ExtractedTable` output; raw responses are cached on disk |
| `pipeline/data_normalizer.py` | Classifies tables, converts lakhs/crores to rupees, assigns fiscal periods and loads `source_tables`, `line_items`, `related_parties` and `analysis_results` |
| `skills/shared/data_inspector.py`, `data_curator.py` | Data-quality profile and `curated_line_items` / `curated_related_parties` views (period consolidation, de-duplication, entity whitelist) |
| `skills/benfords-analysis/` | First, second, first-two and last-two digit tests plus the summation test (Nigrini MAD thresholds) |
| `skills/duplicate-detector/` | Exact, near-amount, fuzzy-name and cross-period duplicates and round-number concentration |
| `skills/ratio-analyzer/` | Margins and expense ratios per period with year-on-year change flags |
| `skills/anomaly-detector/` | IQR, Z-score and Isolation Forest (PyOD) outliers with a consensus flag |
| `skills/network-analyzer/` | Related-party graph: centrality, Louvain communities, cycles and hubs |
| `frontend/` | Streamlit app (`app.py`), pipeline runner and the Agno forensic agent with its toolkit |

Every skill writes a JSON report with a 1-10 risk score and investigation suggestions.

---

## Setup and Prerequisites

### Python Environment

The project uses a conda environment named `ml-env` with Python 3.12:

```bash
conda activate ml-env
```

### Required Packages

Core dependencies (see `requirements.txt` for the full list):

| Package | Purpose |
|---|---|
| `lightrag-hku` | Knowledge graph construction and retrieval |
| `mistralai` | Mistral API client (KG building LLM) |
| `google-genai` | Gemini API client (reasoning/adjudication LLM) |
| `sentence-transformers` | Local embeddings (`all-MiniLM-L6-v2`) |
| `agno` | Agent framework for the chatbot |
| `docling` | PDF/Excel to Markdown conversion |
| `python-dotenv` | Environment variable management |
| `nest-asyncio` | Async support in Jupyter notebooks |

### Environment Variables

Create a `.env` file in the project root (see `.env.example`) with:

```
GEMINI_API_KEY=your_gemini_api_key
MISTRAL_API_KEY=your_mistral_api_key
```

Install the dependencies with `pip install -r requirements.txt` and run all commands below from the project root.

### Running Tests

```bash
# Offline suite (LLM calls are replaced with deterministic fakes; no API keys needed)
pytest

# Skip the tests that load local models (Docling, sentence-transformers)
pytest -m "not slow"

# Live end-to-end run against Mistral + Gemini (needs both API keys)
pytest -m e2e
```

The tests use a small fictional company, Acme Widgets Private Limited (`tests/fixtures/`).
To try the notebook or CLI on the same sample data, write sample XLSX/PDF files into `user_documents/` with:

```bash
python tests/fixtures/build_fixtures.py
```

---

## Usage

### 1. Document Ingestion and Chat (Notebook)

Open `rag_chatbot.ipynb` and run cells sequentially:

1. **Environment setup** -- loads API keys and initializes the LightRAG instance with Mistral LLM and local embeddings.
2. **Document indexing** -- place documents in `user_documents/`, add their paths to `files_to_index`, then run the cell to preprocess (file-type-aware) and index into the knowledge graph. Or skip this and use the agent's `upload_document` tool interactively.
3. **Interactive chat** -- starts a conversational loop powered by a Gemini agent with 9 tools (search, upload, preview, compliance check, etc.).

```bash
jupyter notebook rag_chatbot.ipynb
```

### 2. Knowledge Graph Query (CLI)

```bash
# Basic hybrid query
python skills/lightrag-query/scripts/query.py --query "What is ExampleCo's total revenue?"

# Specific mode with custom storage path
python skills/lightrag-query/scripts/query.py \
  --query "Who are the related parties?" \
  --mode local \
  --storage ./rag_storage

# Raw context retrieval (no LLM synthesis)
python skills/lightrag-query/scripts/query.py \
  --query "CSR expenditure" \
  --context-only
```

### 3. Compliance Audit Pipeline

**Full pipeline (recommended):**

```bash
python skills/compliance-checker/scripts/run_pipeline.py --storage ./rag_storage
```

**Phase-by-phase execution:**

```bash
# Phase 0: Profile the document and select applicable law categories
python skills/compliance-checker/scripts/profile_document.py --storage ./rag_storage

# Phase 1: Generate atomic yes/no compliance questions
python skills/compliance-checker/scripts/atomise_laws.py

# Phase 2: Retrieve context from the KG for each question
python skills/compliance-checker/scripts/batch_retrieve.py --storage ./rag_storage

# Phase 3: Gemini adjudicates each question
python skills/compliance-checker/scripts/adjudicate.py

# Phase 4: Aggregate scores and generate reports
python skills/compliance-checker/scripts/generate_report.py
```

All intermediate and final outputs are written to `skills/compliance-checker/outputs/`.

### 4. Forensic Pipeline and Streamlit App

```bash
# Sample documents for the fictional Acme Widgets Private Limited (written to user_documents/)
python tests/fixtures/build_fixtures.py

# Extract + normalise into DuckDB (defaults to every PDF/Excel/CSV file in user_documents/),
# then sweep all five skills (reports go to skills/<skill>/outputs/sweep.json)
python -m pipeline.test_normalization --entity "Acme Widgets Private Limited" --fiscal-year 2024-25 --run-skills

# Use Mistral OCR for PDFs instead of Docling (needs MISTRAL_API_KEY)
python -m pipeline.test_normalization --extractor mistral

# Run a single skill against the workbench
python skills/duplicate-detector/scripts/duplicate_detector.py \
  --db pipeline/test_output/test_forensic.duckdb --output duplicates.json

# Chat UI with upload, pipeline run and dashboards
streamlit run frontend/app.py
```

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `FORENSIC_OUTPUT_DIR` | `pipeline/test_output/` | DuckDB workbench, table cache and skill reports written by the app's pipeline runs |
| `FORENSIC_AGENT_DB` | `data/forensic_agent.db` | SQLite file for the agent's sessions and memory |
| `MISTRAL_OCR_CACHE_DIR` | `pipeline/test_output/mistral_cache/` | Cached Mistral OCR responses |

---

## Sample Output

Running the full compliance pipeline against `user_documents/sample_docs/sample_statement.pdf` (**Example Engineering Private Limited Profit & Loss Statement, FY 2023-24**) produced the following results:

| Metric | Value |
|---|---|
| Overall Compliance Score | **84.3%** |
| Total Questions Generated | 141 |
| Compliant | 43 |
| Violations | 8 |
| Insufficient Evidence | 90 |

The high `INSUFFICIENT_EVIDENCE` count reflects the nature of the input document -- a standalone P&L statement does not contain the full set of disclosures, board resolutions, and audit reports that a complete annual filing would. The scoring formula excludes these from the denominator, so the 84.3% score represents compliance confidence across the 51 questions where the document contained enough information to render a judgment.

Category-level breakdown from the report:

- **Companies Act, 2013**: 100.0% (14 compliant, 0 violations, 36 insufficient)
- Other categories include Income Tax Act, GST, SEBI regulations, and related party transaction rules, each scored independently at section granularity.

The full structured report is available at `skills/compliance-checker/outputs/compliance_report.json` and the human-readable version at `skills/compliance-checker/outputs/compliance_report.md`.
