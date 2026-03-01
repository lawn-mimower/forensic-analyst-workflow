# Indian Financial Thresholds That Affect Benford's Law Analysis

This reference documents Indian-specific statutory and corporate thresholds that cause natural clustering in financial data. When Benford's analysis flags amounts near these thresholds, the deviation may have a legitimate regulatory or behavioral explanation rather than indicating fraud.

The forensic analyst must consider these thresholds before concluding that a Benford's deviation is anomalous.

---

## 1. Tax Deducted at Source (TDS) Thresholds

TDS withholding obligations create behavioral incentives: payees may structure invoices to stay below thresholds to avoid cash-flow impact of withholding, and payers may split payments.

### Section-wise Thresholds (Income Tax Act, 1961)

| Section | Nature of Payment | Threshold (per payee per year) | TDS Rate | Behavioral Effect |
|---------|-------------------|-------------------------------|----------|-------------------|
| **192** | Salary | Basic exemption limit (INR 2,50,000 / 3,00,000 / 5,00,000 depending on regime) | Slab rates | Payroll structuring near exemption limits |
| **194A** | Interest (other than securities) | INR 40,000 (INR 50,000 for senior citizens) | 10% | Fixed deposits structured below threshold |
| **194C** | Contractor payments -- single transaction | INR 30,000 | 1% (individual) / 2% (company) | Invoice splitting to stay below INR 30,000 |
| **194C** | Contractor payments -- aggregate annual | INR 1,00,000 | 1% / 2% | Annual payment structuring |
| **194H** | Commission or brokerage | INR 15,000 | 5% | Commission payments structured below threshold |
| **194I** | Rent | INR 2,40,000 per annum | 2% (plant/machinery) / 10% (land/building) | Monthly rent structured below INR 20,000 |
| **194J** | Professional/technical fees | INR 30,000 | 2% (technical) / 10% (professional) | Consulting invoices split below INR 30,000 |
| **194Q** | Purchase of goods | INR 50,00,000 | 0.1% | Large purchases structured below threshold |
| **194R** | Perquisites/benefits to business | INR 20,000 | 10% | Gift/benefit amounts kept below threshold |
| **194S** | Transfer of virtual digital assets | INR 50,000 (specified person) / INR 10,000 (others) | 1% | Crypto transaction structuring |
| **206C(1H)** | Sale of goods | INR 50,00,000 | 0.1% | Revenue suppression near threshold |

### Behavioral Patterns to Watch

- Clustering of contractor invoices at INR 29,000-29,999 (just below INR 30,000 194C limit)
- Professional fee invoices consistently at INR 29,500-29,999
- Rent payments structured as INR 19,000-19,999 monthly (to keep annual below INR 2,40,000)
- Multiple invoices from same vendor in same month (invoice splitting)

---

## 2. Goods and Services Tax (GST) Thresholds

### Registration and Compliance Thresholds

| Threshold | Applicability | Behavioral Effect |
|-----------|--------------|-------------------|
| **INR 20,00,000** (turnover) | Mandatory GST registration for goods suppliers | Businesses may suppress revenue to stay below |
| **INR 10,00,000** (turnover) | Mandatory GST registration for special category states (NE states, J&K, Himachal, Uttarakhand) | Lower threshold creates more pressure |
| **INR 40,00,000** (turnover) | Threshold for goods-only suppliers (not applicable to services) | |
| **INR 1,50,00,000** | Composition scheme eligibility limit | Revenue suppression to remain in composition scheme (lower compliance burden) |
| **INR 50,00,000** | Composition scheme for service providers | |
| **INR 5,00,00,000** | E-invoicing mandatory threshold (from August 2023) | Revenue structuring to avoid e-invoicing compliance |
| **INR 2,00,00,000** | GST audit threshold (GSTR-9C) | Revenue suppression to avoid audit |

### E-Way Bill Thresholds

| Threshold | Applicability | Behavioral Effect |
|-----------|--------------|-------------------|
| **INR 50,000** | E-way bill mandatory for interstate movement of goods | Consignment value splitting to avoid e-way bill |
| **INR 1,00,000** | E-way bill for intrastate movement (varies by state) | Similar splitting behavior |

### Input Tax Credit (ITC) Patterns

- Vendors may issue credit notes to adjust invoices below thresholds
- ITC reversal triggers at specific proportions (common-credit rule under Rule 42/43)
- Year-end ITC reversals in March can cause clustering

---

## 3. Companies Act, 2013 Thresholds

### Board and Shareholder Approval Limits

| Section | Nature | Threshold | Approval Required | Behavioral Effect |
|---------|--------|-----------|-------------------|-------------------|
| **S.180(1)(a)** | Sale/lease/disposal of undertaking | Substantial part of assets | Special resolution + board | Transactions structured to avoid "substantial" classification |
| **S.180(1)(c)** | Borrowing powers | Aggregate exceeding paid-up capital + free reserves | Special resolution | Borrowing structured below threshold |
| **S.185** | Loan to directors | Any amount (effectively prohibited for most companies) | -- | Disguised as advances, deposits, or related-party transactions |
| **S.186** | Loan/guarantee/investment in other body corporates | 60% of paid-up capital + free reserves + securities premium, OR 100% of free reserves, whichever is more | Special resolution if exceeds | Investments structured below threshold |
| **S.188** | Related party transactions | Prescribed thresholds (see below) | Board/shareholder approval | Transaction splitting to avoid disclosure |

### Related Party Transaction Thresholds (Rule 15 of Companies (Meetings of Board and its Powers) Rules, 2014)

| Nature of Transaction | Threshold (requiring shareholder approval) |
|----------------------|-------------------------------------------|
| Sale/purchase/supply of goods/materials | 10% of turnover |
| Selling/buying property | 10% of net worth |
| Leasing of property | 10% of turnover |
| Availing/rendering services | 10% of turnover |
| Appointment to office/place of profit | Monthly remuneration > INR 2,50,000 |
| Remuneration for underwriting | 1% of net worth |

### Audit Committee Thresholds (Regulation 23, SEBI LODR)

For listed companies:
- Related party transactions > INR 1,000 crore OR 10% of annual consolidated turnover (whichever is lower) require shareholder approval
- All material RPTs need prior audit committee approval

---

## 4. Common Corporate Delegation of Authority (DoA) Limits

These are not statutory but are commonly found in Indian corporate governance frameworks. Transactions may cluster just below these limits.

| Approval Level | Typical Limit | Common Pattern |
|---------------|--------------|----------------|
| Petty cash / Office manager | INR 5,000 -- INR 10,000 | Small expense claims at INR 4,900 -- INR 9,900 |
| Department manager | INR 25,000 -- INR 50,000 | Vendor payments at INR 49,000 -- INR 49,999 |
| Senior manager / GM | INR 1,00,000 -- INR 2,00,000 | Purchase orders at INR 99,000 -- INR 1,99,000 |
| VP / Divisional head | INR 5,00,000 -- INR 10,00,000 | Capital expenditure at INR 4,99,000 -- INR 9,99,000 |
| CFO / Managing Director | INR 25,00,000 -- INR 50,00,000 | Large contracts structured below board threshold |
| Board / Committee | INR 1,00,00,000+ | Transactions split to avoid board agenda |

**How to use:** When Benford's analysis flags clustering at specific amounts, check the entity's delegation of authority matrix (if available) to determine if the clustering matches an approval threshold.

---

## 5. Cash Transaction Limits

### Income Tax Act Restrictions

| Section | Nature | Threshold | Consequence | Behavioral Effect |
|---------|--------|-----------|-------------|-------------------|
| **S.269SS** | Acceptance of loan/deposit/advance | INR 20,000 (from a person in a day) | Penalty = 100% of amount (S.271D) | Cash transactions structured below INR 20,000 |
| **S.269T** | Repayment of loan/deposit/advance | INR 20,000 | Penalty = 100% of amount (S.271E) | Repayment splitting |
| **S.269ST** | Receipt of amount in cash | INR 2,00,000 (from a person in a day / for a single transaction / for transactions related to one event) | Penalty = 100% (S.271DA) | Cash receipts structured below INR 2,00,000 |
| **S.40A(3)** | Cash payment for expenses | INR 10,000 (per day per person) | Disallowance of expenditure | Expense payments split across days or payees |
| **S.43(1)** | Capital asset acquisition | INR 10,000 (cash payment) | Cost not allowable for depreciation | Asset purchase structuring |

### Prevention of Money Laundering Act (PMLA) / FEMA

| Threshold | Context | Behavioral Effect |
|-----------|---------|-------------------|
| **INR 10,00,000** | Cash transaction reporting threshold (by banks) | Transactions structured below INR 10 lakh |
| **INR 50,000** | Cash deposit identification requirement (PAN mandatory) | Deposits structured below INR 50,000 |
| **USD 250,000** | LRS (Liberalised Remittance Scheme) annual limit | Foreign remittances structured below limit |

---

## 6. Fiscal Year-End Effects (March Transactions)

Indian companies follow an April-March fiscal year (FY 2023-24 = April 2023 to March 2024). March transactions naturally deviate from Benford's for several reasons:

### Legitimate Year-End Activities

1. **Provisions and accruals** -- Estimates for expenses incurred but not yet invoiced. These are typically round numbers.
2. **Write-offs and write-backs** -- Bad debt write-offs, inventory write-downs, provision reversals
3. **Advance billing** -- Revenue recognized in March for Q1 deliverables (common in IT/ITES)
4. **Budget utilization** -- Government and PSU clients spend remaining budget allocations in March
5. **Tax-planning transactions** -- Donations (S.80G), insurance premiums, advance tax payments
6. **Transfer pricing adjustments** -- Year-end adjustments for related party transactions to maintain arm's-length pricing
7. **Closing entries** -- Depreciation calculations, foreign exchange revaluations, fair value adjustments

### How to Handle

- Always run Benford's analysis separately for Q4 (January-March) vs. Q1-Q3
- If Q4 deviates but Q1-Q3 conform, document the year-end effect as a natural explanation
- If Q4 deviates AND the deviations cluster near specific thresholds or round numbers, investigate further -- year-end urgency creates cover for fraudulent entries
- Manual journal entries in the last week of March deserve heightened scrutiny regardless of Benford's results

---

## 7. Industry-Specific Thresholds

### Government Procurement (GFR 2017 / GeM Portal)

| Threshold | Procurement Method | Effect |
|-----------|-------------------|--------|
| INR 25,000 | Direct purchase (no quotes needed) | Purchases structured below INR 25,000 |
| INR 2,50,000 | Purchase committee (3 quotes) | Splitting to avoid committee process |
| INR 25,00,000 | Open tender mandatory | Contract splitting below tender threshold |

### Real Estate (RERA)

| Threshold | Context | Effect |
|-----------|---------|--------|
| INR 500 sq.m or 8 apartments | RERA registration mandatory | Project structuring |
| Stamp duty rates | Vary by state, typically 5-7% | Undervaluation of property transactions |

### Banking (RBI Norms)

| Threshold | Context | Effect |
|-----------|---------|--------|
| INR 5,00,000 | Priority sector lending individual loan | Loan structuring |
| INR 25,00,000 | MSME loan classification | Loan amount structuring |
| INR 5,00,00,000 | Large exposure framework | Exposure splitting |
