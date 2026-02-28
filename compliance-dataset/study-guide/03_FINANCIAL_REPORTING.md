# Part 3 — Financial Reporting: Accounting Standards, Auditing Standards, and CARO

## 3.1 Accounting Standards in India

India has two sets of accounting standards:

| Standard Set | Applies To | Governed By |
|---|---|---|
| **Ind AS** (Indian Accounting Standards) | Listed companies, companies with NW >= Rs. 500 cr or turnover >= Rs. 250 cr | MCA (aligned with IFRS) |
| **AS** (Accounting Standards) | All other companies | ICAI / NFRA |

### Key Ind AS for Forensic Analysis

| Standard | Topic | Why It Matters for Forensics |
|---|---|---|
| Ind AS 1 | Presentation of Financial Statements | Format compliance, going concern assessment |
| Ind AS 8 | Accounting Policies, Changes, Errors | Were changes disclosed properly? Prior period errors corrected? |
| Ind AS 10 | Events After Reporting Period | Material post-balance-sheet events disclosed? |
| Ind AS 12 | Income Taxes | Deferred tax computed correctly? |
| Ind AS 18/115 | Revenue Recognition | Revenue recognized per criteria? Premature recognition = red flag |
| Ind AS 24 | Related Party Disclosures | **Critical for fraud** — all RPTs disclosed? Arm's length? |
| Ind AS 33 | Earnings Per Share | EPS computed correctly? |
| Ind AS 36 | Impairment of Assets | Asset values impaired when indicators present? |
| Ind AS 37 | Provisions, Contingent Liabilities | All provisions recognized? Contingencies disclosed? |

**Your pipeline category to add**: `ind_as_accounting_standards`

## 3.2 Standards on Auditing (SAs) — ICAI

There are **38 Standards on Auditing** issued by ICAI. These tell the auditor *how* to audit. For a forensic analyst, understanding SAs tells you what the auditor *should have done*.

### Most Important SAs for Forensic Work

| SA | Title | Forensic Relevance |
|---|---|---|
| **SA 200** | Overall Objectives of the Independent Auditor | Sets the "reasonable assurance" framework |
| **SA 240** | The Auditor's Responsibilities Relating to Fraud | **Core SA for fraud** — presumed risk of fraud in revenue recognition |
| **SA 250** | Laws and Regulations in an Audit | Auditor's duty regarding non-compliance (NOCLAR) |
| **SA 315** | Identifying and Assessing Risks of Material Misstatement | How the auditor should assess fraud risk |
| **SA 330** | Auditor's Responses to Assessed Risks | What the auditor should do about identified risks |
| **SA 500** | Audit Evidence | Standards for evidence — relevant for forensic evidence gathering |
| **SA 505** | External Confirmations | Bank confirmations, debtor confirmations |
| **SA 520** | Analytical Procedures | Ratio analysis, trend analysis — basic forensic techniques |
| **SA 550** | Related Parties | **Critical** — auditor's responsibility for RPTs |
| **SA 570** | Going Concern | Was going concern assessment adequate? |
| **SA 700-706** | Reporting Standards | How audit opinion should be formed and modified |

**Your pipeline category**: `icai_standards_on_auditing`
**Resource**: ICAI Checklist on SAs (requires manual download from ICAI website)

## 3.3 CARO 2020 — Companies (Auditor's Report) Order

CARO 2020 requires the auditor to report on **21 specific matters** in addition to the standard audit report. This is a **goldmine for forensic analysts** because it forces disclosure on exactly the issues that matter.

### Key CARO Clauses

| Clause | Topic | Red Flags |
|---|---|---|
| (i) | Fixed assets — existence, title deeds, revaluation | Mismatched title deeds, inflated revaluation |
| (ii) | Inventory — physical verification, discrepancies | Large unexplained inventory discrepancies |
| (iii) | Loans to parties per S.189 | Loans to related parties, overdue loans |
| (vii) | Statutory dues — PF, ESI, TDS, GST, Income Tax | Undisputed dues outstanding >6 months |
| (ix) | Default in repayment of borrowings | Loan defaults indicate financial distress |
| (x) | Application of funds raised through IPO/further offerings | Fund diversion |
| (xi) | Fraud reported by auditor / on the company | Any fraud reported under S.143(12) |
| (xiii) | Related party transactions per S.177/188 | RPTs not at arm's length |
| (xiv) | Internal audit system adequacy | Inadequate internal audit = higher risk |
| (xvii) | Cash losses in current/previous year | Cash losses indicate fundamental problems |
| (xx) | Unspent CSR amount | CSR obligation unmet |
| (xxi) | Qualifications/adverse remarks in subsidiary audits | Problems in subsidiary financial statements |

**Resource**: `pdfs/ICAI_CARO_2020_Guidance_Note.pdf` — read this cover to cover. It's the most directly useful resource for your pipeline.

## 3.4 Tax Audit under Section 44AB

Tax audit applies to businesses with turnover > Rs. 1 crore (Rs. 10 crore if cash transactions < 5%) and professionals with gross receipts > Rs. 50 lakh.

**Form 3CD** has **44 clauses** covering:
- Books of account maintained
- Method of accounting (cash vs accrual)
- Changes in accounting policies
- Income/deduction computations under various IT Act sections
- TDS/TCS compliance
- GST registration and returns
- ICDS compliance

**Resource**: `pdfs/ICAI_Tax_Audit_GN_Section_44AB.pdf` — 10th edition, updated for Finance Act 2025.

**Your pipeline category**: `income_tax_act_1961`

## 3.5 NFRA and Audit Quality

The National Financial Reporting Authority (NFRA) oversees audit quality for:
- Listed companies and their subsidiaries
- Companies with NW >= Rs. 500 crore or turnover >= Rs. 1,000 crore
- Companies with securities listed outside India

NFRA's **Audit Quality Review (AQR) reports** are uniquely valuable because they show **real-world audit failures** — what auditors commonly miss. Use these to prioritize which compliance checks matter most.

**Web resource**: [nfra.gov.in/aqr/](https://nfra.gov.in/aqr/)

## 3.6 Self-Assessment Questions

1. What is the difference between Ind AS and AS? Which companies must use Ind AS?
2. Under SA 240, what fraud risk must the auditor *always* presume?
3. Name 5 CARO 2020 clauses that are most relevant for detecting financial fraud.
4. What are the turnover thresholds for mandatory tax audit?
5. What is the role of NFRA vs. ICAI in audit oversight?
