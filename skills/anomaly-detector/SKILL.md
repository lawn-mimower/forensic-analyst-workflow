---
name: anomaly-detector
description: Statistical outlier detection on financial line items using IQR, Z-score, and Isolation Forest methods with consensus flagging
triggers:
  - anomaly detection
  - outlier detection
  - statistical outliers
  - unusual amounts
  - find anomalies
  - detect outliers
---

# Anomaly Detector Skill

Runs unsupervised statistical anomaly detection on numeric financial data using three complementary methods: IQR, Z-score, and Isolation Forest. Items flagged by 2+ methods are considered high-confidence anomalies.

- **Pass 1 (Sweep):** Run all methods on full dataset, flag consensus anomalies.
- **Pass 2 (Investigate):** Re-run filtered by table_type, period, or account pattern.

---

## When to Use

### Positive Triggers
- Line item amounts where you need to identify statistical outliers
- P&L or BS data where one or two items may be manipulated
- Any numeric column where extreme values need flagging
- Post-Benford's analysis to identify the specific items driving non-conformity

### Negative Triggers
- Datasets with fewer than 20 records (insufficient for statistical methods)
- Data where extreme values are expected (e.g., total rows alongside detail rows)
- Categorical data

---

## Methods

### 1. IQR (Interquartile Range)
Flags values outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]. Robust to extreme outliers. Best for detecting values far from the central distribution.

### 2. Z-Score
Flags values with |Z| > 3 (more than 3 standard deviations from mean). Sensitive to the distribution shape. Best when data is roughly normal.

### 3. Isolation Forest (PyOD)
Ensemble tree-based method that isolates anomalies by random partitioning. Works on feature matrix: [amount, log10(|amount|+1), is_negative, row_position]. Catches multivariate anomalies that univariate methods miss.

### Consensus
An item is flagged as a high-confidence anomaly if >= 2 of 3 methods agree. This reduces false positives while catching true outliers.

---

## Interpretation Guide

### Risk Scoring (1-10)
- **1-3:** Few or no consensus anomalies; data distribution is clean
- **4-5:** Some outliers detected; review individually
- **6-7:** Multiple consensus anomalies or anomalies concentrated in one area
- **8-10:** Extreme outliers or systematic anomaly pattern; investigate

### Per-Method Interpretation
| Method | Flags | Likely Meaning |
|---|---|---|
| IQR only | Moderate outlier | Value is unusual but not extreme |
| Z-score only | Distribution tail | Value is far from mean but distribution is skewed |
| IForest only | Multivariate anomaly | Value's feature combination is unusual |
| IQR + Z-score | Strong univariate outlier | Value is clearly extreme |
| All three | Very strong anomaly | Multiple evidence streams agree |

### Red Flags
| Pattern | Signal |
|---|---|
| Single large item flagged by all methods | Potential fabricated large transaction |
| Cluster of anomalies in one table_type | Systematic issue in that financial statement section |
| Anomalies concentrated in one period | Period-specific manipulation |
| Negative anomalies (unusually small) | Possible suppression of amounts |

---

## Script Usage

```bash
python skills/anomaly-detector/scripts/anomaly_detector.py \
  --db case.duckdb \
  --table line_items \
  --column amount \
  --output results.json \
  [--filter "NOT is_total"] \
  [--contamination 0.05] \
  [--case-id CASE-001]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--db` | Yes | -- | Path to DuckDB database |
| `--output` | Yes | -- | Output JSON file path |
| `--table` | No | `line_items` | Table to analyze |
| `--column` | No | `amount` | Numeric column to analyze |
| `--filter` | No | -- | SQL WHERE clause |
| `--contamination` | No | `0.05` | Expected proportion of outliers for IForest |
| `--case-id` | No | -- | Case identifier for audit trail |

---

## Cross-Reference with Other Skills

| This Skill Finds | Other Skill Finds | Combined Signal |
|---|---|---|
| Large positive outlier in expenses | Ratio analyzer shows expense spike | Investigate the specific expense |
| Outlier concentrated in one vendor | Benford's failure on vendor payments | Vendor fraud likely |
| Negative outlier (suppressed amount) | Ratio analyzer shows improving margins | Amount suppression to inflate profits |
