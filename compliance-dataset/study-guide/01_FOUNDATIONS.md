# Part 1 — Foundations: The Indian Compliance Landscape

## 1.1 Why This Matters

A forensic analyst checking Indian company documents needs to understand the **regulatory ecosystem** — who makes the rules, who enforces them, and how they interact. India has a layered compliance structure where multiple regulators may apply to the same company simultaneously.

## 1.2 Key Regulatory Bodies

### Ministry of Corporate Affairs (MCA)
- **Governs**: All companies registered under the Companies Act, 2013
- **Key tool**: MCA-21 e-filing portal
- **Enforcement arm**: Serious Fraud Investigation Office (SFIO)
- **Standards body**: National Financial Reporting Authority (NFRA)

### Institute of Chartered Accountants of India (ICAI)
- **Role**: Statutory body governing CAs, sets auditing standards, accounting standards, and forensic accounting standards
- **Key publications**: Standards on Auditing (38 SAs), FAIS 2023, Guidance Notes on CARO/Tax Audit/ICFR
- **Why it matters**: Every financial document you check was prepared or audited by someone bound by ICAI standards

### Institute of Company Secretaries of India (ICSI)
- **Role**: Statutory body governing Company Secretaries
- **Key publications**: Manual on Secretarial Audit, CSAS standards, compliance checklists
- **Why it matters**: Secretarial audit covers the broadest multi-law compliance scope

### Securities and Exchange Board of India (SEBI)
- **Governs**: Listed companies, securities markets, mutual funds, intermediaries
- **Key regulations**: LODR (Listing Obligations), PIT (Insider Trading), ICDR (Capital Issues), Takeover Code
- **Disclosure regime**: Continuous disclosure + periodic filings

### Reserve Bank of India (RBI)
- **Governs**: Banks, NBFCs, payment systems, foreign exchange
- **Key instruments**: Master Directions (consolidated circulars), KYC/AML directions
- **Why it matters**: Banking sector compliance is governed almost entirely by RBI

### Central Board of Direct Taxes (CBDT) / Central Board of Indirect Taxes (CBIC)
- **CBDT**: Income Tax Act, ICDS (Income Computation & Disclosure Standards)
- **CBIC**: GST (CGST/SGST/IGST), Customs

### Financial Intelligence Unit — India (FIU-IND)
- **Role**: India's central agency for receiving, processing, and disseminating suspicious transaction reports
- **Governs**: AML/CFT compliance for reporting entities under PMLA

## 1.3 How Laws and Standards Interact

```
Constitution of India
    |
    v
Acts of Parliament (e.g., Companies Act 2013, Income Tax Act 1961)
    |
    v
Rules & Regulations (e.g., Companies Rules 2014, SEBI LODR Regulations)
    |
    v
Circulars & Notifications (e.g., MCA circulars, SEBI master circulars)
    |
    v
Professional Standards (e.g., ICAI SAs, ICSI CSAS, Ind AS)
    |
    v
Guidance Notes & Technical Guides (interpretive, non-binding but authoritative)
```

**Key insight**: A single company document (say, an Annual Report) may need to comply with:
- Companies Act 2013 (Sections 128-134, 143, etc.)
- Schedule III format requirements
- Ind AS / Accounting Standards
- CARO 2020 reporting requirements
- SEBI LODR (if listed)
- Income Tax Act (tax audit under Section 44AB)
- GST requirements
- Secretarial Standards SS-1 and SS-2

## 1.4 Document Types and Their Primary Regulators

| Document | Primary Regulator | Key Laws/Standards |
|---|---|---|
| Financial Statements (P&L, Balance Sheet) | MCA + ICAI | Companies Act S.128-134, Schedule III, Ind AS, SAs |
| Annual Report | MCA + SEBI (if listed) | Companies Act S.134, SEBI LODR Reg.34 |
| Auditor's Report | MCA + ICAI + NFRA | Companies Act S.143, CARO 2020, SAs |
| Tax Audit Report | CBDT + ICAI | Income Tax Act S.44AB, Forms 3CA/3CB/3CD |
| Board Resolutions | MCA + ICSI | Companies Act S.179, SS-1 |
| Related Party Disclosures | MCA + SEBI | Companies Act S.188, Ind AS 24, SEBI LODR Reg.23 |
| Secretarial Audit Report | MCA + ICSI | Companies Act S.204, CSAS-4, Form MR-3 |
| KYC/AML Records | RBI + FIU | PMLA 2002, RBI KYC Master Direction |
| Prospectus/Offer Document | SEBI | SEBI ICDR Regulations |
| GST Returns | CBIC | CGST Act 2017, GSTR-9 |

## 1.5 Key Reference — Downloaded Resources for This Section

| Resource | File | Covers |
|---|---|---|
| ICSI GRC & Ethics Study Material | `pdfs/ICSI_GRC_Ethics_Study_Material.pdf` | Full governance, risk, compliance framework |
| PMLA Full Text | `pdfs/PMLA_2002_Full_Text.html` | Anti-money laundering legislation |
| CivicTech Legal JSONs | `structured-data/Indian-Law-Penal-Code-Json/` | IPC, CrPC, Evidence Act in structured format |
