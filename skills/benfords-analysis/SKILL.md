---
name: benfords-analysis
description: Apply Benford's Law digit-frequency analysis to financial datasets to detect potential manipulation, fabrication, or anomalous patterns in numeric data
triggers:
  - run benfords law analysis
  - benford's law test
  - digit frequency analysis
  - check for fabricated numbers
  - number manipulation detection
  - benford analysis
  - digit distribution test
---

# Benford's Law Analysis Skill

Applies Benford's Law (First Digit Law) to financial datasets stored in DuckDB. Benford's Law states that in naturally occurring datasets, the leading digit is more likely to be small: ~30.1% of numbers start with 1, ~17.6% with 2, declining to ~4.6% for 9. Deviations from this distribution can signal fabrication, manipulation, or systemic behavioral patterns.

This skill supports first-digit, second-digit, first-two-digit, last-two-digit, and summation tests, each revealing different aspects of data integrity.

---

## When to Use

### Positive Triggers (Benford's IS Applicable)

- **Vendor payment ledgers** -- payments to external parties follow Benford's well because they span multiple orders of magnitude
- **Expense claims and reimbursements** -- employee-submitted amounts are a classic manipulation target
- **Journal entry amounts** -- especially manual journal entries, which bypass systematic controls
- **Revenue line items** -- sales invoices, revenue recognition entries
- **Accounts payable / receivable ageing buckets** -- outstanding amounts across many counterparties
- **Line item amounts** (table: `line_items`, or the `curated_line_items` view after curation; column: `amount` or `amount_inr`) -- everything the pipeline extracts, including general-ledger extracts, lands in this table; the workbench has no separate transactions table
- **Any dataset that spans at least two orders of magnitude and arises from a multiplicative process**

### Negative Triggers (Benford's is NOT Applicable)

Do NOT run Benford's analysis on:

- **Datasets with fewer than 100 records** -- insufficient statistical power; results will be unreliable
- **Assigned numbers** -- invoice numbers, cheque numbers, employee IDs, PAN numbers, journal numbers, entity IDs
- **Dates or date components** -- transaction_date, posting_date, period columns
- **Categorical codes** -- account_code, journal_type, flag_type, entity_type
- **Percentages** -- ownership_pct, confidence scores, variance_pct (bounded distributions)
- **Rates** -- exchange_rate, interest rates (narrow-range distributions)
- **Rounded budget/estimate figures** -- approved budget allocations often cluster by design
- **Datasets where values are constrained to a narrow range** (e.g., all values between 1000 and 9999)
- **Tax rates, GST rates, TDS rates** -- fixed by statute, not naturally distributed

---

## Interpretation Guide

### Statistical Measures Computed

Each test produces four complementary statistical measures:

| Measure | What It Tests | Primary/Secondary |
|---|---|---|
| **MAD (Mean Absolute Deviation)** | Average deviation of observed from expected frequencies | **Primary** -- used for conformity verdict |
| **Chi-squared test** | Whether observed distribution differs significantly from expected | Secondary -- confirms MAD finding |
| **KS test (Kolmogorov-Smirnov)** | Maximum cumulative deviation between observed and expected | Secondary -- sensitive to systematic shifts |
| **Z-score per digit** | Which specific digits deviate significantly | Diagnostic -- pinpoints the anomaly |

### MAD Conformity Thresholds (Nigrini's Standards)

The verdicts are based on Mark Nigrini's published Mean Absolute Deviation thresholds. See `references/nigrini_thresholds.md` for full details.

**First-digit test:**

| MAD Range | Conformity Level |
|---|---|
| 0.000 -- 0.006 | CLOSE_CONFORMITY |
| 0.006 -- 0.012 | ACCEPTABLE_CONFORMITY |
| 0.012 -- 0.015 | MARGINALLY_ACCEPTABLE |
| > 0.015 | NON_CONFORMING |

**First-two-digit test:**

| MAD Range | Conformity Level |
|---|---|
| 0.000 -- 0.0012 | CLOSE_CONFORMITY |
| 0.0012 -- 0.0018 | ACCEPTABLE_CONFORMITY |
| 0.0018 -- 0.0022 | MARGINALLY_ACCEPTABLE |
| > 0.0022 | NON_CONFORMING |

**Second-digit test:**

| MAD Range | Conformity Level |
|---|---|
| 0.000 -- 0.008 | CLOSE_CONFORMITY |
| 0.008 -- 0.010 | ACCEPTABLE_CONFORMITY |
| 0.010 -- 0.012 | MARGINALLY_ACCEPTABLE |
| > 0.012 | NON_CONFORMING |

### What Each Test Reveals

**First-digit test** -- Broad manipulation screening. The coarsest test (only 9 buckets). If this fails, something significant is happening. Best for initial sweep.

**First-two-digit test** -- More granular (90 buckets: 10-99). Identifies the specific numeric ranges where manipulation concentrates. If first-digit passes but first-two-digit fails, the manipulation is subtle and confined to a narrow range (e.g., an excess of amounts starting with "49" could indicate clustering just below a 50,000 threshold).

**Second-digit test** -- Sensitive to rounding and estimation. Humans tend to use 0 and 5 as second digits when fabricating numbers. An excess of second-digit 0 strongly suggests round-number fabrication. An excess of second-digit 5 suggests estimation or approximation.

**Last-two-digit test** -- Detects round-number fabrication. In natural data, the last two digits should be approximately uniformly distributed (each of 00-99 appearing ~1%). Spikes at "00" indicate round-number fabrication. Spikes at "50" indicate half-rounding. Spikes at "99" may indicate just-below pricing strategies.

**Summation test** -- Identifies digit combinations that carry disproportionate monetary value. Even if frequency looks normal, if 90% of the total dollar value concentrates in amounts starting with "48" or "49", this signals large transactions clustered in that range. Each first-two-digit group should carry approximately 1/90 (~1.11%) of the total value.

### Overall Verdict Logic

The overall verdict is the **worst** verdict across all tests run:

| Verdict | Meaning |
|---|---|
| CONFORMING | All tests show CLOSE or ACCEPTABLE conformity |
| MARGINALLY_NON_CONFORMING | At least one test shows MARGINALLY_ACCEPTABLE |
| NON_CONFORMING | At least one test shows NON_CONFORMING |
| ANOMALOUS | Multiple tests fail, or single test with extreme deviation (risk score >= 8) |

Risk score (1-10) is a composite:
- 1-3: Conforming, no action needed
- 4-5: Minor deviations, may warrant documentation
- 6-7: Significant deviations, investigation recommended
- 8-10: Strong statistical evidence of non-natural distribution, escalation required

### How to Read the Output JSON

The output file contains:

- `meta` -- Dataset metadata: record counts, filters applied, case ID for audit trail
- `tests` -- Per-test results: observed/expected distributions, all statistics, verdict
- `tests.*.flagged_digits` -- Specific digits or digit-pairs where Z-score > 1.96 (95% significance)
- `overall_verdict` -- Worst-case across all tests
- `overall_risk_score` -- 1-10 composite score
- `flagged_ranges` -- Human-readable list of suspicious digit ranges
- `investigation_suggestions` -- Automated follow-up recommendations based on statistical patterns

---

## Red Flags and Natural Explanations

### Patterns That Indicate Fraud

| Pattern | Likely Explanation |
|---|---|
| First-digit passes but first-two-digit fails in specific range | Manipulation clustered in a narrow amount range (e.g., amounts fabricated to stay below an approval threshold) |
| Last-two-digit shows massive "00" spike (>5x expected) | Round-number fabrication -- amounts invented rather than arising from genuine transactions |
| Second-digit excess of 0 and 5 | Numbers are being estimated or invented, not recorded from real transactions |
| Summation test shows value concentration despite normal frequencies | A few large fabricated transactions dominate value -- frequency looks normal because they are few, but they carry enormous monetary weight |
| First-digit excess of 1 combined with deficit of 8 and 9 | Classic "conservative fabrication" -- fabricator knows amounts should start with lower digits but overcorrects |
| Consistent non-conformity across ALL tests | Systemic data integrity issue -- the entire dataset may be fabricated or systematically manipulated |

### Patterns with Natural Business Explanations

| Pattern | Likely Explanation |
|---|---|
| Last-two-digit "00" spike in salary data | Salaries are negotiated in round numbers -- not fraud |
| First-two-digit spike at "50" in expense data | Expenses clustered near INR 50,000 may reflect genuine approval thresholds, not manipulation. Verify against delegation of authority matrix |
| March (Q4) data deviates but other quarters conform | Fiscal year-end effects: accruals, provisions, true-ups cause natural distortion |
| Small dataset (100-200 records) shows marginal deviation | Reduced statistical power. Type I error (false positive) risk is elevated. Document as "inconclusive -- insufficient sample size" |
| Rental payments fail Benford's | Rent is contractually fixed -- same amount repeats monthly. This is expected behavior, not fraud |
| Depreciation entries fail Benford's | Straight-line depreciation produces repeated calculated amounts -- expected |

---

## Investigation Guide (Pass 2)

### When to Re-run with Filters

After Pass 1 sweep, if any test is NON_CONFORMING or has risk score >= 6, the following re-runs are recommended:

1. **Filter by account** -- Isolate a single account or expense head. One manipulated account can poison the entire distribution.
   ```bash
   python skills/benfords-analysis/scripts/benfords.py --db case.duckdb --table line_items --column amount \
     --filter "account_name = 'Professional fees'" --tests all --min-records 50 --output rerun_account.json
   ```

2. **Filter by period** -- Test each period separately. If only one year deviates, look at what changed in that year.
   ```bash
   python skills/benfords-analysis/scripts/benfords.py --db case.duckdb --table line_items --column amount \
     --filter "period_label = 'FY 2024-25'" --tests first_two --output rerun_period.json
   ```

3. **Filter by account category** -- Separate expenses from revenue. If only expenses deviate, focus investigation there.
   ```bash
   python skills/benfords-analysis/scripts/benfords.py --db case.duckdb --table line_items --column amount_inr \
     --filter "account_name ILIKE '%expense%'" --tests all --output rerun_expenses.json
   ```

4. **Exclude totals and comparatives** -- Subtotals and prior-year comparatives repeat other numbers and distort the digit distribution.
   ```bash
   python skills/benfords-analysis/scripts/benfords.py --db case.duckdb --table line_items --column amount \
     --filter "NOT is_total AND NOT is_comparative" --tests first_digit,first_two --output rerun_detail.json
   ```

5. **Filter by amount range** -- If first-two-digit flagged digits 48-50, re-run on amounts in that range for deeper analysis.

### When to Re-run with Different Tests

| Pass 1 Finding | Recommended Pass 2 Action |
|---|---|
| First-digit fails | ALWAYS follow up with first-two-digit to pinpoint the range |
| First-two-digit fails for digits 48-50 | Run last-two-digit test on amounts 48000-50999 to check for rounding |
| Last-two-digit shows "00" spike | Run summation test to quantify the monetary impact |
| Summation test shows value concentration | Filter to the concentrated digit range and run all tests |
| All tests pass | No re-run needed. Document as clean baseline |

### Cross-Reference with Other Skills

**Critical combinations that warrant escalation:**

| This Skill Finds | Other Skill Finds | Combined Signal |
|---|---|---|
| Benford's failure on vendor payments | `duplicate-detector` finds duplicate amounts for same vendor | **ESCALATE** -- potential duplicate payment fraud |
| Benford's failure on expenses | `ratio-analyzer` shows improving margins despite revenue decline | **Potential expense suppression** -- expenses being understated |
| Benford's second-digit 0/5 excess | `duplicate-detector` reports a high round-number concentration | **Fabrication signal** -- numbers being invented |
| Benford's failure concentrated in a few accounts | `anomaly-detector` flags outliers in the same accounts | **Investigate those accounts first** |

### Indian-Specific Context

See `references/indian_thresholds.md` for comprehensive threshold documentation.

**Common approval thresholds that cause natural Benford's deviations:**
- INR 50,000 -- typical petty cash / manager approval limit
- INR 1,00,000 -- senior manager / department head limit
- INR 5,00,000 -- VP / divisional head limit
- INR 10,00,000 -- director / board committee limit
- INR 1,00,00,000 -- full board approval limit

**TDS thresholds that cause behavioral clustering:**
- INR 30,000 (Section 194C) -- single contract payment TDS threshold
- INR 50,000 (Section 194J) -- professional fees TDS threshold per payee per year
- INR 2,50,000 (Section 194I) -- rent TDS threshold per payee per year
- Vendors/payees may structure invoices to stay below these thresholds to avoid TDS withholding

**GST thresholds:**
- INR 20,00,000 -- GST registration threshold (INR 10,00,000 for special category states)
- INR 5,00,00,000 -- e-invoicing threshold
- Businesses near these thresholds may suppress revenue to stay below them

**Fiscal year-end effect:**
- March transactions may naturally deviate due to: year-end provisions, accrual reversals, advance billing, inventory adjustments, tax-planning transactions
- Always test Q4 separately before concluding fraud

---

## Script Usage

### CLI Interface

```bash
python skills/benfords-analysis/scripts/benfords.py [OPTIONS]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--db` | Yes | -- | Path to DuckDB database file |
| `--table` | No | `transactions` | Table name to analyze. The workbench has no `transactions` table, so pass `--table line_items` (or `curated_line_items`) |
| `--column` | No | `amount` | Numeric column to test |
| `--tests` | No | `all` | Comma-separated: `first_digit`, `second_digit`, `first_two`, `last_two`, `summation`, `all` |
| `--filter` | No | -- | SQL WHERE clause to filter data |
| `--min-records` | No | `100` | Minimum records required for valid analysis |
| `--output` | Yes | -- | Output JSON file path |
| `--significance` | No | `0.05` | Significance level for hypothesis tests |
| `--case-id` | No | -- | Case identifier for audit trail |

### Pass 1 (Sweep) -- Default Invocation

```bash
# Sweep on extracted line items (what the pipeline runs)
python skills/benfords-analysis/scripts/benfords.py \
  --db pipeline/test_output/test_forensic.duckdb \
  --table line_items \
  --column amount \
  --tests all \
  --output skills/benfords-analysis/outputs/sweep.json \
  --case-id "CASE-001"

# Same, without subtotals
python skills/benfords-analysis/scripts/benfords.py \
  --db pipeline/test_output/test_forensic.duckdb \
  --table line_items \
  --column amount_inr \
  --tests all \
  --filter "NOT is_total" \
  --output skills/benfords-analysis/outputs/sweep_nontotal.json \
  --case-id "CASE-001"
```

### Pass 2 (Investigation) -- Targeted Re-runs

```bash
# First-two and last-two digit tests for one period only
python skills/benfords-analysis/scripts/benfords.py \
  --db pipeline/test_output/test_forensic.duckdb \
  --table line_items \
  --column amount \
  --tests first_two,last_two \
  --filter "period_label = 'FY 2024-25' AND NOT is_total" \
  --output skills/benfords-analysis/outputs/rerun_period.json \
  --case-id "CASE-001"

# Focus on amounts near the INR 50,000 threshold
python skills/benfords-analysis/scripts/benfords.py \
  --db pipeline/test_output/test_forensic.duckdb \
  --table line_items \
  --column amount_inr \
  --tests first_two,last_two,summation \
  --filter "amount_inr BETWEEN 40000 AND 55000" \
  --min-records 50 \
  --output skills/benfords-analysis/outputs/rerun_50k_threshold.json \
  --case-id "CASE-001"
```

### Output JSON Schema

See the `tests` object within the output for per-test results. Each test contains:

```json
{
  "observed": {"1": 0.301, "2": 0.176, ...},
  "expected": {"1": 0.301, "2": 0.176, ...},
  "chi_squared": 12.34,
  "chi_squared_critical": 15.51,
  "p_value": 0.137,
  "ks_statistic": 0.023,
  "ks_p_value": 0.89,
  "mad": 0.004,
  "mad_conformity": "CLOSE_CONFORMITY",
  "verdict": "CONFORMING",
  "flagged_digits": [
    {"digit": "7", "observed": 0.089, "expected": 0.058, "z_score": 2.34, "direction": "excess"}
  ]
}
```

Top-level fields:
- `meta` -- Audit trail: case ID, timestamp, data provenance, record counts
- `tests` -- Per-test statistical results and verdicts
- `overall_verdict` -- Worst-case verdict across all tests
- `overall_risk_score` -- 1-10 composite risk score
- `flagged_ranges` -- Human-readable list of suspicious digit ranges with context
- `investigation_suggestions` -- Automated follow-up recommendations

---

## Few-Shot Examples

### Example 1: First-Two-Digit Anomaly on Vendor Payments

**Pass 1 sweep result:**
- `first_digit`: CONFORMING (MAD = 0.005, p = 0.42)
- `first_two_digit`: NON_CONFORMING (MAD = 0.0028, p = 0.003)
- Flagged digits: 49 (Z = 3.1, excess), 50 (Z = 2.4, excess)
- `last_two_digit`: CONFORMING
- `overall_verdict`: NON_CONFORMING, risk_score = 7

**Agent reasoning:** First-digit passes but first-two-digit fails specifically at digits 49-50. This pattern is consistent with amounts being structured near INR 50,000 (a common Indian approval threshold). The fact that last-two-digit is clean means the amounts themselves are not round numbers -- they are just clustered in the 49,000-50,999 range. This requires investigation.

**Pass 2 action:** Re-run with filter on payment amounts 45,000-55,000, then cross-reference with the delegation of authority matrix to identify the approval threshold at play. Also filter by the specific vendors receiving these payments.

### Example 2: Clean Sweep -- All Tests Conforming

**Pass 1 sweep result:**
- All five tests: CONFORMING
- MAD values all within CLOSE or ACCEPTABLE ranges
- No flagged digits
- `overall_verdict`: CONFORMING, risk_score = 2

**Agent reasoning:** The dataset conforms to Benford's Law across all digit positions. This does not prove the absence of fraud (a sophisticated manipulator can maintain Benford's conformity), but it means there is no statistical basis for digit-frequency-based suspicion. Document as clean baseline.

**Pass 2 action:** No re-run needed. Record the clean result in the case file.

### Example 3: Last-Two-Digit Round-Number Pattern

**Pass 1 sweep result:**
- `first_digit`: CONFORMING (MAD = 0.004)
- `second_digit`: MARGINALLY_ACCEPTABLE (MAD = 0.011, excess at digit 0)
- `last_two_digit`: NON_CONFORMING -- "00" at 4.2% vs expected 1.0%, "50" at 2.8% vs expected 1.0%
- `overall_verdict`: NON_CONFORMING, risk_score = 6

**Agent reasoning:** The first-digit distribution looks natural, but the last-two-digit test reveals significant round-number bias. 4.2% of amounts end in "00" (expected: 1%). Combined with second-digit excess at 0, this suggests many amounts are being recorded as round numbers. This could indicate: (a) legitimate round-number contracts/salaries, (b) estimates being recorded as actuals, or (c) fabricated amounts. Need to determine if the round numbers cluster in specific accounts.

**Pass 2 action:** Re-run filtering by account type (expense accounts only, then revenue only) to isolate where the rounding occurs. Cross-reference with the round-number concentration reported by `duplicate-detector`. Check if the round-number entries are manual journal entries vs. system-generated.
