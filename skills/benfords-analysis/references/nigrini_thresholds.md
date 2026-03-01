# Nigrini's Benford's Law Conformity Thresholds

Reference: Mark J. Nigrini, *Benford's Law: Applications for Forensic Accounting, Auditing, and Fraud Detection* (Wiley, 2012).

This document provides the authoritative statistical thresholds and mathematical foundations used by the `benfords-analysis` skill.

---

## 1. The Mathematical Foundation

### Benford's Law (Newcomb-Benford Law)

For a dataset arising from a naturally occurring multiplicative process spanning multiple orders of magnitude, the probability that the first significant digit is `d` is:

```
P(d) = log10(1 + 1/d)    for d in {1, 2, 3, ..., 9}
```

Generalised for the first two digits `dd` (10 through 99):

```
P(dd) = log10(1 + 1/dd)   for dd in {10, 11, 12, ..., 99}
```

For the second digit `d2` (0 through 9):

```
P(d2) = SUM over d1=1..9 of log10(1 + 1/(10*d1 + d2))
```

For the last two digits in naturally occurring data, the distribution is approximately uniform:

```
P(last two = dd) ~ 1/100 = 0.01    for dd in {00, 01, ..., 99}
```

---

## 2. Expected Distributions

### First-Digit Distribution

| Digit | Expected Probability |
|-------|---------------------|
| 1     | 0.30103             |
| 2     | 0.17609             |
| 3     | 0.12494             |
| 4     | 0.09691             |
| 5     | 0.07918             |
| 6     | 0.06695             |
| 7     | 0.05799             |
| 8     | 0.05115             |
| 9     | 0.04576             |

### Second-Digit Distribution

| Digit | Expected Probability |
|-------|---------------------|
| 0     | 0.11968             |
| 1     | 0.11389             |
| 2     | 0.10882             |
| 3     | 0.10433             |
| 4     | 0.10031             |
| 5     | 0.09668             |
| 6     | 0.09337             |
| 7     | 0.09035             |
| 8     | 0.08757             |
| 9     | 0.08500             |

### First-Two-Digit Distribution

The probabilities follow `P(dd) = log10(1 + 1/dd)`:

| Digits | Probability | Digits | Probability | Digits | Probability |
|--------|-------------|--------|-------------|--------|-------------|
| 10     | 0.04139     | 40     | 0.01075     | 70     | 0.00621     |
| 11     | 0.03779     | 41     | 0.01047     | 71     | 0.00612     |
| 12     | 0.03476     | 42     | 0.01020     | 72     | 0.00604     |
| 13     | 0.03218     | 43     | 0.00995     | 73     | 0.00595     |
| 14     | 0.02996     | 44     | 0.00970     | 74     | 0.00587     |
| 15     | 0.02803     | 45     | 0.00947     | 75     | 0.00580     |
| 16     | 0.02633     | 46     | 0.00925     | 76     | 0.00572     |
| 17     | 0.02482     | 47     | 0.00904     | 77     | 0.00564     |
| 18     | 0.02348     | 48     | 0.00884     | 78     | 0.00557     |
| 19     | 0.02228     | 49     | 0.00864     | 79     | 0.00550     |
| 20     | 0.02119     | 50     | 0.00846     | 80     | 0.00543     |
| 21     | 0.02019     | 51     | 0.00828     | 81     | 0.00537     |
| 22     | 0.01926     | 52     | 0.00811     | 82     | 0.00530     |
| 23     | 0.01841     | 53     | 0.00795     | 83     | 0.00524     |
| 24     | 0.01761     | 54     | 0.00780     | 84     | 0.00518     |
| 25     | 0.01688     | 55     | 0.00765     | 85     | 0.00512     |
| 26     | 0.01619     | 56     | 0.00751     | 86     | 0.00506     |
| 27     | 0.01554     | 57     | 0.00738     | 87     | 0.00500     |
| 28     | 0.01494     | 58     | 0.00725     | 88     | 0.00494     |
| 29     | 0.01438     | 59     | 0.00712     | 89     | 0.00489     |
| 30     | 0.01385     | 60     | 0.00700     | 90     | 0.00484     |
| 31     | 0.01336     | 61     | 0.00689     | 91     | 0.00478     |
| 32     | 0.01289     | 62     | 0.00678     | 92     | 0.00473     |
| 33     | 0.01245     | 63     | 0.00667     | 93     | 0.00468     |
| 34     | 0.01204     | 64     | 0.00656     | 94     | 0.00463     |
| 35     | 0.01165     | 65     | 0.00646     | 95     | 0.00458     |
| 36     | 0.01128     | 66     | 0.00637     | 96     | 0.00453     |
| 37     | 0.01093     | 67     | 0.00627     | 97     | 0.00449     |
| 38     | 0.01059     | 68     | 0.00618     | 98     | 0.00444     |
| 39     | 0.01028     | 69     | 0.00609     | 99     | 0.00439     |

### Last-Two-Digit Distribution

Uniform: each of the 100 combinations (00-99) has an expected probability of 0.01 (1.0%).

---

## 3. Mean Absolute Deviation (MAD) Conformity Thresholds

MAD is Nigrini's recommended primary conformity measure. It is more robust than chi-squared for Benford's analysis because chi-squared is overly sensitive with large sample sizes (leading to Type I errors at N > 10,000).

### Definition

```
MAD = (1/K) * SUM(i=1..K) |Observed_i - Expected_i|
```

Where K is the number of digit categories (9 for first-digit, 10 for second-digit, 90 for first-two-digit).

### First-Digit Test Thresholds (K = 9)

| MAD Range       | Conformity Level       | Interpretation                                      |
|-----------------|------------------------|-----------------------------------------------------|
| 0.000 -- 0.006  | Close Conformity       | Excellent fit; no concerns                          |
| 0.006 -- 0.012  | Acceptable Conformity  | Minor deviations within normal variation             |
| 0.012 -- 0.015  | Marginally Acceptable  | Noticeable deviations; warrants documentation        |
| > 0.015         | Non-Conforming         | Significant deviation; investigation recommended     |

### Second-Digit Test Thresholds (K = 10)

| MAD Range       | Conformity Level       | Interpretation                                      |
|-----------------|------------------------|-----------------------------------------------------|
| 0.000 -- 0.008  | Close Conformity       | Excellent fit                                        |
| 0.008 -- 0.010  | Acceptable Conformity  | Normal variation                                     |
| 0.010 -- 0.012  | Marginally Acceptable  | Warrants documentation                               |
| > 0.012         | Non-Conforming         | Investigation recommended                            |

### First-Two-Digit Test Thresholds (K = 90)

| MAD Range        | Conformity Level       | Interpretation                                      |
|------------------|------------------------|-----------------------------------------------------|
| 0.000 -- 0.0012  | Close Conformity       | Excellent fit                                        |
| 0.0012 -- 0.0018 | Acceptable Conformity  | Normal variation                                     |
| 0.0018 -- 0.0022 | Marginally Acceptable  | Warrants documentation                               |
| > 0.0022         | Non-Conforming         | Investigation recommended                            |

---

## 4. Supplementary Statistical Tests

### Chi-Squared Goodness-of-Fit Test

```
chi2 = SUM(i=1..K) (Observed_count_i - Expected_count_i)^2 / Expected_count_i
```

- Degrees of freedom: K - 1
- Reject null hypothesis (data follows Benford's) if chi2 > chi2_critical at chosen significance level
- **Caution:** chi-squared is highly sensitive to sample size. At N > 10,000, even trivially small deviations produce statistically significant results. This is why MAD is preferred as the primary measure.

Critical values at common significance levels (first-digit test, df = 8):

| Significance | Critical Value |
|-------------|----------------|
| 0.10        | 13.362         |
| 0.05        | 15.507         |
| 0.01        | 20.090         |

### Z-Test Per Digit (with Continuity Correction)

```
Z = (|p_observed - p_expected| - 1/(2N)) / sqrt(p_expected * (1 - p_expected) / N)
```

- Apply Yates' continuity correction `-1/(2N)` to reduce Type I error
- Flag digit if Z > 1.96 (95% confidence)
- The Z-score identifies which specific digits are anomalous, complementing the overall MAD/chi-squared tests

### Kolmogorov-Smirnov (KS) Test

```
D = max |F_observed(x) - F_expected(x)|
```

Where F is the cumulative distribution function. The KS test is sensitive to systematic shifts in the distribution (e.g., all digits shifted slightly higher) that MAD might average away.

---

## 5. Summation Test

The summation test (Nigrini, 1994) examines whether the total monetary value is evenly distributed across first-two-digit groups.

### Rationale

Even if digit frequencies appear normal, a fraudster might create a small number of very large fabricated transactions. These would not distort frequencies (because they are few) but would concentrate monetary value.

### Expected Distribution

Each first-two-digit group (10 through 99) should carry approximately 1/90 (~1.11%) of the total monetary value. This is derived from the fact that each mantissa interval contributes equally to the total in a Benford-distributed dataset.

### Interpretation

- A single digit group carrying > 5% of total value warrants investigation
- The Z-test per group uses the same formula as for frequency tests but applied to value shares instead of frequency shares

---

## 6. Sample Size Considerations

| Sample Size | Reliability  | Notes                                                    |
|-------------|-------------|----------------------------------------------------------|
| < 50        | Unreliable  | Do not apply Benford's Law                                |
| 50 -- 100   | Very Low    | Results are indicative only; high Type I and Type II error |
| 100 -- 500  | Moderate    | Use with caution; MAD is more reliable than chi-squared   |
| 500 -- 1000 | Good        | Standard forensic analysis range                          |
| > 1000      | High        | Strong statistical power                                  |
| > 10000     | Very High   | Chi-squared will almost always reject; rely on MAD        |

---

## 7. Court Admissibility Notes

Benford's Law analysis has been accepted as evidence in US federal courts (e.g., *United States v. Skilling*, 2006) and in Indian tribunals. To maintain admissibility:

1. **Document the methodology** -- the test, thresholds, and significance levels must be stated in advance
2. **Use published thresholds** -- Nigrini's thresholds are the accepted standard
3. **Report all tests** -- do not selectively report only the tests that produce anomalies
4. **State the limitations** -- sample size, data quality, natural explanations for deviations
5. **Reproducibility** -- the same input data with the same parameters must produce the same results
6. **Chain of custody** -- the data source (DuckDB, table, column, filter) must be recorded in the output metadata
