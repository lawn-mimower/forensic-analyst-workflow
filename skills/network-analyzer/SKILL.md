---
name: network-analyzer
description: Build entity relationship graphs from related-party data, detect communities, measure centrality, and find circular relationships
triggers:
  - network analysis
  - related party analysis
  - entity relationship graph
  - community detection
  - circular transactions
  - shell company detection
  - hub entity analysis
---

# Network Analyzer Skill

Builds an entity relationship graph from the `related_parties` DuckDB table, applies community detection (Louvain), centrality metrics, and cycle detection to reveal hidden connections and suspicious structures.

- **Pass 1 (Sweep):** Build full graph from all related parties, compute all metrics.
- **Pass 2 (Investigate):** Filter by relationship_category or transaction_type.

---

## When to Use

### Positive Triggers
- Related-party disclosures with multiple entities and relationships
- Vendor/counterparty data where shell company networks are suspected
- Any dataset with entity-to-entity relationships and transaction amounts
- When investigating tunneling, circular trading, or related-party abuse

### Negative Triggers
- Fewer than 3 entities (trivial graph)
- No related_parties table in the database
- Data without entity relationship information

---

## Analysis

### 1. Graph Construction
- Entities as nodes (party_name + related entities from relationships)
- Relationships as edges with type (relationship_type) and weight (transaction_amount)
- Directed graph when relationship direction is meaningful

### 2. Community Detection (Louvain)
Groups entities into communities/clusters. Entities in the same community transact more with each other than with outsiders. Useful for identifying:
- Corporate group structures
- Hidden subsidiary networks
- Transacting cliques

### 3. Centrality Metrics
| Metric | What It Reveals |
|---|---|
| Degree centrality | Entities connected to many others (hubs) |
| Betweenness centrality | Entities that bridge between groups (gatekeepers) |
| Closeness centrality | Entities that can reach all others quickly |

### 4. Circular Relationships
Detects cycles: A -> B -> C -> A. Circular transaction chains are a classic indicator of:
- Round-tripping (fictitious revenue)
- Layering (money laundering)
- Fund diversion through intermediaries

### 5. Hub Entities
Entities with degree significantly above average. High-degree hubs in related-party networks may be:
- Holding companies (legitimate)
- Shell entities used to route transactions (suspicious)

---

## Interpretation Guide

### Risk Scoring (1-10)
- **1-3:** Simple network, few connections, no cycles
- **4-5:** Moderate complexity, some hub entities
- **6-7:** Cycles detected or high-centrality non-obvious entities
- **8-10:** Complex circular structures or entities bridging unrelated groups

### Red Flags
| Pattern | Signal |
|---|---|
| Cycles involving 3+ entities | Possible round-tripping or circular trading |
| Entity with high betweenness but low degree | Gatekeeper entity routing funds between groups |
| Community with all transactions flowing one direction | Fund siphoning through a chain |
| Multiple entities sharing same relationship_category | Potential shell network |

### Natural Explanations
| Pattern | Explanation |
|---|---|
| Holding company has highest degree | Normal corporate group structure |
| Two communities connected by one entity | Common subsidiary between two groups |
| Small cycles in trading companies | Normal trading relationships |

---

## Script Usage

```bash
python skills/network-analyzer/scripts/network_analyzer.py \
  --db case.duckdb \
  --output results.json \
  [--filter "relationship_category = 'Subsidiary'"] \
  [--case-id CASE-001]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--db` | Yes | -- | Path to DuckDB database |
| `--output` | Yes | -- | Output JSON file path |
| `--table` | No | `related_parties` | Table or view to query (e.g. `curated_related_parties`) |
| `--filter` | No | -- | SQL WHERE clause for related_parties |
| `--case-id` | No | -- | Case identifier for audit trail |

---

## Cross-Reference with Other Skills

| This Skill Finds | Other Skill Finds | Combined Signal |
|---|---|---|
| Circular transaction chain A->B->C->A | Benford's failure on amounts in that chain | Round-tripping fraud |
| Hub entity with high betweenness | Duplicate detector finds duplicate amounts to/from hub | Hub is routing duplicated payments |
| Community of 5+ closely-connected entities | Ratio analyzer shows revenue from these entities | Related-party revenue inflation |
