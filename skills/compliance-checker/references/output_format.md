# Output Format Reference

JSON schemas for all intermediate and final outputs of the compliance checker pipeline.

## Phase 0 — `document_profile.json`

```json
{
  "document_summary": "string — full text summary from LightRAG global query",
  "applicable_category_keys": ["companies_act_2013", "income_tax_act_1961", "..."],
  "applicable_category_names": ["Companies Act, 2013", "Income Tax Act, 1961", "..."],
  "total_applicable": 5,
  "total_available": 17
}
```

## Phase 1 — `atomic_questions.json`

```json
[
  {
    "question_id": "Q0001",
    "question_text": "Does the financial statement disclose that it follows accrual basis of accounting?",
    "suggested_mode": "local",
    "keywords": ["accrual", "accounting basis"],
    "source_category": "companies_act_2013",
    "source_category_name": "Companies Act, 2013",
    "source_section": "section_128",
    "source_section_name": "Section 128 - Books of Account"
  }
]
```

## Phase 2 — `retrieved_contexts.json`

```json
{
  "Q0001": {
    "question_id": "Q0001",
    "context_text": "string — retrieved context from LightRAG",
    "is_empty": false,
    "mode_used": "local"
  }
}
```

## Phase 3 — `verdicts.json`

```json
[
  {
    "question_id": "Q0001",
    "verdict": "COMPLIANT",
    "reasoning": "The financial statements explicitly state they follow accrual basis.",
    "excerpt": "The financial statements are prepared on accrual basis..."
  }
]
```

Valid verdict values: `COMPLIANT`, `VIOLATION`, `INSUFFICIENT_EVIDENCE`

## Phase 4 — `compliance_report.json`

```json
{
  "report_metadata": {
    "generated_at": "2026-02-19T12:00:00",
    "document_summary": "string",
    "total_categories": 5,
    "total_questions": 120
  },
  "overall": {
    "score": 0.85,
    "score_pct": "85.0%",
    "totals": {
      "COMPLIANT": 68,
      "VIOLATION": 12,
      "INSUFFICIENT_EVIDENCE": 40
    }
  },
  "categories": {
    "companies_act_2013": {
      "category_name": "Companies Act, 2013",
      "score": 0.90,
      "total_questions": 45,
      "totals": { "COMPLIANT": 30, "VIOLATION": 3, "INSUFFICIENT_EVIDENCE": 12 },
      "sections": {
        "section_128": {
          "section_name": "Section 128 - Books of Account",
          "score": 1.0,
          "total_questions": 3,
          "totals": { "COMPLIANT": 2, "VIOLATION": 0, "INSUFFICIENT_EVIDENCE": 1 },
          "questions": [
            {
              "question_id": "Q0001",
              "question_text": "...",
              "verdict": "COMPLIANT",
              "reasoning": "...",
              "excerpt": "..."
            }
          ]
        }
      }
    }
  }
}
```

## Phase 4 — `compliance_report.md`

Markdown format:

```markdown
# Compliance Report: {Entity Name}
**Overall Score**: X% | **Questions**: N | **Compliant**: C | **Violations**: V | **Insufficient Evidence**: I

---

## {Category Name}
**Category Score**: Y% | **Compliant**: C | **Violations**: V | **Insufficient**: I

### {Section Name}
**Score**: C/J (Z%) | K INSUFFICIENT

| # | Question | Verdict | Reasoning | Excerpt |
|---|---|---|---|---|
| 1 | ... | COMPLIANT | ... | ... |
```

## Scoring Formula

- **Section score**: `compliant / (compliant + violation)` — excludes INSUFFICIENT_EVIDENCE
- **Category score**: same formula aggregated across all sections
- **Overall score**: same formula aggregated across all categories
- Score is `null` / `N/A` when there are zero judgeable (compliant + violation) items
