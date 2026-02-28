# Part 5 — Fraud Detection, Forensic Accounting, and Anti-Money Laundering

## 5.1 ICAI Forensic Accounting and Investigation Standards (FAIS), 2023

FAIS is the **world's first forensic accounting standards framework**, mandatory for all ICAI members from July 1, 2023. This is the single most important resource for understanding how forensic investigations should be conducted in India.

### Structure of FAIS

| Category | Standards | Focus |
|---|---|---|
| **Key Concepts** | FAIS 100-series | What forensic accounting is, scope, terminology |
| **Engagement Management** | FAIS 200-series | Accepting engagements, planning, team composition |
| **Executing Assignments** | FAIS 300-series | Evidence gathering, data analytics, interviewing, the 5W approach |
| **Specialized Areas** | FAIS 400-series | Digital forensics, valuation disputes, insurance claims |
| **Quality Control** | FAIS 500-series | Quality assurance, peer review, documentation |

### The 5W Approach (FAIS Investigation Methodology)

1. **What** happened? (Identify the irregularity)
2. **Who** is involved? (Identify perpetrators and victims)
3. **When** did it happen? (Timeline reconstruction)
4. **Where** did it happen? (Identify locations, accounts, entities)
5. **Why** did it happen? (Motive — the fraud triangle: opportunity, pressure, rationalization)

### Key FAIS Standards for Document Compliance

| Standard | Topic | Application |
|---|---|---|
| FAIS 110 | Forensic Accounting Framework | Conceptual framework for all forensic work |
| FAIS 210 | Engagement Acceptance | When and how to accept a forensic engagement |
| FAIS 310 | Evidence Collection | Standards for gathering admissible evidence |
| FAIS 320 | Data Analytics in Forensics | Using data analytics for fraud detection |
| FAIS 410 | Digital Evidence | Handling electronic evidence, chain of custody |

**Resource**: `pdfs/ICAI_FAIS_2023_Forensic_Standards.pdf`
**Your pipeline category to add**: `icai_fais_2023`

## 5.2 Fraud Under Indian Law

### Companies Act S.447 — Definition of Fraud

Fraud includes any act, omission, concealment of any fact or abuse of position committed with intent to deceive, gain undue advantage, or injure the interests of the company, its shareholders, creditors, or any other person. This covers:
- **Falsification of documents** (financial statements, board minutes, filings)
- **Wrongful gain** at the expense of the company
- **Knowing misrepresentation** of material facts

**Punishment**: 1-10 years imprisonment + fine of 1x-3x the amount involved.
For fraud involving public interest: minimum 3 years.

### S.143(12) — Mandatory Fraud Reporting by Auditors

| Amount | Report To | Timeline |
|---|---|---|
| >= Rs. 1 crore | Central Government via Form ADT-4 | Within 60 days |
| < Rs. 1 crore | Audit Committee or Board | Within 2 days |

### Bharatiya Nyaya Sanhita (BNS), 2023 — Replaces IPC

Effective July 1, 2024. Key economic offence provisions:

| BNS Section | Offence | IPC Equivalent |
|---|---|---|
| S.318 | Cheating | S.420 IPC |
| S.316 | Criminal Breach of Trust | S.406 IPC |
| S.335-340 | Forgery and counterfeiting | S.463-489 IPC |
| S.111 | Organized crime (includes financial crime) | **New — no IPC equivalent** |
| S.318(4) | Mass marketing fraud | **New** |

**Resource**: `pdfs/BPRD_BNS_Handbook_2023.pdf` — comprehensive handbook with IPC-to-BNS mapping
**Your pipeline category**: `indian_penal_code_bharatiya_nyaya_sanhita`

## 5.3 Prevention of Money Laundering Act (PMLA), 2002

### Key Obligations

| Obligation | Details |
|---|---|
| **Customer Due Diligence (CDD)** | Identity verification for all customers |
| **Enhanced Due Diligence (EDD)** | For high-risk customers, PEPs, complex transactions |
| **Suspicious Transaction Reporting (STR)** | Report to FIU-IND within prescribed timeline |
| **Cash Transaction Reporting (CTR)** | Cash transactions > Rs. 10 lakh in a month |
| **Record Maintenance** | 5 years from date of transaction |
| **Appointment of Principal Officer** | Mandatory for reporting entities |

### Scheduled Offences (PMLA Schedule)

Money laundering is the "proceeds of crime" from any scheduled offence, including:
- Fraud under Companies Act
- Tax evasion under Income Tax Act
- FEMA contraventions
- Cheating/criminal breach of trust under BNS
- Corruption under Prevention of Corruption Act
- Narcotics offences

**Resource**: `pdfs/FIU_India_AML_CFT_Guidelines.pdf` + `pdfs/PMLA_2002_Full_Text.html`
**Your pipeline category**: `prevention_of_money_laundering_act_2002`

## 5.4 Other Fraud-Related Laws

### Fugitive Economic Offenders Act, 2018
- Applies when offence amount > Rs. 100 crore and the accused has left India
- Properties can be confiscated even before conviction

### Benami Transactions (Prohibition) Act, 1988 (amended 2016)
- Property held in name of another person (benamidar) while consideration paid by beneficial owner
- Punishment: 1-7 years imprisonment + fine up to 25% of fair market value

### Negotiable Instruments Act, 1881 — S.138
- Dishonour of cheque for insufficiency of funds
- Punishment: imprisonment up to 2 years or fine up to twice the cheque amount

**Your pipeline categories**: `fugitive_economic_offenders_act_2018`, `benami_transactions_act_1988`, `negotiable_instruments_act_1881`

## 5.5 Red Flags Checklist for Forensic Analysts

Use this when reviewing any company document:

### Financial Statement Red Flags
- [ ] Revenue growth inconsistent with industry/cash flows
- [ ] Unusual related party transactions, especially near year-end
- [ ] Significant management estimates without adequate basis
- [ ] Frequent changes in accounting policies
- [ ] Round-number journal entries
- [ ] Post-closing adjustments
- [ ] Receivables growing faster than revenue
- [ ] Inventory growing faster than COGS

### Corporate Governance Red Flags
- [ ] Frequent auditor changes
- [ ] Qualified audit opinions or emphasis of matter paragraphs
- [ ] Inadequate Audit Committee composition or meetings
- [ ] No whistleblower mechanism
- [ ] Related party transactions not at arm's length
- [ ] Director disqualifications

### Operational Red Flags
- [ ] Cash losses in multiple years
- [ ] Statutory dues outstanding > 6 months
- [ ] Loan defaults
- [ ] SFIO/SEBI investigations
- [ ] Pending litigations of material nature

## 5.6 Self-Assessment Questions

1. What are the five categories of FAIS standards?
2. How does S.447 of Companies Act define fraud?
3. What is the two-tier fraud reporting obligation under S.143(12)?
4. What are the new economic offence provisions in BNS that had no IPC equivalent?
5. What are the three elements of the fraud triangle?
6. When must a Suspicious Transaction Report be filed under PMLA?
7. Name 5 financial statement red flags that indicate potential fraud.
