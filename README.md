# Forensic Analyst Workflow

Checking a company's financial statements for compliance gaps or signs of manipulation means reading the narrative (notes, disclosures, related-party schedules) and testing the numbers. This project does both from the same documents. The text goes into a LightRAG knowledge graph that answers questions and drives a five-phase compliance audit against Indian financial and corporate law. The tables are extracted into a DuckDB workbench, where five deterministic forensic tests (Benford's law, duplicates, ratios, anomalies, related-party networks) run without an LLM. An Agno chat agent and a Streamlit app sit on top of both.

This is a personal proof of concept, not a finished product. No financial documents ship with the repository. You supply your own, and `tests/fixtures/` holds a small fictional company (Acme Widgets Private Limited) to try it on.

## How it works

```
                  ┌─ text ──► LightRAG knowledge graph ──► questions (local / global / hybrid / mix / naive)
 your documents ──┤          (Mistral extracts entities,  └─► compliance audit (Gemini):
 user_documents/  │           local MiniLM embeddings)         profile → atomise → retrieve → adjudicate → report
                  │
                  └─ tables ─► normalise (units, periods) ─► DuckDB workbench ─► curate ─► 5 forensic tests
                                                                                           (JSON reports, dashboards)

 Agno agent: tools over both sides plus read-only SQL on the workbench.
 Streamlit app: upload, run the table pipeline, dashboards, chat with the agent.
```

**Knowledge graph.** Documents are converted to text or Markdown (see [Inputs](#inputs)) and indexed by LightRAG. Mistral (`ministral-14b-2512`) extracts the entities and relations. Embeddings come from a local `all-MiniLM-L6-v2` model, so they need no API calls. The graph is kept in LightRAG's default file storage under `rag_storage/`.

**Compliance audit** (`skills/compliance-checker/`). The audit runs against `indian_financial_fraud_compliance_laws.json`, which holds 19 categories and 134 sections: the Companies Act 2013, IPC/BNS, PMLA, SEBI, RBI, Income Tax, GST, FEMA, IBC, the ICAI standards and others.

| Phase | What happens |
|---|---|
| 0 Profile | A global graph query summarises the document. Gemini then picks the law categories that apply (for example, SEBI only for listed companies). |
| 1 Atomise | For each section that applies, Gemini writes 1–5 yes/no questions, each with a suggested retrieval mode and keywords. |
| 2 Retrieve | A context-only LightRAG query runs for each question, up to 4 in parallel. |
| 3 Adjudicate | Gemini returns `COMPLIANT`, `VIOLATION` or `INSUFFICIENT_EVIDENCE`, with reasoning and a quoted excerpt, constrained to a JSON schema. A question with no retrieved context is marked insufficient without an LLM call. |
| 4 Report | Scores per section, per category and overall, written as JSON and Markdown. |

Score = compliant / (compliant + violation). Insufficient-evidence answers are left out of the denominator, so a thin document is scored only on the questions it can answer. The report lists those counts separately.

**Forensic workbench** (`pipeline/`, `skills/*/`). Tables are extracted together with their context: heading, page or sheet, and unit annotation. Each table is classified (P&L, balance sheet, related-party schedule, ledger and so on), converted from lakhs or crores to rupees, assigned fiscal periods, and loaded into `source_tables`, `line_items` and `related_parties`. An inspector flags quality problems. A curator then builds `curated_*` views (period consolidation, de-duplication, entity whitelist) without modifying the raw tables. Five tests run on the result:

| Test | Method |
|---|---|
| Benford's law | First-digit, second-digit, first-two-digit and last-two-digit tests plus the summation test. Uses MAD against Nigrini's thresholds, chi-squared, KS and per-digit z-scores. |
| Duplicates | Exact, near-amount (±1 % by default), fuzzy-name (rapidfuzz) and cross-period duplicates, plus round-number concentration. |
| Ratios | Margins and expense ratios per period. Year-on-year changes above a threshold (default 0.20) are flagged. |
| Anomalies | IQR, z-score and Isolation Forest (PyOD). An item counts as a consensus anomaly when at least two methods agree. |
| Related-party network | Graph of parties and amounts, with centrality, Louvain communities, cycles and hubs. |

Each test writes a JSON report with a 1–10 risk score and suggested follow-ups. The `SKILL.md` in each skill folder explains when the test applies and how to read the results.

**Agent.** `frontend/forensic_agent.py` builds an Agno agent with tools for the table pipeline, inspection and curation, the five tests, knowledge-graph search and upload, and the compliance phases. It can also run read-only SQL on the workbench. Sessions and memory are stored in SQLite. The notebook uses a smaller, nine-tool agent (`skills/shared/agent_tools.py`) limited to the knowledge graph, document preview and the compliance audit.

## Inputs

| Format | Knowledge-graph ingestion | Table pipeline |
|---|---|---|
| PDF | Mistral OCR (default) or Docling | Docling (CLI default) or Mistral OCR (app default) |
| XLSX, XLSM | openpyxl + pandas: per-sheet summary, Markdown table and the list of formulas | openpyxl: merged cells, formulas, unit rows, several tables per sheet |
| CSV | pandas | pandas |
| DOCX | Docling | Docling |
| PPTX, HTML, Markdown, PNG/JPG/TIFF/BMP | Docling | — |

`.xls` and `.xlsb` files are not supported because openpyxl cannot read them. Convert them to `.xlsx` first. Mistral OCR responses are cached on disk, so the same PDF is not sent to the API twice.

## What you can ask

Against the knowledge graph (CLI, notebook or agent):

- "What was revenue from operations in FY 2024-25, and how does it compare with the previous year?"
- "Who are the related parties and what was paid to each?"
- "Who is the statutory auditor?"
- "Is the company listed or unlisted, public or private?"

Compliance (CLI or agent):

- "Which of the 19 law categories apply to this company?"
- "Run the compliance check." The output is a verdict for each question, with the reasoning and the excerpt it relied on, rolled up into section, category and overall scores.

On the workbench (CLI, dashboards or agent):

- "Do these amounts follow Benford's law? Which digit ranges stand out?"
- "Are there duplicate, near-duplicate or suspiciously round entries?"
- "Which line items are statistical outliers?"
- "How did margins and expense ratios move year on year?"
- "Which related parties are hubs, and do money flows between them form cycles?"
- Ad-hoc questions about `line_items` or `related_parties`, which the agent answers with SQL.

The agent's instructions also ask it to cross-reference findings, for example a Benford anomaly and a duplicate in the same account.

## Quick start

Tested with Python 3.12 and lightrag-hku 1.4.9. Run every command from the repository root.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in GEMINI_API_KEY and MISTRAL_API_KEY
```

**Forensic workbench on the synthetic documents (no API keys needed):**

```bash
python tests/fixtures/build_fixtures.py       # writes four fictional Acme Widgets files to user_documents/
python -m pipeline.test_normalization --entity "Acme Widgets Private Limited" \
    --fiscal-year 2024-25 --run-skills        # → pipeline/test_output/test_forensic.duckdb
                                              #   and skills/<test>/outputs/sweep.json
streamlit run frontend/app.py                 # sidebar: "Load Existing DB" → pipeline/test_output/test_forensic.duckdb
```

The dashboards need no API keys. The chat tab needs a key for the agent's model. Run without paths, `test_normalization` processes every PDF, Excel and CSV file in `user_documents/`. Pass file paths to pick specific files, and add `--extractor mistral` to read PDFs with Mistral OCR.

**Knowledge graph and compliance audit (needs both keys):**

Index documents with `rag_chatbot.ipynb`: add their paths to `files_to_index`, or ask the notebook agent to `upload_document`. The Streamlit agent's `run_pipeline` tool also indexes a document. Then run:

```bash
python skills/lightrag-query/scripts/query.py --query "Who are the related parties?" --mode hybrid
python skills/lightrag-query/scripts/query.py --query "CSR expenditure" --context-only
python skills/compliance-checker/scripts/run_pipeline.py      # outputs in skills/compliance-checker/outputs/
```

Each audit phase also runs on its own (`profile_document.py`, `atomise_laws.py`, `batch_retrieve.py`, `adjudicate.py`, `generate_report.py`) and reads the output of the phase before it.

## Configuration

Environment variables are read from `.env` in the repository root:

| Variable | Used for |
|---|---|
| `MISTRAL_API_KEY` | Building and querying the knowledge graph; Mistral OCR |
| `GEMINI_API_KEY` | The compliance phases; the agent's default model (copied to `GOOGLE_API_KEY` if that is unset) |
| `AGENT_MODEL_PROVIDER`, `AGENT_MODEL_ID` | The agent's model: `google` (default, `gemini-3-flash-preview`), `mistral`, `anthropic`, `groq` or `openai`, with the matching `*_API_KEY` |
| `FORENSIC_OUTPUT_DIR` | Where app and agent runs write the workbench, table cache and test reports (default `pipeline/test_output/`) |
| `FORENSIC_AGENT_DB` | SQLite file for agent sessions and memory (default `data/forensic_agent.db`) |
| `MISTRAL_OCR_CACHE_DIR` | Cached Mistral OCR responses (default `pipeline/test_output/mistral_cache/`) |
| `MODEL_CONFIG_PATH` | Model config to use instead of `model_config.yaml` |

`model_config.yaml` maps roles to providers (`kg_llm`: Mistral `ministral-14b-2512`; `reasoning_llm`: Gemini `gemini-3-flash-preview`; the local embedding model) and sets per-provider rate limits. Mistral, Gemini, Anthropic and `openai_compat` providers are implemented. `openai_compat` talks to any OpenAI-compatible server, such as a local Ollama (`base_url: http://localhost:11434/v1`). Set `MODEL_CONFIG_PATH` to use another config file.

## Tests

```bash
python -m pytest                  # 138 offline tests, about 40 s; no API keys
python -m pytest -m "not slow"    # skip the 15 tests that load Docling or the embedding model
python -m pytest -m e2e           # live run against Mistral and Gemini; skipped unless both keys are set
```

The offline suite swaps Mistral and Gemini for deterministic fakes and runs the real code for everything else (the first run downloads the Docling and sentence-transformers models). It covers ingestion into a real LightRAG store, all five query modes, the compliance phases singly and end to end, the table extractors (including a canned Mistral OCR response), the normaliser, the five forensic tests on a workbench built from the synthetic documents (which contain planted duplicates and an outlier), the pipeline CLIs, both agent toolkits, and the Streamlit app through Streamlit's AppTest.

The live test indexes the fictional Markdown statement, asks one question and runs the compliance pipeline on a single law section.

## Status and limitations

- This is a proof of concept. Verdicts are an LLM's reading of retrieved context, not legal or audit advice. The law file holds short summaries of each section, not the full text of the statutes.
- The LLM-backed paths have a live test that has not been re-run recently. Those paths are graph building, question answering, the compliance audit and agent chat. The offline suite exercises the same code with fakes.
- LightRAG logs extraction failures instead of raising them. With an invalid Mistral key, `upload_document` still reports "Indexed …" while the document's status in `rag_storage/kv_store_doc_status.json` is `failed`. Check that file after indexing.
- LightRAG keeps process-wide state, so use one storage directory per process.
- The CLIs default `--storage` to `./rag_storage`, relative to the current directory. The notebook and the agents use `<repo>/rag_storage`. Run the CLIs from the repository root so both point at the same store.
- The table cache is keyed by extractor, not by file. In the app, "Use cached extraction" is ticked by default, and the agent's `run_pipeline` tool always uses the cache. Either way, a new document can get the previous run's tables. Untick the option, or delete `extracted_tables*.pkl`, when you switch documents.
- Unit detection is pattern-based. In the synthetic workbook, the "(Rs. lakhs)" title on the P&L sheet is not picked up, so those amounts load as rupees. The same figures from the synthetic PDF ("All amounts in Rs. lakhs") are scaled correctly.
- `--run-skills` on the CLI runs the tests on the raw tables. The app and the agent curate the data first.
- CSV files must be comma-separated.

## Repository layout

```
frontend/                   Streamlit app, pipeline runner, Agno agent
pipeline/                   table extraction (Docling / openpyxl / pandas, Mistral OCR), normaliser → DuckDB, CLI runners
skills/shared/              LightRAG setup, LLM registry and providers, preprocessors, agent toolkit, inspector, curator
skills/compliance-checker/  five-phase audit (scripts, SKILL.md, references/output_format.md)
skills/lightrag-query/      query CLI
skills/benfords-analysis/   ┐
skills/duplicate-detector/  │
skills/ratio-analyzer/      ├ forensic tests: scripts/ plus SKILL.md
skills/anomaly-detector/    │
skills/network-analyzer/    ┘
indian_financial_fraud_compliance_laws.json   law sections used by the audit
compliance-dataset/         alternative 17-category rule set built from ICAI/ICSI guidance (not wired
                            into the audit) and study notes on the Indian compliance landscape
schema/                     earlier relational schema (v1), kept for reference; not used by the pipeline
rag_chatbot.ipynb           index documents and chat with the knowledge-graph agent
model_config.yaml           provider and model for each role
tests/                      offline and live tests; fixtures/ holds the synthetic Acme Widgets documents
user_documents/             your own documents (git-ignored)
```

Licence: MIT — see LICENSE.
