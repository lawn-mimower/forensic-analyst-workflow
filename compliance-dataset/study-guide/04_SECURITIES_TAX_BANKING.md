# Part 4 — Securities, Tax, and Banking Regulation

## 4.1 SEBI Regulations (Securities Market)

### SEBI LODR — Listing Obligations and Disclosure Requirements, 2015

This is the **master regulation for listed companies**. If a company is listed on NSE/BSE, LODR compliance is mandatory.

| Regulation | Topic | Compliance Check |
|---|---|---|
| Reg. 17 | Board composition | At least 1/3 independent directors (1/2 for top 500 by market cap) |
| Reg. 18 | Audit Committee | Minimum 3 members, 2/3 independent, all financially literate |
| Reg. 23 | Related Party Transactions | Prior approval of Audit Committee, shareholder approval for material RPTs |
| Reg. 27 | Corporate Governance compliance report | Quarterly filing with stock exchanges |
| Reg. 30 | Disclosure of material events | Timely disclosure of events listed in Schedule III |
| Reg. 33 | Financial results | Quarterly + annual results within prescribed timelines |
| Reg. 34 | Annual Report | Must contain all prescribed disclosures |
| Reg. 46 | Website disclosures | Mandatory information on company website |

**Your pipeline category to add**: `sebi_lodr`
**Resource**: `pdfs/ICSI_LODR_Referencer_Debt_Securities.pdf`
**Web**: NSE/BSE compliance calendars for deadlines

### SEBI PIT — Prohibition of Insider Trading, 2015

| Key Provision | What to Check |
|---|---|
| Insider = anyone with UPSI | Connected persons, designated persons lists |
| Trading window closure | Were trades made during closed windows? |
| Code of Conduct | Does the company have a PIT code? Is it followed? |
| UPSI sharing | Structured Digital Database maintained? |

**Your pipeline category to add**: `sebi_pit`

### SEBI Takeover Code, 2011

Relevant when checking acquisition documents — trigger thresholds (25% initial, 5% creeping), open offer obligations.

## 4.2 Income Tax Act, 1961

### Key Compliance Areas for Forensic Analysis

| Area | Sections | What to Check |
|---|---|---|
| **TDS/TCS** | S.192-206C | Tax deducted at source on salaries, interest, contracts, rent, etc. |
| **Transfer Pricing** | S.92-92F | Related party transactions at arm's length (mandatory TP documentation for international transactions > Rs. 1 crore) |
| **Tax Audit** | S.44AB | See Part 3 — Forms 3CA/3CB/3CD |
| **ICDS** | S.145(2) | 10 Income Computation & Disclosure Standards — differences from accounting standards |
| **Black Money** | Black Money Act, 2015 | Undisclosed foreign income and assets |
| **Benami** | Benami Transactions Act | Property held in name of another person |

### ICDS (Income Computation & Disclosure Standards)

10 standards prescribed by CBDT for computing taxable income. These sometimes differ from accounting standards (Ind AS/AS), creating **reconciliation requirements**.

| ICDS | Topic |
|---|---|
| ICDS I | Accounting Policies |
| ICDS II | Valuation of Inventories |
| ICDS III | Construction Contracts |
| ICDS IV | Revenue Recognition |
| ICDS V | Tangible Fixed Assets |
| ICDS VI | Effects of Changes in Foreign Exchange Rates |
| ICDS VII | Government Grants |
| ICDS VIII | Securities |
| ICDS IX | Borrowing Costs |
| ICDS X | Provisions, Contingent Liabilities, and Contingent Assets |

**Your pipeline category**: `income_tax_act_1961`
**Pipeline addition**: `icds_standards`
**Resource**: `pdfs/ICAI_Tax_Audit_GN_Section_44AB.pdf` covers ICDS extensively

## 4.3 GST (CGST Act, 2017)

| Compliance Area | What to Check |
|---|---|
| GST Registration | All places of business registered? Correct category? |
| Input Tax Credit | ITC claimed correctly? Blocked credits (S.17(5)) excluded? |
| E-invoicing | Mandatory for turnover > Rs. 5 crore — are all invoices e-invoiced? |
| GSTR-9 Annual Return | Filed? Reconciles with books? |
| GSTR-9C Reconciliation | Auditor reconciliation of GST returns with financial statements |
| Reverse Charge | RCM applied where required? |
| HSN/SAC classification | Correct classification and rate applied? |

**Your pipeline category**: `cgst_act_2017`

## 4.4 RBI Directions (Banking & NBFCs)

### Key Master Directions

| Master Direction | Covers |
|---|---|
| KYC Direction | Customer identification, CDD, EDD, ongoing monitoring |
| NBFC Directions | Capital adequacy, asset classification, provisioning |
| IT Governance | Cyber security, business continuity, IT audit |
| Fraud Classification | What constitutes fraud in banking, reporting obligations |
| ALM Guidelines | Asset-Liability Management for banks and NBFCs |

**Your pipeline category**: `rbi_directions_banking_regulation`
**Web resource**: [RBI Master Directions Index](https://rbi.org.in/scripts/bs_viewmasterdirections.aspx)

## 4.5 FEMA, 1999 (Foreign Exchange Management Act)

| Area | What to Check |
|---|---|
| FDI compliance | Sectoral caps, pricing guidelines, reporting (FC-GPR/FC-TRS) |
| ECB compliance | External Commercial Borrowings — end-use restrictions, reporting |
| ODI compliance | Overseas Direct Investment regulations |
| LRS compliance | Liberalised Remittance Scheme — $250,000/year per individual |
| FEMA contraventions | Late reporting, wrong pricing, unapproved transactions |

**Your pipeline category**: `fema_1999`

## 4.6 Self-Assessment Questions

1. What corporate governance disclosures are mandatory under SEBI LODR for listed companies?
2. What is UPSI and who qualifies as an "insider" under SEBI PIT?
3. What are the 10 ICDS and how do they differ from Ind AS?
4. When does reverse charge mechanism apply under GST?
5. What are the FDI reporting obligations under FEMA?
