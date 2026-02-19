---
name: lightrag-query
description: Query a LightRAG knowledge graph built from indexed financial documents
triggers:
  - query knowledge graph
  - search indexed documents
  - retrieve from RAG
  - lightrag query
---

# LightRAG Query Skill

Query an existing LightRAG knowledge graph using different retrieval modes.

## Query Modes

| Mode | Best For |
|---|---|
| `local` | Specific entity lookups (e.g. "What is ExampleCo's revenue?") |
| `global` | Broad summaries and cross-document themes |
| `hybrid` | Balanced — combines local entity + global theme retrieval |
| `mix` | All retrieval strategies merged |
| `naive` | Simple vector similarity (baseline) |

## Usage

### CLI

```bash
# Basic query
python skills/lightrag-query/scripts/query.py --query "What is ExampleCo's total revenue?"

# Choose mode + storage path
python skills/lightrag-query/scripts/query.py \
  --query "Who are the related parties?" \
  --mode hybrid \
  --storage ./rag_storage

# Context-only (raw retrieved chunks, no LLM synthesis)
python skills/lightrag-query/scripts/query.py \
  --query "CSR expenditure" \
  --context-only

# Save output to file
python skills/lightrag-query/scripts/query.py \
  --query "Board of Directors" \
  --output results.json
```

### Arguments

| Arg | Default | Description |
|---|---|---|
| `--query` | *(required)* | The query string |
| `--mode` | `hybrid` | Retrieval mode: local, global, hybrid, mix, naive |
| `--storage` | `./rag_storage` | Path to LightRAG storage directory |
| `--top-k` | `40` | Number of top results to retrieve |
| `--context-only` | `false` | Return raw context without LLM synthesis |
| `--output` | *(stdout)* | Write JSON output to this file |
