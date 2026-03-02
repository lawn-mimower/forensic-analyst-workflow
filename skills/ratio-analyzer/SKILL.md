---
name: ratio-analyzer
description: Compute financial ratios from P&L and balance sheet data, compare across periods, and flag anomalous changes indicating potential manipulation
triggers:
  - financial ratio analysis
  - ratio analysis
  - margin analysis
  - profitability analysis
  - year over year comparison
  - trend analysis
  - expense ratio check
---

# Ratio Analyzer Skill

Computes financial ratios from line items by fuzzy-matching account names to standard Indian financial statement categories (Schedule III). Compares ratios across periods and flags anomalous changes.

- **Pass 1 (Sweep):** Compute all computable ratios, flag changes > 20% absolute or > 2 sigma.
- **Pass 2 (Investigate):** Re-run filtered by table_type or specific accounts.

---

## When to Use

### Positive Triggers
- P&L data with multiple periods (FY23 vs FY24)
- Balance sheet data with comparative periods
- Any financial statement data where trend analysis is meaningful
- When investigating potential revenue manipulation or expense suppression

### Negative Triggers
- Single-period data (no comparison possible)
- Transaction-level GL data (ratios need aggregated financial statements)
- Non-financial data

---

## Ratios Computed

### Profitability Ratios (from P&L)
| Ratio | Formula | Forensic Significance |
|---|---|---|
| Gross Margin | (Revenue - COGS) / Revenue | Sudden improvement may indicate COGS suppression |
| Operating Margin | Operating Profit / Revenue | Manipulation of operating expenses |
| Net Margin | PAT / Revenue | Overall earnings quality |
| Expense-to-Revenue | Each expense line / Revenue | Individual expense line manipulation |

### Liquidity Ratios (from Balance Sheet, if available)
| Ratio | Formula | Forensic Significance |
|---|---|---|
| Current Ratio | Current Assets / Current Liabilities | Sudden improvement may indicate liability suppression |

### Growth Metrics
| Metric | Formula | Forensic Significance |
|---|---|---|
| YoY Growth | (Current - Prior) / Prior | Per-line-item growth; extreme values flag manipulation |

---

## Account Name Matching

Uses `rapidfuzz.fuzz.token_sort_ratio` to match raw account names to ~30 standard Indian financial statement categories. Matching is logged for audit trail.

Example mappings:
- "Revenue from operations" -> revenue
- "Cost of materials consumed" -> cogs
- "Employee benefits expense" -> employee_expense
- "Profit before tax" -> pbt
- "Profit after tax" / "Net profit" -> pat

---

## Interpretation Guide

### Risk Scoring (1-10)
- **1-3:** All ratios within normal ranges; changes are modest
- **4-5:** Some ratios show notable changes; document for review
- **6-7:** Significant ratio movements or contradictory trends; investigate
- **8-10:** Extreme movements or impossible ratio combinations; escalation required

### Red Flags
| Pattern | Signal |
|---|---|
| Gross margin improving while revenue declining | Possible COGS manipulation |
| Operating margin improving via expense reduction in one category | Expense may be reclassified or suppressed |
| Revenue growth >30% with no corresponding asset growth | Fictitious revenue |
| All expense ratios stable except one | Targeted manipulation of that expense line |

### Natural Explanations
| Pattern | Explanation |
|---|---|
| Margin improvement with genuine revenue growth | Operating leverage -- fixed costs spread over more revenue |
| Expense ratio jump in one year | One-off items (impairment, restructuring) |
| Revenue decline with stable margins | Price increases offsetting volume decline |

---

## Script Usage

```bash
python skills/ratio-analyzer/scripts/ratio_analyzer.py \
  --db case.duckdb \
  --output results.json \
  [--table line_items] \
  [--filter "NOT is_total"] \
  [--change-threshold 0.20] \
  [--case-id CASE-001]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--db` | Yes | -- | Path to DuckDB database |
| `--output` | Yes | -- | Output JSON file path |
| `--table` | No | `line_items` | Table to analyze |
| `--filter` | No | -- | SQL WHERE clause |
| `--change-threshold` | No | `0.20` | Flag ratio changes above this absolute threshold |
| `--case-id` | No | -- | Case identifier for audit trail |

---

## Cross-Reference with Other Skills

| This Skill Finds | Other Skill Finds | Combined Signal |
|---|---|---|
| Margin improvement despite flat revenue | Benford's failure on expense amounts | Expense manipulation likely |
| Revenue growth >30% | Network analyzer shows new related parties | Related-party revenue inflation |
| Single expense line spike | Duplicate detector finds duplicates in that line | Double-booking in one category |
