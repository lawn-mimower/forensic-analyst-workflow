# Part 6 — Pipeline Mapping: Resources to Categories

Maps every downloaded resource and reference to your pipeline's compliance categories, and identifies gaps.

## 6.1 Your Current 19 Categories → Resources

| # | Pipeline Category | Key Downloaded Resource | Supplementary Web Resource |
|---|---|---|---|
| 1 | `companies_act_2013` | ICSI_Manual_Secretarial_Audit.pdf, ICAI_CARO_2020_Guidance_Note.pdf, ICAI_Audit_Committee_Technical_Guide.pdf | [CAIRR](https://ca2013.com/) |
| 2 | `indian_penal_code_bharatiya_nyaya_sanhita` | BPRD_BNS_Handbook_2023.pdf, structured-data/Indian-Law-Penal-Code-Json/ipc.json | — |
| 3 | `prevention_of_money_laundering_act_2002` | FIU_India_AML_CFT_Guidelines.pdf, PMLA_2002_Full_Text.html | [FIU-IND](https://fiuindia.gov.in/) |
| 4 | `sebi_act_regulations` | ICSI_LODR_Referencer_Debt_Securities.pdf, ICSI_ASCR_Guidance_Note.pdf | [SEBI Master Circulars](https://www.sebi.gov.in/) |
| 5 | `rbi_directions_banking_regulation` | — (manual download needed) | [RBI Master Directions](https://rbi.org.in/scripts/bs_viewmasterdirections.aspx) |
| 6 | `income_tax_act_1961` | ICAI_Tax_Audit_GN_Section_44AB.pdf | — |
| 7 | `black_money_act_2015` | — | [India Code](https://www.indiacode.nic.in/) |
| 8 | `cgst_act_2017` | — | [ICAI Indirect Tax Publications](https://idtc.icai.org/publications.php) |
| 9 | `fema_1999` | — | [RBI FEMA Directions](https://rbi.org.in/) |
| 10 | `negotiable_instruments_act_1881` | structured-data/Indian-Law-Penal-Code-Json/ | [India Code](https://www.indiacode.nic.in/) |
| 11 | `fugitive_economic_offenders_act_2018` | — | [India Code](https://www.indiacode.nic.in/) |
| 12 | `benami_transactions_act_1988` | — | [India Code](https://www.indiacode.nic.in/) |
| 13 | `chartered_accountants_act_1949` | — | [ICAI](https://www.icai.org/) |
| 14 | `icai_standards_on_auditing` | — (manual download: ICAI Checklist on SAs) | [ICAI AASB](https://www.icai.org/post/icai-publications-auditing-assurance-standards-board) |
| 15 | `icai_code_of_ethics` | — (manual download: ICAI Code of Ethics PDF) | [ICAI ESB](https://www.icai.org/post/icai-publications-ethical-standards-board) |
| 16 | `nfra_rules_2018` | — | [NFRA](https://nfra.gov.in/) |
| 17 | `insolvency_and_bankruptcy_code_2016` | — | [IBBI](https://ibbi.gov.in/) |
| 18 | `cost_and_works_accountants_act_1959` | — | [ICMAI](https://icmai.in/) |
| 19 | `company_secretaries_act_1980` | ICSI_CSAS4_Secretarial_Audit_Standard.pdf, ICSI_SACMDD_Study_Material.pdf | [ICSI](https://www.icsi.edu/) |

## 6.2 Recommended New Categories

Based on the study guide research, these categories should be added to your `indian_financial_fraud_compliance_laws.json`:

| New Category | Justification | Source for Rules |
|---|---|---|
| **ICAI FAIS 2023** | World's first forensic accounting standards — directly relevant to your tool's purpose | ICAI_FAIS_2023_Forensic_Standards.pdf |
| **CARO 2020** | 21 specific statutory reporting requirements — highly structured, easy to convert to rules | ICAI_CARO_2020_Guidance_Note.pdf |
| **SEBI LODR 2015** | Master regulation for listed companies — covers governance, disclosure, reporting | ICSI_LODR_Referencer_Debt_Securities.pdf |
| **SEBI PIT 2015** | Insider trading regulation — critical for securities fraud detection | SEBI website |
| **Ind AS / Accounting Standards** | Financial statement compliance depends on correct application of accounting standards | ICAI ASB publications |
| **ICDS** | 10 standards for tax computation — creates reconciliation requirements | ICAI_Tax_Audit_GN_Section_44AB.pdf |
| **Secretarial Standards (SS-1, SS-2)** | Mandatory standards for board/general meetings | ICSI publications |
| **Digital Personal Data Protection Act, 2023** | New law (effective 2025) — data handling compliance for all companies | MCA |
| **Depositories Act, 1996** | Relevant for share-related compliance | India Code |

## 6.3 Coverage Heat Map

How well each resource covers each domain:

```
Resource                          | Corp | Audit | Tax | SEBI | Fraud | AML | Banking
----------------------------------|------|-------|-----|------|-------|-----|--------
ICSI Manual Secretarial Audit     | ████ | ██    | █   | ████ | █     | █   |
ICAI CARO 2020 GN                | ████ | ████  | █   |      | ██    |     |
ICAI Tax Audit GN                |      | ██    | ████|      |       |     |
ICAI FAIS 2023                   |      | ██    |     |      | ████  | ██  |
BPRD BNS Handbook                |      |       |     |      | ████  | ██  |
FIU AML/CFT Guidelines           |      |       |     |      | ██    | ████| ██
ICSI GRC Ethics                  | ███  | █     | █   | ██   | █     | █   |
ICSI ASCR GN                     | ██   |       |     | ████ |       |     |
ICAI Audit Committee TG          | ███  | ███   |     | ██   | ██    |     |
ICSI LODR Referencer             |      |       |     | ████ |       |     |
ICSI CSAS-4                      | ███  | ████  |     | ██   |       |     |
ICSI SACMDD Study                | ███  | ████  |     | ██   | █     |     |

Legend: ████ = comprehensive  ███ = good  ██ = moderate  █ = light
```

## 6.4 Priority Actions for Pipeline Improvement

### Immediate (use downloaded resources)

1. Parse `ICAI_CARO_2020_Guidance_Note.pdf` → extract 21 clauses as atomic compliance rules
2. Parse `ICAI_Tax_Audit_GN_Section_44AB.pdf` → extract Form 3CD's 44 clauses
3. Parse `ICSI_Manual_Secretarial_Audit.pdf` → extract event-wise checklists
4. Parse `BPRD_BNS_Handbook_2023.pdf` → update IPC/BNS section mapping tables
5. Parse `ICAI_FAIS_2023_Forensic_Standards.pdf` → create new FAIS category

### Short-term (manual downloads needed)

6. Download ICAI Checklist on SAs → parse 38 SA checklists into rules
7. Download ICAI Code of Ethics → parse NOCLAR provisions
8. Download ICAI ICFR GN → parse internal control evaluation criteria

### Medium-term (web scraping/API)

9. Use CAIRR (ca2013.com) to cross-reference Companies Act sections with rules
10. Use Indian Kanoon API for case law context on each rule
11. Scrape NSE/BSE compliance calendars for temporal compliance rules
