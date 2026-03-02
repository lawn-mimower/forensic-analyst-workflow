---
name: duplicate-detector
description: Detect duplicate, near-duplicate, and suspiciously similar line items in financial data to identify potential double-booking, copy-paste fraud, or data entry errors
triggers:
  - find duplicate entries
  - duplicate detection
  - duplicate payments
  - check for duplicates
  - near-duplicate analysis
  - round number analysis
  - double booking detection
---

# Duplicate Detector Skill

Identifies exact, near-amount, fuzzy-name, and cross-period duplicate line items in DuckDB financial data. Also flags round-number concentration. Designed for the two-pass forensic workflow:

- **Pass 1 (Sweep):** Run all tests with defaults on full dataset.
- **Pass 2 (Investigate):** Re-run with filters (by table_type, period, account pattern).

---

## When to Use

### Positive Triggers
- Financial statement line items with multiple periods (FY23 vs FY24)
- Vendor payment ledgers where double-payment fraud is suspected
- Expense data where copy-paste fabrication may occur
- Any dataset where the same account_name + amount should not appear more than once

### Negative Triggers
- Datasets with fewer than 10 records
- Transaction-level data where repeated amounts are expected (e.g., monthly rent)
- GL journals where the same amount appears as debit and credit (normal double-entry)

---

## Tests

### 1. Exact Duplicates
Same account_name + same amount + same period_label. Flags data entry errors or copy-paste.

### 2. Near-Amount Duplicates
Same account_name, amounts within configurable tolerance (default ±1%). Catches slightly-modified duplicate entries.

### 3. Fuzzy-Name Duplicates
Different account_name but rapidfuzz token_sort_ratio >= 85, same amount. Catches renamed-but-identical entries (e.g., "Employee Benefits" vs "Employee Benefit Expense").

### 4. Cross-Period Duplicates
Same account_name + same amount across different period_labels. Normal for recurring items, but flags potential carry-forward errors.

### 5. Round-Number Concentration
Percentage of amounts ending in 000, 00, 50, 0. High concentration suggests estimation or fabrication.

---

## Interpretation Guide

### Risk Scoring (1-10)
- **1-3:** Few or no duplicates found; normal data patterns
- **4-5:** Some near-duplicates or moderate round-number concentration; worth reviewing
- **6-7:** Multiple exact duplicates or high fuzzy matches; investigation recommended
- **8-10:** Systematic duplication pattern or extreme round-number concentration; escalation required

### Red Flags
| Pattern | Signal |
|---|---|
| Exact duplicates within same period and table | Data entry error or intentional double-booking |
| Fuzzy matches with amounts >1 lakh | Renamed line items to hide duplication |
| Cross-period exact matches on non-recurring items | Copy-paste from prior year |
| Round-number concentration >40% | Estimates recorded as actuals, or fabricated amounts |

### Natural Explanations
| Pattern | Explanation |
|---|---|
| Cross-period exact matches on depreciation | Straight-line depreciation produces same amount each year |
| Round numbers in salary/rent | Contractually fixed round amounts |
| Same amount, different accounts | Legitimate reclassification entries |

---

## Script Usage

```bash
python skills/duplicate-detector/scripts/duplicate_detector.py \
  --db case.duckdb \
  --output results.json \
  [--table line_items] \
  [--filter "NOT is_total"] \
  [--tolerance 0.01] \
  [--fuzzy-threshold 85] \
  [--case-id CASE-001]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--db` | Yes | -- | Path to DuckDB database |
| `--output` | Yes | -- | Output JSON file path |
| `--table` | No | `line_items` | Table to analyze |
| `--filter` | No | -- | SQL WHERE clause |
| `--tolerance` | No | `0.01` | Near-amount tolerance (fraction) |
| `--fuzzy-threshold` | No | `85` | Minimum rapidfuzz score for fuzzy match |
| `--case-id` | No | -- | Case identifier for audit trail |

---

## Cross-Reference with Other Skills

| This Skill Finds | Other Skill Finds | Combined Signal |
|---|---|---|
| Exact duplicates on vendor payments | Benford's failure on same amounts | **ESCALATE** -- duplicate payment fraud |
| Round-number concentration >50% | Anomaly detector flags same items | Fabricated data likely |
| Cross-period exact matches | Ratio analyzer shows flat margins | Lazy copy-paste from prior year financials |
