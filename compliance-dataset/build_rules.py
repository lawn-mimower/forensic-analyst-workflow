#!/usr/bin/env python3
"""Build compliance_rules.json — 17 categories sourced from compliance-dataset PDFs."""
import json

rules = {
    "metadata": {
        "title": "Indian Financial Compliance Rules — P&L / Financial Statement Analysis",
        "description": "Comprehensive rules sourced from ICAI, ICSI, and statutory references for checking standalone financial statements of Indian private limited companies against applicable laws, standards, and reporting requirements.",
        "jurisdiction": "India",
        "last_updated": "2026-02-28",
        "categories": [
            "Income Tax — Tax Audit (Form 3CD)",
            "CARO 2020",
            "Companies Act 2013 — Financial Statements",
            "Companies Act 2013 — Corporate Governance",
            "ICAI Standards on Auditing",
            "ICAI Forensic Accounting Standards (FAIS 2023)",
            "Employee Benefit Laws",
            "CGST Act, 2017",
            "MSMED Act, 2006",
            "FEMA 1999 — Export Compliance",
            "Indian Accounting Standards (Ind AS)",
            "Schedule III — Companies Act",
            "ICDS (Income Computation & Disclosure Standards)",
            "Audit Committee Requirements",
            "CSR Rules, 2014",
            "Transfer Pricing",
            "Customs & Export Incentives"
        ],
        "source_documents": [
            "ICAI_Tax_Audit_GN_Section_44AB.pdf",
            "ICAI_CARO_2020_Guidance_Note.pdf",
            "ICAI_FAIS_2023_Forensic_Standards.pdf",
            "ICAI_Audit_Committee_Technical_Guide.pdf",
            "ICSI_Manual_Secretarial_Audit.pdf",
            "ICSI_GRC_Ethics_Study_Material.pdf",
            "ICSI_SACMDD_Study_Material.pdf",
            "FIU_India_AML_CFT_Guidelines.pdf",
            "BPRD_BNS_Handbook_2023.pdf"
        ]
    },

    # ── 1. INCOME TAX — TAX AUDIT ──────────────────────────────────────
    "income_tax_tax_audit": {
        "clause_34_applicability": {
            "name": "Clause 34 — Tax Audit Applicability under S.44AB",
            "statement": "Every person carrying on business shall, if his total sales, turnover or gross receipts in business exceed Rs. 1 crore in any previous year, get his accounts audited by an accountant before the specified date and furnish by that date the report of such audit in Form 3CA/3CB and 3CD. The threshold is Rs. 10 crore if cash receipts and payments do not exceed 5% of total receipts and payments respectively. For professionals, the threshold is Rs. 50 lakhs gross receipts. Failure to comply attracts penalty of 0.5% of turnover or Rs. 1,50,000 whichever is lower under S.271B."
        },
        "clause_8_nature_of_business": {
            "name": "Clause 8/8A — Nature of Business",
            "statement": "The tax auditor must report the nature of business or profession carried on by the assessee, and whether there has been any change in the nature of business or profession during the previous year. If there is a change, the auditor must report the details of such change. This is relevant for determining the applicability of specific provisions such as presumptive taxation, industry-specific deductions, and section-specific allowances."
        },
        "clause_11_books_of_account": {
            "name": "Clause 11 — Books of Account Maintained",
            "statement": "The tax auditor must report the list of books of account maintained by the assessee, the address where they are kept, and whether they have been maintained at the registered office. If books are maintained at a place other than the registered office, the auditor must verify the permission for maintenance at such other place. Books of account must be maintained on either cash or accrual basis as per S.145(1)."
        },
        "clause_13_method_of_accounting": {
            "name": "Clause 13 — Method of Accounting and Changes",
            "statement": "The tax auditor must report the method of accounting employed in the previous year (cash or mercantile), whether any change was made in the method of accounting from the immediately preceding year, the details and effect of such change on profit or loss, and whether any adjustment was required in the method of accounting to make it comply with ICDS or the conditions prescribed under S.145(2). Any change in accounting method that affects taxable income must be specifically reported."
        },
        "clause_14_valuation_of_stock": {
            "name": "Clause 14 — Method of Valuation of Closing Stock",
            "statement": "The tax auditor must report the method of valuation of closing stock employed in the previous year (FIFO, weighted average, or specific identification). If the method is different from the preceding year, the auditor must report the effect on profit. Closing stock must be valued at cost or net realizable value, whichever is lower, in accordance with ICDS II. Any deviation from this principle must be reported with its impact on profit."
        },
        "clause_16_amounts_not_allowable_s36": {
            "name": "Clause 16 — Amounts Not Allowable under S.36",
            "statement": "The tax auditor must report amounts debited to the profit and loss account that are not allowable under Section 36. This includes: (a) insurance premium in excess of amount allowed, (b) bonus or commission paid to employees but not actually payable under any law or agreement, (c) interest to partners exceeding 12% per annum, (d) employer's contribution to provident fund/superannuation fund/gratuity fund not made within due dates under respective Acts, (e) any sum paid as an employer towards provident fund without deducting employee's contribution from salary."
        },
        "clause_17_amounts_not_allowable_s37": {
            "name": "Clause 17 — Amounts Not Allowable under S.37",
            "statement": "The tax auditor must report amounts debited to profit and loss account that are not allowable as deductions under Section 37. Key items include: (a) expenditure incurred on CSR under Section 135 of Companies Act (not deductible per Explanation 2 to S.37(1)), (b) any penalty or fine for violation of any law, (c) expenditure incurred for any purpose which is an offence or prohibited by law, (d) expenditure on advertisement in any souvenir/brochure published by a political party. CSR expenditure must always be added back in the tax computation."
        },
        "clause_18_payments_to_related_parties": {
            "name": "Clause 18 — Payments to Related Parties under S.40A(2)(b)",
            "statement": "The tax auditor must report any expenditure or allowance in respect of which payment has been or is to be made to any person referred to in Section 40A(2)(b) — i.e., related parties including directors, partners, relatives of such persons, or any company/firm/association in which such person has substantial interest (20% or more). The auditor must report whether the expenditure is in excess of the fair market value of goods, services, or facilities. If so, the excess amount is disallowed. For the ExampleCo P&L, remuneration to KMP, purchases from and sales to KMP-controlled entities must be verified at arm's length."
        },
        "clause_20_depreciation": {
            "name": "Clause 20 — Depreciation under S.32",
            "statement": "The tax auditor must report depreciation allowable under S.32. Details include: (a) description of each asset or block of assets, (b) rate of depreciation, (c) actual cost or written down value, (d) additions/deductions during the year with dates, (e) depreciation allowable, (f) written down value at year end. The auditor must verify that depreciation rates comply with the Income Tax Act Schedule (which may differ from Companies Act rates), additional depreciation of 20% on new plant and machinery is correctly claimed where applicable, and that no depreciation is claimed on assets not put to use."
        },
        "clause_21_amounts_inadmissible_s40a_tds": {
            "name": "Clause 21 — Amounts Inadmissible under S.40(a) for TDS Non-deduction",
            "statement": "The tax auditor must report any amount debited to profit and loss on which tax has not been deducted or after deduction has not been paid on or before the due date. Under S.40(a)(ia), 30% of any sum payable to a resident on which TDS was deductible but not deducted or not deposited before the due date is disallowed. For payments to non-residents under S.40(a)(i), the entire amount is disallowed if TDS is not deducted. The auditor must verify TDS compliance on all payments including salaries (S.192), interest (S.194A), contractors (S.194C), rent (S.194I), professional fees (S.194J), and commission (S.194H)."
        },
        "clause_22_bad_debts": {
            "name": "Clause 22 — Bad Debts under S.36(1)(vii)",
            "statement": "The tax auditor must report any amount of bad debts written off during the year and claimed as a deduction. The amount must have been taken into account in computing income of the assessee of the previous year or an earlier year, or must represent money lent in the ordinary course of business of banking or money lending. The auditor must verify that bad debts are actually written off in the books and not merely provided for. A provision for doubtful debts is not deductible under S.36(1)(vii) but is deductible under S.36(1)(viia) only for banks and financial institutions."
        },
        "clause_23_msmed_interest": {
            "name": "Clause 23 — Interest on MSMED Delayed Payments",
            "statement": "The tax auditor must report particulars of interest payable or paid under the Micro, Small and Medium Enterprises Development Act, 2006 (MSMED Act). This includes: (a) principal amount remaining unpaid to any supplier at the end of each accounting year, (b) interest due thereon remaining unpaid at the end of each accounting year, (c) the amount of interest paid by the buyer in terms of S.16, (d) the amount of payment made to the supplier beyond the appointed day during each accounting year, (e) the amount of interest accrued and remaining unpaid at the end of each accounting year, (f) the amount of further interest remaining due and payable in succeeding years. This is particularly relevant as S.43B(h) (effective from April 2024) disallows deduction if MSME payments exceed 45 days."
        },
        "clause_26_payments_to_employees_s43b": {
            "name": "Clause 26 — Employee Benefit Payments and S.43B",
            "statement": "The tax auditor must report whether deductions from employees' salary towards PF, ESI, or other funds have been deposited within the prescribed due dates. Under S.36(1)(va), employer's contribution to PF/ESI is deductible only if deposited before the due date prescribed under the respective Acts (15th of following month for PF, 21st for ESI). Under S.43B, any sum payable by the employer by way of contribution to any provident fund or superannuation fund or gratuity fund or any other fund for the welfare of employees is deductible only in the year of actual payment. Failure to deposit within due dates results in disallowance and potential penal interest."
        },
        "clause_27_tds_tcs": {
            "name": "Clause 27 — TDS/TCS Compliance",
            "statement": "The tax auditor must furnish details of TDS deducted and TCS collected during the year — whether amounts have been deducted/collected at the correct rates and deposited to the Government account within prescribed time. Details must include: (a) section under which TDS/TCS was required, (b) rate applicable, (c) total amount of payment on which TDS/TCS was required, (d) total amount deducted/collected, (e) total amount deposited, (f) date of deposit. Late deposit attracts interest under S.201(1A) at 1% per month (from date of deduction to deposit) or 1.5% per month (if not deducted at all)."
        },
        "clause_29_cash_transactions": {
            "name": "Clause 29 — Cash Transaction Limits under S.269SS/269T",
            "statement": "The tax auditor must report whether loans or deposits or any specified sum exceeding Rs. 20,000 has been received or repaid otherwise than by account payee cheque/draft or electronic clearing system. Under S.269SS, no person shall take or accept from any other person any loan or deposit or any specified sum otherwise than by account payee cheque/draft or electronic transfer if the amount is Rs. 20,000 or more. Under S.269T, repayment of loan or deposit exceeding Rs. 20,000 must also be by the same mode. Contravention attracts penalty equal to the amount under S.271D/271E."
        },
        "clause_30_unexplained_income": {
            "name": "Clause 30 — Unexplained Credits/Investments under S.68-69D",
            "statement": "The tax auditor must report any amount credited to profit and loss account which falls within the provisions of S.68 (unexplained cash credits), S.69 (unexplained investments), S.69A (unexplained money), S.69B (amount of investments not fully disclosed), S.69C (unexplained expenditure), or S.69D (amount borrowed or repaid on hundi). Any such amounts are deemed income and taxable at 60% plus surcharge and cess (effective rate ~78.7%) with no deduction allowed for any expenditure or allowance against such income."
        },
        "clause_32_chapter_via_deductions": {
            "name": "Clause 32 — Deductions under Chapter VI-A",
            "statement": "The tax auditor must report all deductions claimed under Chapter VI-A of the Income Tax Act. This includes: S.80C (investments up to Rs. 1.5 lakh), S.80D (medical insurance), S.80G (donations), S.80GGB (contribution to political parties by companies), S.80IA/IB/IC (profits from infrastructure/industrial undertakings), S.80JJAA (additional employee cost), and any other applicable sections. The auditor must verify eligibility conditions for each deduction and that the aggregate deductions do not exceed gross total income. For companies, S.80G deductions are critical — CSR spend is not eligible for S.80G deduction."
        },
        "clause_44_gst_breakup": {
            "name": "Clause 44 — GST Reconciliation",
            "statement": "The tax auditor must report: (a) total expenditure incurred during the year, (b) expenditure in respect of entities registered under GST, (c) expenditure relating to entities not registered under GST, and (d) total expenditure on which GST input tax credit was availed, was not availed (eligible), and was not availed (ineligible). This reconciliation helps verify whether the company has correctly identified and claimed input tax credits and whether expenditures to unregistered dealers are properly accounted for."
        }
    },

    # ── 2. CARO 2020 ───────────────────────────────────────────────────
    "caro_2020": {
        "clause_i_fixed_assets": {
            "name": "CARO Clause (i) — Property, Plant & Equipment and Intangible Assets",
            "statement": "The auditor must report whether: (a) the company is maintaining proper records showing full particulars including quantitative details and situation of PPE and intangible assets, (b) these assets have been physically verified by management at reasonable intervals, material discrepancies noticed on such verification have been properly dealt with, (c) title deeds of all immovable properties (other than properties where the company is the lessee and the lease agreements are duly executed in favour of the lessee) disclosed in the financial statements are held in the name of the company. If not, provide details. (d) the company has revalued its PPE or intangible assets, whether by a registered valuer, and the amount of change. (e) any proceedings have been initiated or are pending against the company for holding any Benami property under the Benami Transactions (Prohibition) Act, 1988."
        },
        "clause_ii_inventory": {
            "name": "CARO Clause (ii) — Inventory",
            "statement": "The auditor must report whether: (a) physical verification of inventory has been conducted at reasonable intervals by the management, and whether any material discrepancies (10% or more in aggregate) were noticed and properly dealt with in the books of account, (b) during any point of time of the year, the company has been sanctioned working capital limits in excess of Rs. 5 crore from banks or financial institutions on the basis of security of current assets, and whether quarterly returns or statements filed by the company with such banks or financial institutions are in agreement with the books of account of the company."
        },
        "clause_iii_loans_advances": {
            "name": "CARO Clause (iii) — Loans, Investments, Guarantees, Security",
            "statement": "The auditor must report whether the company has made investments in, provided any guarantee or security, or granted any loans or advances in the nature of loans, secured or unsecured, to companies, firms, LLPs or other parties covered in the Register maintained under S.189 of Companies Act 2013. If so, report: (a) the aggregate amount during the year and balance outstanding, (b) terms and conditions including interest rate, (c) whether receipt of principal and interest is regular, (d) if overdue, the total amount overdue for more than 90 days and reasonable steps taken for recovery, (e) whether any loan granted has fallen due and has been renewed/extended or fresh loans granted to settle overdues, (f) whether the company has granted loans either repayable on demand or without specifying any terms of repayment."
        },
        "clause_iv_loans_to_directors": {
            "name": "CARO Clause (iv) — Compliance with S.185 and S.186",
            "statement": "The auditor must report whether the company has complied with provisions of S.185 (Loan to directors) and S.186 (Loan and investment by company) of Companies Act 2013. S.185 prohibits loans to directors, their partners, or relatives, with exceptions for housing/vehicle loans per company policy. S.186 restricts aggregate loans, guarantees, securities and investments to 60% of paid-up share capital + free reserves + securities premium, or 100% of free reserves, whichever is more. Board resolution required; special resolution if exceeding threshold."
        },
        "clause_v_deposits": {
            "name": "CARO Clause (v) — Deposits",
            "statement": "The auditor must report whether the company has accepted deposits under S.73-76 of Companies Act 2013 and the Companies (Acceptance of Deposits) Rules 2014. If so, whether directives issued by RBI and the provisions of S.73-76 have been complied with. If not, the nature of contraventions and amounts involved. Whether any order has been passed by NCLT or RBI and whether the company has complied with such orders."
        },
        "clause_vi_cost_records": {
            "name": "CARO Clause (vi) — Cost Records under S.148",
            "statement": "The auditor must report whether the Central Government has prescribed maintenance of cost records under S.148(1) for the products manufactured/services provided by the company, and whether such accounts and records have been so made and maintained. The Companies (Cost Records and Audit) Rules 2014 specify industries/products requiring cost records. Manufacturing companies producing goods covered under the rules (including hydraulic equipment/engineering goods) must maintain cost records."
        },
        "clause_vii_statutory_dues": {
            "name": "CARO Clause (vii) — Statutory Dues",
            "statement": "The auditor must report whether the company is regular in depositing undisputed statutory dues including Provident Fund, Employees' State Insurance, Income Tax, GST, Sales Tax, Customs Duty, Excise Duty, Cess, and any other material statutory dues with appropriate authorities. If not deposited on the due date, the extent of arrears of outstanding statutory dues as at the last day of the financial year for a period of more than 6 months from the date they became payable must be indicated. The auditor must also report details of disputed statutory dues that have not been deposited, along with the forum where the dispute is pending and the year to which the amount relates."
        },
        "clause_viii_undisclosed_income": {
            "name": "CARO Clause (viii) — Undisclosed Income",
            "statement": "The auditor must report whether any transactions not recorded in the books of account have been surrendered or disclosed as income during the year in the tax assessments under the Income Tax Act 1961. If so, whether the previously unrecorded income has been properly recorded in the books of account during the year."
        },
        "clause_ix_borrowing_default": {
            "name": "CARO Clause (ix) — Default in Repayment of Borrowings",
            "statement": "The auditor must report (a) whether the company has defaulted in repayment of loans or other borrowings or in the payment of interest thereon to any lender, the period and amount of default (only if default existed at the balance sheet date), (b) whether the company is a declared wilful defaulter by any bank or financial institution or other lender, (c) whether term loans were applied for the purpose for which they were obtained, and if not, report the amount of diversion, (d) whether funds raised on short term basis have been used for long term purposes, and (e) whether the company has taken any funds from any entity or person on account of or to meet obligations of its subsidiaries, associates, or JVs."
        },
        "clause_x_ipo_funds": {
            "name": "CARO Clause (x) — Application of IPO/Further Offering Funds",
            "statement": "The auditor must report whether money raised by way of initial public offer or further public offer (including debt instruments) have been applied for the purposes for which they were raised. If not, details with amount and reasons for not using such funds."
        },
        "clause_xi_fraud": {
            "name": "CARO Clause (xi) — Fraud",
            "statement": "The auditor must report (a) whether any fraud by the company or any fraud on the company has been noticed or reported during the year. If yes, the nature, amount involved, and parties involved. (b) Whether any report under S.143(12) of Companies Act has been filed by the auditors in Form ADT-4 with the Central Government. (c) Whether the auditor has considered whistle-blower complaints, if any, received during the year by the company."
        },
        "clause_xiii_related_party_transactions": {
            "name": "CARO Clause (xiii) — Related Party Transactions",
            "statement": "The auditor must report whether all transactions with related parties are in compliance with S.177 (Audit Committee approval) and S.188 (Related Party Transactions) of Companies Act 2013 and the details have been disclosed in the financial statements as required by the applicable accounting standards. Related party transactions must be at arm's length and in the ordinary course of business. Transactions exceeding prescribed thresholds under S.188 require Board resolution, and material transactions require ordinary resolution of shareholders. The auditor must verify that related party disclosures are complete and accurate."
        },
        "clause_xiv_internal_audit": {
            "name": "CARO Clause (xiv) — Internal Audit System",
            "statement": "The auditor must report whether the company has an internal audit system commensurate with the size and nature of its business. Under Rule 13 of Companies (Accounts) Rules 2014, internal audit is mandatory for every listed company and unlisted private companies with turnover >= Rs. 200 crore or outstanding loans/borrowings >= Rs. 100 crore. For other companies, the auditor must assess whether the voluntary internal audit system (if any) is adequate."
        },
        "clause_xv_non_cash_transactions": {
            "name": "CARO Clause (xv) — Non-Cash Transactions with Directors",
            "statement": "The auditor must report whether the company has entered into any non-cash transactions with directors or persons connected with them and whether provisions of S.192 of Companies Act 2013 have been complied with. S.192 requires that any non-cash transaction between a company and its directors (or connected persons) requires prior approval of shareholders by ordinary resolution. Non-compliance renders the transaction voidable."
        },
        "clause_xvii_cash_losses": {
            "name": "CARO Clause (xvii) — Cash Losses",
            "statement": "The auditor must report whether the company has incurred cash losses in the financial year and in the immediately preceding financial year. Cash losses are calculated as net profit/loss after tax plus non-cash charges (depreciation, amortisation, provisions) minus non-cash income. Cash losses indicate severe operational distress and are a critical going concern indicator."
        },
        "clause_xviii_auditor_resignation": {
            "name": "CARO Clause (xviii) — Auditor Resignation",
            "statement": "The auditor must report whether there has been any resignation of the statutory auditors during the year. If so, whether the auditor has taken into consideration the issues, objections, or concerns raised by the outgoing auditors. Auditor resignation mid-term is a red flag that may indicate disagreements with management over accounting treatment or discovery of irregularities."
        },
        "clause_xix_going_concern": {
            "name": "CARO Clause (xix) — Going Concern",
            "statement": "The auditor must report on the basis of the financial ratios, ageing and expected dates of realisation of financial assets and payment of financial liabilities, other information accompanying the financial statements, the auditor's knowledge of the Board of Directors and management plans, whether in the auditor's opinion there is any material uncertainty relating to the company's ability to meet its liabilities existing at the date of the balance sheet as and when they fall due within a period of one year from the balance sheet date."
        },
        "clause_xx_csr": {
            "name": "CARO Clause (xx) — CSR Unspent Amount",
            "statement": "The auditor must report whether the company is required to spend under S.135 of Companies Act and if so, whether the amount has been spent and the shortfall, if any. For ongoing projects, whether the unspent amount has been transferred to a special account within 30 days of the end of the financial year in compliance with S.135(6). For other than ongoing projects, whether the unspent amount has been transferred to a Fund specified in Schedule VII within 6 months of the end of the financial year. The company must disclose the reasons for any shortfall in the Board's Report."
        },
        "clause_xxi_subsidiary_qualifications": {
            "name": "CARO Clause (xxi) — Qualifications in Subsidiary Audit Reports",
            "statement": "The auditor must report whether there have been any qualifications or adverse remarks by the respective auditors in the Companies (Auditor's Report) Order (CARO) reports of the companies included in the consolidated financial statements. If so, details of the qualifications. This is relevant when the parent company prepares consolidated financial statements and must incorporate subsidiary audit findings."
        }
    },

    # ── 3. COMPANIES ACT — FINANCIAL STATEMENTS ─────────────────────────
    "companies_act_financial_statements": {
        "s128_books_of_account": {
            "name": "Section 128 — Books of Account",
            "statement": "Every company shall prepare and keep at its registered office books of account and other relevant books and papers and financial statement for every financial year which give a true and fair view of the state of affairs of the company. Books must be kept on accrual basis and according to the double entry system of accounting. Books must be preserved for not less than 8 financial years immediately preceding the current year, or from the date of incorporation if the company is less than 8 years old. Failure attracts imprisonment up to one year and/or fine Rs. 50,000 to Rs. 5,00,000 for officers in default."
        },
        "s129_financial_statement": {
            "name": "Section 129 — Financial Statement",
            "statement": "Financial statements shall give a true and fair view of the state of affairs and comply with accounting standards notified under S.133. Statements must be in Schedule III format. Any deviation from accounting standards must be disclosed with reasons and financial effects. If a company has subsidiaries/associates/JVs, it must prepare consolidated financial statements in addition to standalone. Financial statements must be laid before the AGM."
        },
        "s134_board_report": {
            "name": "Section 134 — Financial Statement, Board's Report",
            "statement": "Financial statements must be approved by the Board and signed by the chairperson (if authorized) or by two directors (one being MD) and by CEO, CFO, and Company Secretary where appointed. The Board's report must include: (a) web address where annual return is placed, (b) number of Board meetings, (c) Directors' Responsibility Statement (DRS) confirming applicable accounting standards followed, consistent policies, reasonable estimates, adequate internal controls, going concern basis), (d) details of fraud reported under S.143(12), (e) company policy on directors' appointment, remuneration, (f) explanations for qualifications in auditor's report, (g) CSR report, (h) particulars of loans/guarantees under S.186, (i) RPTs under S.188."
        },
        "s135_csr": {
            "name": "Section 135 — Corporate Social Responsibility",
            "statement": "Every company having net worth >= Rs. 500 crore, or turnover >= Rs. 1,000 crore, or net profit >= Rs. 5 crore during immediately preceding FY shall constitute a CSR Committee of 3+ directors (at least 1 independent, if applicable). The company must spend at least 2% of average net profits of 3 immediately preceding FYs on CSR activities per Schedule VII. If the company fails to spend, the Board must specify reasons in its report. Unspent amounts on ongoing projects must be transferred to Unspent CSR Account within 30 days of FY end. Unspent amounts on other projects must be transferred to Schedule VII fund within 6 months. Penalty for non-compliance: twice the unspent amount or Rs. 1 crore, whichever is less; officers: 1/10th of unspent amount or Rs. 2 lakhs."
        },
        "s143_auditor_powers_duties": {
            "name": "Section 143 — Powers and Duties of Auditors",
            "statement": "The auditor must report whether financial statements give a true and fair view, whether proper books of account have been maintained, whether the auditor has obtained all information and explanations necessary, whether the company has adequate internal financial controls with reference to financial statements and their operating effectiveness, and whether the directors are disqualified under S.164(2). If the auditor believes fraud of Rs. 1 crore or above has been committed, report to Central Government in Form ADT-4 within 60 days. For fraud below Rs. 1 crore, report to Audit Committee or Board within 2 days of knowledge."
        },
        "s177_audit_committee": {
            "name": "Section 177 — Audit Committee",
            "statement": "Every listed public company and prescribed class of companies shall constitute an Audit Committee of minimum 3 directors with independent directors forming a majority, including at least one member with financial expertise. The Audit Committee shall: oversee financial reporting, recommend auditor appointment/remuneration, approve RPTs, review quarterly/annual financial statements, evaluate internal controls and risk management, review whistle-blower mechanism. All RPTs must have prior Audit Committee approval. The Committee has authority to investigate any matter in its terms of reference and access to information from any employee."
        },
        "s188_related_party_transactions": {
            "name": "Section 188 — Related Party Transactions",
            "statement": "No company shall enter into any contract or arrangement with a related party with respect to: (a) sale/purchase/supply of goods, (b) selling/buying property, (c) leasing of property, (d) availing/rendering services, (e) appointment to office or place of profit, (f) underwriting subscription of securities, unless prior consent of the Board is obtained by resolution at Board meeting. If the paid-up share capital is Rs. 10 crore or more, the transaction exceeds prescribed thresholds, or the related party is a director's relative, shareholders' approval by ordinary resolution is required. Thresholds: sale/purchase > 10% of turnover; selling/buying property > 10% of net worth; leasing > 10% of net worth or turnover; services > 10% of turnover; appointment with remuneration > Rs. 2.5 lakhs per month."
        },
        "s197_managerial_remuneration": {
            "name": "Section 197 and Schedule V — Managerial Remuneration",
            "statement": "Total managerial remuneration payable by a public company to its directors (including MD and WTD) shall not exceed 11% of net profit in any financial year. For MD/WTD: maximum 5% (one person) or 10% (all). For directors other than MD/WTD: maximum 1% (if MD/WTD exists) or 3%. Private companies are not subject to S.197 limits but must still obtain proper Board approvals. Where the company has inadequate or no profits, Schedule V limits apply: maximum Rs. 30 lakhs per year for companies with effective capital up to Rs. 5 crore (increasing with capital). Central Government approval required for payment in excess."
        },
        "s447_fraud_definition": {
            "name": "Section 447 — Punishment for Fraud",
            "statement": "Fraud includes any act, omission, concealment of any fact, or abuse of position committed by any person with intent to deceive, gain undue advantage, or injure the interests of the company, shareholders, creditors, or any other person. Punishment: imprisonment for 6 months to 10 years plus fine not less than the amount involved but up to 3x the amount. Where fraud involves public interest: minimum 3 years imprisonment. 'Fraud' is broadly defined and covers falsification of financial statements, misrepresentation of material facts, siphoning of funds, and deliberate non-compliance with accounting standards."
        }
    },

    # ── 4. COMPANIES ACT — GOVERNANCE ───────────────────────────────────
    "companies_act_governance": {
        "s149_board_composition": {
            "name": "Section 149 — Board Composition",
            "statement": "Every company shall have a Board of Directors with a minimum of 3 directors for public companies and 2 for private companies. Every listed public company shall have at least 1/3 of total directors as independent directors. Certain prescribed classes of unlisted public companies must also have independent directors. At least one woman director required for listed companies and companies with paid-up capital >= Rs. 100 crore or turnover >= Rs. 300 crore. Maximum 15 directors (more by special resolution)."
        },
        "s164_disqualification": {
            "name": "Section 164 — Disqualification of Directors",
            "statement": "A person shall not be appointed as director if: (a) found of unsound mind by court, (b) undischarged insolvent, (c) applied to be adjudicated as insolvent, (d) convicted of an offence and sentenced to imprisonment for >= 6 months (within preceding 5 years), (e) order of court/tribunal restraining, (f) has not paid any calls on shares for 6 months, (g) convicted under S.188 (RPTs). Under S.164(2), no person who is or has been director of a company which has not filed financial statements/annual returns for 3 continuous FYs, or has failed to repay deposits/debentures/interest/pay dividends, shall be eligible for appointment as director for 5 years from such default."
        },
        "s166_duties_of_directors": {
            "name": "Section 166 — Duties of Directors",
            "statement": "A director shall: (a) act in accordance with the articles, (b) act in good faith to promote objects of the company for benefit of members as a whole and in best interests of the company, employees, shareholders, community, and environment, (c) exercise due and reasonable care, skill, and diligence, (d) not involve in situations where there is direct or indirect conflict of interest with the company, (e) not achieve or attempt to achieve any undue gain or advantage, (f) not assign his office. Contravention: fine Rs. 1 lakh to Rs. 5 lakhs."
        },
        "s184_disclosure_of_interest": {
            "name": "Section 184 — Disclosure of Interest by Director",
            "statement": "Every director shall at the first meeting of the Board in which he participates as director, and at the first meeting of the Board in every financial year, disclose his concern or interest in any company, body corporate, firm, or other association. A director who is directly or indirectly interested in any contract or arrangement shall disclose the nature of his interest at the Board meeting. An interested director shall not participate in the discussion or vote on such contract or arrangement. Contravention: imprisonment up to 1 year and/or fine Rs. 50,000 to Rs. 1,00,000."
        },
        "s185_loans_to_directors": {
            "name": "Section 185 — Loans to Directors",
            "statement": "No company shall directly or indirectly advance any loan to or give any guarantee or provide any security in connection with a loan to: (a) any director of the company or a director of a holding company, (b) any partner or relative of such director, (c) any firm in which such director or relative is a partner, (d) any private company of which such director is a director or member, (e) any body corporate at a general meeting of which not less than 25% of total voting power may be exercised by such director. Exceptions: loans to MDs/WTDs as part of employment conditions, loans in ordinary course of business if interest >= bank rate, inter-corporate loans/investments with prior special resolution. Contravention: imprisonment up to 6 months and/or fine Rs. 5 lakhs to Rs. 25 lakhs on the company; imprisonment up to 6 months and/or fine Rs. 5 lakhs to Rs. 25 lakhs on defaulting director."
        },
        "s186_loans_and_investments": {
            "name": "Section 186 — Loan and Investment by Company",
            "statement": "No company shall directly or indirectly: (a) give any loan to any person or body corporate, (b) give any guarantee or provide security in connection with a loan, (c) acquire securities of any other body corporate, exceeding 60% of its paid-up share capital + free reserves + securities premium, or 100% of its free reserves + securities premium, whichever is more, unless prior approval of members by special resolution is obtained. All investments, guarantees, or security must be authorized by Board resolution and the rate of interest charged shall not be lower than the prevailing yield of government securities. Full disclosure of investments, loans, guarantees, and securities must be made in the financial statements."
        },
        "s204_secretarial_audit": {
            "name": "Section 204 — Secretarial Audit",
            "statement": "Every listed company and company belonging to a class of companies with paid-up share capital >= Rs. 50 crore or turnover >= Rs. 250 crore shall annex with its Board's report a secretarial audit report in Form MR-3 given by a company secretary in practice. The secretarial audit report shall be prepared in accordance with CSAS-4 and shall cover compliance with Companies Act, SEBI regulations (if listed), Depositories Act, FEMA, secretarial standards SS-1 and SS-2, and other applicable sector-specific laws."
        }
    },

    # ── 5. ICAI AUDITING STANDARDS ──────────────────────────────────────
    "icai_auditing_standards": {
        "sa_200_overall_objectives": {
            "name": "SA 200 — Overall Objectives of the Independent Auditor",
            "statement": "The auditor shall obtain reasonable assurance about whether the financial statements as a whole are free from material misstatement, whether due to fraud or error. Reasonable assurance is a high but not absolute level of assurance. The auditor shall plan and perform the audit with professional skepticism, recognizing that circumstances may exist that cause the financial statements to be materially misstated. The auditor shall exercise professional judgment in planning and performing the audit."
        },
        "sa_240_fraud": {
            "name": "SA 240 — Auditor's Responsibilities Relating to Fraud",
            "statement": "The auditor must maintain professional skepticism throughout the audit, recognizing the possibility that a material misstatement due to fraud could exist notwithstanding the auditor's past experience. The auditor shall presume that there are risks of fraud in revenue recognition and shall treat these as significant risks. The auditor shall consider the risk of management override of controls. Procedures include: (a) testing appropriateness of journal entries and other adjustments, (b) reviewing accounting estimates for management bias, (c) evaluating business rationale of significant unusual transactions. The auditor must communicate any identified fraud to management, those charged with governance, and regulatory authorities as appropriate."
        },
        "sa_250_laws_and_regulations": {
            "name": "SA 250 — Laws and Regulations in an Audit",
            "statement": "The auditor shall obtain sufficient appropriate audit evidence regarding compliance with the provisions of those laws and regulations generally recognized to have a direct effect on the determination of material amounts and disclosures in the financial statements (e.g., tax laws, labor laws). The auditor shall perform audit procedures to identify instances of non-compliance with other laws and regulations that may have a material effect on the financial statements. If the auditor becomes aware of non-compliance or suspected non-compliance with laws and regulations (NOCLAR), the auditor shall report the matter to management, those charged with governance, and consider the implications for the audit report."
        },
        "sa_315_risk_assessment": {
            "name": "SA 315 — Identifying and Assessing Risks of Material Misstatement",
            "statement": "The auditor shall identify and assess the risks of material misstatement at the financial statement level and the assertion level for classes of transactions, account balances, and disclosures. The auditor shall obtain an understanding of the entity and its environment including: (a) industry, regulatory, and other external factors, (b) the entity's nature (operations, governance, ownership, investments, financing, accounting policies), (c) the entity's selection and application of accounting policies, (d) the entity's internal control relevant to the audit. The auditor shall determine whether any of the risks identified are significant risks requiring special audit consideration."
        },
        "sa_540_accounting_estimates": {
            "name": "SA 540 — Auditing Accounting Estimates Including Fair Value",
            "statement": "The auditor shall obtain sufficient appropriate audit evidence about whether accounting estimates, including fair value estimates, in the financial statements are reasonable and related disclosures are adequate. This includes evaluating: (a) how management identified transactions, events, and conditions that give rise to the need for accounting estimates, (b) how management made the accounting estimate, the data on which it is based, and assumptions used, (c) whether management has used an expert, (d) whether there are indicators of possible management bias. Key estimates in financial statements include: actuarial valuations for gratuity/leave (discount rate, salary escalation, withdrawal rate), fair value of Level 2/3 financial instruments, impairment assessments, provisions for contingent liabilities, useful life of assets."
        },
        "sa_550_related_parties": {
            "name": "SA 550 — Related Parties",
            "statement": "The auditor shall perform audit procedures to identify, assess and respond to the risks of material misstatement arising from the entity's failure to appropriately account for or disclose related party relationships, transactions, and balances. The auditor shall: (a) inquire of management regarding related party relationships and transactions, (b) remain alert for related party information when reviewing records, (c) share related party information with the engagement team, (d) evaluate whether identified RPTs have been properly accounted for and disclosed per applicable accounting framework (Ind AS 24), (e) evaluate whether RPTs outside the entity's normal course of business indicate fraud risk. Significant RPTs outside the normal course of business require the auditor to inspect underlying contracts and evaluate business rationale."
        },
        "sa_570_going_concern": {
            "name": "SA 570 — Going Concern",
            "statement": "The auditor shall evaluate whether there is a material uncertainty related to events or conditions that may cast significant doubt on the entity's ability to continue as a going concern. Indicators include: (a) net liability or net current liability position, (b) adverse key financial ratios, (c) substantial operating losses, (d) arrears or discontinuance of dividends, (e) inability to pay creditors on due dates, (f) inability to comply with terms of loan agreements, (g) change from credit to cash-on-delivery transactions with suppliers, (h) loss of key management without replacement, (i) loss of major market, license, or principal supplier. If material uncertainty exists and adequate disclosures are made, the auditor includes an Emphasis of Matter paragraph. If disclosures are inadequate, the auditor expresses a qualified or adverse opinion."
        },
        "sa_700_forming_opinion": {
            "name": "SA 700/701/705/706 — Audit Opinion and Reporting",
            "statement": "The auditor shall form an opinion on whether the financial statements are prepared, in all material respects, in accordance with the applicable financial reporting framework. SA 700 governs unmodified opinions. SA 705 covers modifications: (a) qualified opinion — material but not pervasive misstatement/inability to obtain evidence, (b) adverse opinion — material and pervasive misstatement, (c) disclaimer of opinion — material and pervasive inability to obtain evidence. SA 706 allows the auditor to draw attention via Emphasis of Matter (material uncertainty, significant related party transactions) or Other Matter paragraphs. SA 701 requires communication of Key Audit Matters for listed entities."
        }
    },

    # ── 6. FORENSIC ACCOUNTING STANDARDS ────────────────────────────────
    "icai_fais_2023": {
        "fais_100_framework": {
            "name": "FAIS 100 — Forensic Accounting Framework",
            "statement": "Forensic accounting involves the application of accounting, auditing, and investigative skills to examine financial statements and transactions for use in legal proceedings. The framework establishes that forensic accounting is distinct from statutory auditing — while auditing provides reasonable assurance, forensic accounting aims to detect fraud and provide litigation support. Key concepts include: fraud triangle (opportunity, pressure, rationalization), fraud diamond (adds capability), and the distinction between occupational fraud (by employees), management fraud (by executives), and external fraud (by third parties)."
        },
        "fais_310_evidence_collection": {
            "name": "FAIS 310 — Evidence Collection and Preservation",
            "statement": "Forensic evidence must be collected, preserved, and documented to ensure admissibility in legal proceedings. The chain of custody must be maintained at all times. Evidence categories include: (a) documentary evidence (invoices, contracts, bank statements, journal entries), (b) electronic evidence (emails, digital records, system logs, metadata), (c) physical evidence, (d) testimonial evidence (witness statements, confessions). The 5W approach must be applied: What happened, Who is involved, When did it occur, Where did it occur, Why did it happen (motive). All evidence must be relevant, reliable, and obtained through lawful means."
        },
        "fais_320_data_analytics": {
            "name": "FAIS 320 — Data Analytics in Forensic Accounting",
            "statement": "Data analytics techniques for fraud detection include: (a) Benford's Law analysis — testing the distribution of leading digits in financial data against expected frequencies; deviations indicate potential manipulation, (b) duplicate payment detection — identifying duplicate invoices, amounts, or vendors, (c) trend analysis — identifying unusual patterns in revenue, expenses, or inventory over time, (d) ratio analysis — comparing financial ratios against industry benchmarks and historical trends, (e) journal entry testing — identifying unusual entries (round amounts, year-end entries, entries by unauthorized users, entries without descriptions), (f) vendor/customer analysis — identifying shell companies, circular transactions, or fictitious entities. These techniques should be applied to the P&L line items, particularly revenue recognition, inventory valuation, and related party transactions."
        },
        "fais_red_flags_financial_statements": {
            "name": "FAIS — Financial Statement Red Flags",
            "statement": "Red flags in financial statements that warrant forensic investigation include: (a) revenue growth inconsistent with industry or cash flows, (b) significant related party transactions especially near year-end, (c) unusual increase in work-in-progress or inventory without corresponding revenue growth, (d) frequent changes in accounting policies or estimates, (e) round-number journal entries or entries without supporting documentation, (f) post-closing adjustments, (g) receivables growing faster than revenue, (h) aggressive revenue recognition (channel stuffing, bill-and-hold, premature recognition), (i) understated liabilities or provisions, (j) unexplained or undocumented fair value gains, (k) CSR expenses routed through related party foundations, (l) large cash transactions, (m) significant one-time or unusual items near year-end."
        }
    },

    # ── 7. EMPLOYEE BENEFIT LAWS ────────────────────────────────────────
    "employee_benefit_laws": {
        "epf_act_1952": {
            "name": "EPF Act, 1952 — Provident Fund Contributions",
            "statement": "Under S.6 of the EPF Act, the employer must contribute 12% of basic wages + dearness allowance to the Employees' Provident Fund for every employee earning up to Rs. 15,000 per month (statutory ceiling). The employee also contributes 12%. The employer's contribution is split: 8.33% to Employees' Pension Scheme (EPS) and 3.67% to EPF. Contributions must be deposited by the 15th of the following month. Under S.7A, the Commissioner can determine the amount due from the employer. Under S.14B, penalty for delayed payment: damages at rates ranging from 5% to 25% per annum depending on the period of delay. The employer must maintain records and file monthly returns."
        },
        "esi_act_1948": {
            "name": "ESI Act, 1948 — Employee State Insurance",
            "statement": "Under S.39 of the ESI Act, employers must contribute 3.25% and employees 0.75% of wages for employees earning up to Rs. 21,000 per month. ESI is applicable to factories employing 10 or more persons and certain establishments. Contributions must be deposited by the 15th of the following month. Under S.85, penalty for non-compliance includes imprisonment up to 2 years and/or fine up to Rs. 5,000. The employer must maintain records (Form 6 — Register of Employees), file half-yearly returns, and issue contribution cards."
        },
        "payment_of_gratuity_act_1972": {
            "name": "Payment of Gratuity Act, 1972",
            "statement": "Under S.4, every employee who has completed 5 years of continuous service (4 years in case of death or disablement) is entitled to gratuity at the rate of 15 days' wages for every completed year of service (or part thereof exceeding 6 months), subject to a maximum of Rs. 25 lakhs (enhanced from Rs. 20 lakhs effective March 2024). The gratuity obligation may be funded through a recognized gratuity fund (e.g., LIC Group Gratuity Scheme) or remain unfunded. Under Ind AS 19, the defined benefit obligation must be measured using the Projected Unit Credit Method (PUCM) with actuarial valuations at each reporting date. Actuarial gains and losses must be recognized in Other Comprehensive Income (OCI). Key assumptions: discount rate (based on government bond yields), salary escalation rate, withdrawal rate, mortality rate."
        },
        "payment_of_bonus_act_1965": {
            "name": "Payment of Bonus Act, 1965",
            "statement": "Under S.10, every employer shall pay minimum bonus of 8.33% of salary/wage earned during the accounting year or Rs. 100, whichever is higher. Under S.11, the maximum bonus is 20% of salary/wage. Bonus is payable to every employee earning up to Rs. 21,000 per month. Under S.12, allocable surplus is computed as 60% (67% for banking) of available surplus. Available surplus = gross profit minus depreciation, direct taxes, and prior year set-on/set-off. The employer must maintain records (Form A-D), calculate allocable surplus, and pay bonus within 8 months of close of accounting year."
        },
        "ind_as_19_employee_benefits": {
            "name": "Ind AS 19 — Employee Benefits (Accounting Standard)",
            "statement": "Ind AS 19 requires recognition of: (a) short-term employee benefits (salaries, wages, social security, paid leave, bonus, profit sharing) — recognized as expense when employee renders service, (b) post-employment benefits — defined contribution plans (PF) recognized as expense when contributions are due; defined benefit plans (gratuity, pension) recognized based on actuarial valuation using Projected Unit Credit Method. For defined benefit plans: current service cost and net interest recognized in P&L; remeasurements (actuarial gains/losses, return on plan assets excluding net interest) recognized in OCI and never reclassified to P&L. Required disclosures: reconciliation of opening and closing balances, principal actuarial assumptions (discount rate, salary increase, mortality, withdrawal), sensitivity analysis, expected contributions, maturity profile of defined benefit obligation."
        }
    },

    # ── 8. CGST ACT 2017 ───────────────────────────────────────────────
    "cgst_act_2017": {
        "s16_input_tax_credit": {
            "name": "S.16 — Input Tax Credit Conditions",
            "statement": "A registered person shall be entitled to take credit of input tax charged on supply of goods or services used in the course or furtherance of business subject to conditions: (a) possession of tax invoice or debit note, (b) goods or services have been received, (c) tax charged has been actually paid to the Government, (d) return under S.39 has been furnished. ITC must be claimed within the time limit prescribed (currently the 30th November of the year following the FY to which the invoice pertains, or the date of filing the annual return, whichever is earlier). ITC cannot be claimed on invoices not reflected in GSTR-2B. Excess ITC availed must be reversed with interest at 18% per annum."
        },
        "s17_5_blocked_credits": {
            "name": "S.17(5) — Blocked Input Tax Credits",
            "statement": "Input tax credit shall NOT be available for: (a) motor vehicles and conveyances (with exceptions for transportation/training/insurance), (b) food and beverages, outdoor catering, beauty treatment, health services, cosmetic/plastic surgery (with exceptions), (c) membership of club, health centre, fitness centre, (d) rent-a-cab, life/health insurance (with exceptions), (e) travel benefits to employees on vacation, (f) works contract services for construction of immovable property (except plant and machinery), (g) goods/services for construction of immovable property on own account, (h) goods/services on which tax has been paid under composition scheme, (i) goods/services used for personal consumption, (j) goods lost, stolen, destroyed, written off, disposed by way of gift or free samples."
        },
        "s31_tax_invoice": {
            "name": "S.31 — Tax Invoice Requirements",
            "statement": "A registered person supplying taxable goods/services shall issue a tax invoice showing: (a) name, address and GSTIN of supplier, (b) consecutive serial number, (c) date of issue, (d) name, address and GSTIN/UIN of recipient (if registered), (e) HSN code of goods / SAC of services, (f) description of goods/services, (g) quantity and unit, (h) value of supply, (i) taxable value considering discount, (j) rate of tax (CGST, SGST, IGST), (k) amount of tax, (l) place of supply, (m) address of delivery, (n) signature. E-invoicing (Invoice Registration Portal) is mandatory for businesses with aggregate turnover exceeding Rs. 5 crore."
        },
        "s44_annual_return": {
            "name": "S.44 — Annual Return (GSTR-9) and Reconciliation (GSTR-9C)",
            "statement": "Every registered person shall furnish an annual return (GSTR-9) for every financial year on or before 31st December following the end of such financial year. GSTR-9 includes: details of outward and inward supplies, tax paid, input tax credit availed and reversed, HSN-wise summary of outward supplies, HSN-wise summary of inward supplies. GSTR-9C (reconciliation statement) is a self-certified reconciliation between GSTR-9 and audited annual financial statements — mandatory for registered persons with aggregate turnover exceeding Rs. 5 crore. Key reconciliations: turnover per books vs. turnover per returns, ITC per books vs. ITC as per returns, tax payable and tax paid."
        },
        "reverse_charge": {
            "name": "S.9(3)/9(4) — Reverse Charge Mechanism",
            "statement": "Under S.9(3), the Government may specify categories of supply of goods or services where the tax shall be paid on reverse charge basis by the recipient. Notified categories include: legal services from an individual advocate, goods transport agency (GTA) services, services by author/music composer/artist, import of services, services by director to the company. Under S.9(4), tax on supply of taxable goods or services by an unregistered supplier to a registered person shall be paid by the recipient on reverse charge basis. The recipient must issue a self-invoice, pay tax under reverse charge, and can claim ITC on such payment."
        }
    },

    # ── 9. MSMED ACT 2006 ──────────────────────────────────────────────
    "msmed_act_2006": {
        "s15_payment_obligation": {
            "name": "S.15 — Buyer's Liability to Make Payment",
            "statement": "Where any supplier supplies any goods or renders any services to any buyer, the buyer shall make payment therefor on or before the date agreed upon between him and the supplier in writing or, where there is no agreement, before the appointed day (the day following immediately after the expiry of the period of fifteen days from the day of acceptance of goods/services). In no case shall the period agreed upon between the buyer and the supplier exceed 45 days from the day of acceptance or deemed acceptance. This is a strict statutory requirement applicable to all buyers (including companies) purchasing from MSMEs."
        },
        "s16_interest_on_delayed_payment": {
            "name": "S.16 — Interest on Delayed Payments",
            "statement": "Where any buyer fails to make payment of the amount to the supplier as required under S.15, the buyer shall, notwithstanding anything contained in any agreement, be liable to pay compound interest with monthly rests to the supplier on that amount from the appointed day at three times the bank rate notified by the Reserve Bank of India. This interest is mandatory and cannot be waived by agreement between the parties. The buyer cannot claim deduction for this interest payment under the Income Tax Act."
        },
        "s22_disclosure_requirements": {
            "name": "S.22 — Disclosure in Annual Statement of Accounts",
            "statement": "Every buyer shall, within the period as may be prescribed, submit to the prescribed authority a return showing: (a) the principal amount and the interest due thereon remaining unpaid to any supplier as at the end of each accounting year, (b) the interest paid to each supplier under S.16 along with the amounts of payment made beyond the appointed day, (c) the amount of interest due and payable for the period of delay in making payment (which have been paid but beyond the appointed day), and (d) the amount of interest accrued and remaining unpaid at the end of each accounting year, and (e) the amount of further interest remaining due and payable even in the succeeding years. These disclosures must be made in the financial statements as prescribed by the accounting standards."
        },
        "s43b_h_it_act": {
            "name": "S.43B(h) IT Act — Disallowance for MSME Delayed Payments",
            "statement": "With effect from April 1, 2024 (applicable from AY 2024-25), Section 43B(h) of the Income Tax Act provides that any sum payable by the assessee to a micro or small enterprise beyond the time limit specified in Section 15 of the MSMED Act 2006 shall be allowed as a deduction only in the previous year in which such sum is actually paid. This means: if payment to an MSME supplier is not made within 45 days (or the agreed period, whichever is earlier, but not exceeding 45 days), the deduction is disallowed in the year of accrual and allowed only in the year of actual payment. This has a significant impact on tax planning and cash flow management for buyers of MSME goods and services."
        }
    },

    # ── 10. FEMA — EXPORT COMPLIANCE ───────────────────────────────────
    "fema_export_compliance": {
        "export_realization": {
            "name": "FEMA — Export Proceeds Realization",
            "statement": "Under FEMA and RBI Master Direction on Export of Goods and Services, every exporter must realize and repatriate the full value of goods or services exported to India within 9 months from the date of export (15 months for units in SEZ). The export value must be declared in the Shipping Bill / Bill of Export filed with Customs. Any write-off of unrealized export proceeds requires prior RBI approval if exceeding prescribed limits. The Authorized Dealer bank monitors realization through the EDPMS (Export Data Processing and Monitoring System). Non-realization attracts penalties under S.13 of FEMA."
        },
        "softex_brc": {
            "name": "FEMA — SOFTEX/BRC Requirements",
            "statement": "For physical exports, the exporter must file a Shipping Bill with Customs and obtain a Bank Realization Certificate (BRC) from the Authorized Dealer bank upon realization of export proceeds. For software exports, SOFTEX form must be filed. The BRC serves as proof that export proceeds have been realized in India. All export documents (invoice, bill of lading, packing list, Shipping Bill, BRC) must be maintained for a minimum of 5 years. Non-compliance attracts action under FEMA including compounding of contravention."
        },
        "duty_drawback": {
            "name": "Customs Act — Duty Drawback",
            "statement": "Under S.75 of the Customs Act 1962, duty drawback is allowed on re-export of imported goods or on export of goods manufactured from imported materials. Drawback rates are fixed by the Government through notifications. The exporter must file a drawback claim with Customs at the time of export. The claim must be supported by proper documentation: Shipping Bill, invoice, Bank Realization Certificate. Drawback must be recognized as income in the year of export. Under the Income Tax Act, duty drawback received is taxable as business income. Fraudulent drawback claims attract penalties under S.76 of Customs Act and prosecution under S.135."
        },
        "meis_rodtep": {
            "name": "Foreign Trade Policy — MEIS/RoDTEP Scheme",
            "statement": "The Merchandise Exports from India Scheme (MEIS) provided duty credit scrips based on FOB value of exports, which could be used for payment of customs duties. MEIS has been replaced by RoDTEP (Remission of Duties and Taxes on Exported Products) effective January 1, 2021. RoDTEP provides refund of embedded taxes and duties not refunded through other mechanisms. Income from MEIS/RoDTEP scrips is taxable as business income. If MEIS scrips are sold at a loss, the loss is recognized in the P&L. The company must maintain proper records of scrips received, utilized, and outstanding."
        }
    },

    # ── 11. INDIAN ACCOUNTING STANDARDS ─────────────────────────────────
    "ind_as_accounting_standards": {
        "ind_as_1_presentation": {
            "name": "Ind AS 1 — Presentation of Financial Statements",
            "statement": "Financial statements shall present fairly the financial position, financial performance, and cash flows of an entity. Fair presentation requires faithful representation of the effects of transactions, events, and conditions in accordance with the definitions and recognition criteria for assets, liabilities, income, and expenses. The entity must present a complete set of financial statements: (a) Balance Sheet, (b) Statement of Profit and Loss, (c) Statement of Changes in Equity, (d) Statement of Cash Flows, (e) Notes. Comparative information for the preceding period must be presented. The entity must assess its ability to continue as a going concern."
        },
        "ind_as_2_inventories": {
            "name": "Ind AS 2 — Inventories",
            "statement": "Inventories shall be measured at the lower of cost and net realizable value (NRV). Cost includes: purchase cost, conversion costs (direct labor, production overheads), and other costs incurred in bringing inventories to their present location and condition. Cost formulas: FIFO or weighted average cost. LIFO is NOT permitted under Ind AS. NRV is the estimated selling price less estimated costs of completion and estimated costs to sell. Inventories must be written down to NRV on an item-by-item basis (or by group if items relate to the same product line). Write-downs to NRV are recognized as expense in the period. Reversal of write-down is recognized as reduction of expense in the period of reversal."
        },
        "ind_as_12_income_taxes": {
            "name": "Ind AS 12 — Income Taxes",
            "statement": "Current tax for the current and prior periods shall be measured at the amount expected to be paid to (or recovered from) tax authorities using the tax rates enacted or substantively enacted by the end of the reporting period. Deferred tax shall be recognized for all temporary differences between the carrying amount of an asset/liability and its tax base. Deferred tax assets shall be recognized for unused tax losses and tax credits to the extent that it is probable that future taxable profit will be available. Deferred tax must be measured at the tax rates expected to apply in the period of reversal. Current and deferred tax shall be recognized in P&L except to the extent it relates to items recognized in OCI or directly in equity. The company must disclose the tax reconciliation showing the relationship between tax expense and accounting profit."
        },
        "ind_as_16_ppe": {
            "name": "Ind AS 16 — Property, Plant and Equipment",
            "statement": "An item of PPE shall be recognized as an asset if: (a) it is probable that future economic benefits will flow to the entity, and (b) the cost can be measured reliably. PPE shall be measured at cost less accumulated depreciation and accumulated impairment losses. Cost includes purchase price, import duties (non-refundable), directly attributable costs of bringing the asset to working condition. Subsequent costs are capitalized only if recognition criteria are met. Each significant part of an item of PPE must be depreciated separately (component accounting). Depreciation method must reflect the pattern of consumption of economic benefits. Useful life must be reviewed at least at each financial year-end. Residual value must also be reviewed annually."
        },
        "ind_as_24_related_parties": {
            "name": "Ind AS 24 — Related Party Disclosures",
            "statement": "Relationships between a parent and its subsidiaries shall be disclosed irrespective of whether there have been transactions. The entity must disclose: (a) the name of the parent and the ultimate controlling party, (b) key management personnel compensation (in total and by category: short-term benefits, post-employment benefits, other long-term benefits, termination benefits, share-based payment), (c) details of transactions with each related party: nature of relationship, nature of transactions, amount of transactions, amount of outstanding balances (including commitments), terms and conditions (secured/unsecured, guarantees), provision for doubtful debts, expense recognized for bad/doubtful debts. Related parties include: parent, subsidiaries, associates, JVs, KMP, close family members of KMP, entities controlled/jointly controlled by KMP or their close family members."
        },
        "ind_as_37_provisions": {
            "name": "Ind AS 37 — Provisions, Contingent Liabilities, Contingent Assets",
            "statement": "A provision shall be recognized when: (a) the entity has a present obligation (legal or constructive) as a result of a past event, (b) it is probable that an outflow of resources embodying economic benefits will be required to settle the obligation, (c) a reliable estimate can be made of the amount. If these conditions are not met, a contingent liability must be disclosed (unless the possibility of outflow is remote). Contingent assets are not recognized but disclosed when an inflow of economic benefits is probable. Provisions must be reviewed at each balance sheet date and adjusted to reflect the current best estimate. Provisions shall not be recognized for future operating losses."
        },
        "ind_as_107_financial_instruments_disclosures": {
            "name": "Ind AS 107 — Financial Instruments: Disclosures",
            "statement": "The entity must disclose information that enables users to evaluate: (a) the significance of financial instruments for the entity's financial position and performance, (b) the nature and extent of risks arising from financial instruments and how the entity manages those risks. Required disclosures include: carrying amounts by category (FVTPL, FVOCI, amortized cost), fair value hierarchy (Level 1/2/3), credit risk (maximum exposure, ageing of receivables, expected credit loss model), liquidity risk (maturity analysis of financial liabilities by contractual maturity), market risk (sensitivity analysis for interest rate, currency, and price risk). For Level 3 fair value measurements: valuation techniques, inputs used, reconciliation of opening to closing balances, unrealized gains/losses in P&L."
        },
        "ind_as_113_fair_value": {
            "name": "Ind AS 113 — Fair Value Measurement",
            "statement": "Fair value is defined as the price that would be received to sell an asset or paid to transfer a liability in an orderly transaction between market participants at the measurement date (exit price). The fair value hierarchy prioritizes inputs: Level 1 (quoted prices in active markets for identical assets/liabilities), Level 2 (inputs other than quoted prices that are observable, either directly or indirectly), Level 3 (unobservable inputs based on best available information about assumptions that market participants would use). The entity must disclose: fair value at the end of the reporting period, level of the fair value hierarchy, valuation techniques and inputs used, for Level 3: quantitative information about significant unobservable inputs, a reconciliation from opening to closing balances, total gains/losses recognized in P&L and in OCI, description of valuation processes, and a narrative description of the sensitivity to changes in unobservable inputs."
        }
    },

    # ── 12. SCHEDULE III ───────────────────────────────────────────────
    "schedule_iii_companies_act": {
        "part_ii_pl_format": {
            "name": "Schedule III Part II — P&L Format Requirements",
            "statement": "The Statement of Profit and Loss shall disclose the following line items: (I) Revenue from operations, (II) Other income, (III) Total income (I+II), (IV) Expenses (cost of materials consumed, purchases of stock-in-trade, changes in inventories of FG/WIP/stock-in-trade, employee benefits expense, finance costs, depreciation and amortisation, other expenses), (V) Total expenses, (VI) Profit/(loss) before exceptional items and tax (III-V), (VII) Exceptional items, (VIII) Profit/(loss) before tax (VI-VII), (IX) Tax expense (current tax, deferred tax), (X) Profit/(loss) for the period (VIII-IX), (XI) Other comprehensive income, (XII) Total comprehensive income (X+XI). Revenue from operations must be separately disclosed from other income."
        },
        "general_instructions_rounding": {
            "name": "Schedule III — General Instructions on Rounding and Comparatives",
            "statement": "Figures in the financial statements may be rounded off as follows: turnover < Rs. 100 crore — to nearest hundreds, thousands, or lakhs; turnover >= Rs. 100 crore but < Rs. 500 crore — to nearest lakhs; turnover >= Rs. 500 crore — to nearest lakhs or crores. Previous year comparative figures must be presented. If previous year figures have been regrouped/reclassified, the fact must be disclosed. The statement 'Figures for the previous year have been regrouped/reclassified wherever necessary' must be disclosed."
        },
        "mandatory_notes": {
            "name": "Schedule III — Mandatory Note Disclosures",
            "statement": "The following notes are mandatory: (1) Significant accounting policies — basis of preparation, use of estimates, revenue recognition, depreciation, inventories, employee benefits, borrowing costs, taxation, etc. (2) Share capital — authorized, issued, subscribed, paid-up, reconciliation, rights of shareholders, shares held by promoters and their % change. (3) PPE — gross carrying amount, additions, disposals, depreciation, net carrying amount for each class. (4) Trade receivables — ageing schedule (not due, overdue <6 months, 6 months-1 year, 1-2 years, 2-3 years, >3 years) separately for undisputed and disputed, and for considered good and doubtful. (5) Trade payables — ageing schedule (not due, overdue <1 year, 1-2 years, 2-3 years, >3 years) separately for MSME and other vendors. (6) Contingent liabilities and commitments. (7) Earnings per share — basic and diluted."
        },
        "eps_disclosure": {
            "name": "Schedule III — Earnings Per Share Disclosure",
            "statement": "Basic EPS is computed by dividing the profit/(loss) attributable to equity shareholders by the weighted average number of equity shares outstanding during the period. Diluted EPS adjusts both the numerator and denominator for the effects of all dilutive potential equity shares (convertible debentures, options, warrants). The face value per share must be disclosed. The financial statements must disclose: (a) the amounts used as the numerator (profit/loss attributable to equity shareholders), (b) the weighted average number of equity shares used as the denominator, (c) instruments that could potentially dilute basic EPS in the future."
        }
    },

    # ── 13. ICDS ───────────────────────────────────────────────────────
    "icds_standards": {
        "icds_i_accounting_policies": {
            "name": "ICDS I — Accounting Policies (for Tax Purposes)",
            "statement": "For computing income under the heads 'Profits and gains of business or profession' or 'Income from other sources', the fundamental accounting assumptions are: going concern, consistency, and accrual. If the fundamental accounting assumptions are not followed, this fact must be disclosed with reasons. The treatment and presentation of transactions should be governed by their substance and not merely by legal form. Marked-to-market loss or an expected loss shall not be recognized unless specifically permitted by any other ICDS. This differs from Ind AS which requires fair value accounting — creating differences that must be reconciled in the tax computation."
        },
        "icds_ii_inventories": {
            "name": "ICDS II — Valuation of Inventories (for Tax Purposes)",
            "statement": "Inventories shall be valued at cost or net realizable value, whichever is lower. Cost shall be computed using FIFO or weighted average cost formula. Cost of goods purchased includes purchase price, duties and taxes (non-recoverable), freight inward, and other expenditure directly attributable to acquisition. Cost of conversion includes direct labor and systematic allocation of fixed and variable production overheads based on normal capacity. NRV is estimated selling price less estimated cost of completion and selling costs. Key difference from Ind AS 2: ICDS does not allow recognition of inventories at NRV higher than cost (i.e., no reversal of write-downs is allowed for tax purposes)."
        },
        "icds_iv_revenue_recognition": {
            "name": "ICDS IV — Revenue Recognition (for Tax Purposes)",
            "statement": "Revenue from sale of goods shall be recognized when the seller has transferred property in goods to the buyer for a price, or when the seller has transferred significant risks and rewards of ownership to the buyer and the seller retains no effective control to a degree associated with ownership. Revenue from rendering of services shall be recognized by reference to the stage of completion method (percentage of completion). Interest shall accrue on a time basis. Dividend is recognized on the date of right to receive. Key difference from Ind AS 115: ICDS uses risks and rewards approach while Ind AS 115 uses the 5-step model (identify contract, performance obligations, determine price, allocate price, recognize when satisfied)."
        },
        "icds_vi_forex": {
            "name": "ICDS VI — Effects of Changes in Foreign Exchange Rates",
            "statement": "A foreign currency transaction shall be recorded at the exchange rate on the date of the transaction. At the end of each previous year, monetary items denominated in foreign currency shall be translated using the closing rate. Exchange differences arising on settlement or translation of monetary items shall be recognized as income or expense in the previous year in which they arise. Non-monetary items which are measured at historical cost shall be translated using the exchange rate at the date of the transaction. Key difference: Under ICDS, exchange differences on long-term foreign currency monetary items relating to acquisition of depreciable assets are not capitalized — they are recognized as income/expense in the year of arising."
        },
        "icds_x_provisions": {
            "name": "ICDS X — Provisions, Contingent Liabilities, Contingent Assets",
            "statement": "A provision shall be recognized when: (a) the person has a present obligation as a result of a past event, (b) it is reasonably certain that an outflow of resources will be required to settle the obligation, (c) a reliable estimate can be made of the amount. Key difference from Ind AS 37: ICDS uses 'reasonably certain' standard (higher threshold) while Ind AS 37 uses 'probable' (more likely than not — lower threshold). Contingent liabilities are not recognized as a provision under ICDS. Expected cost of contingencies is provided for based on reasonable certainty. This means fewer provisions are deductible for tax purposes than recognized in financial statements under Ind AS."
        }
    },

    # ── 14. AUDIT COMMITTEE REQUIREMENTS ───────────────────────────────
    "audit_committee_requirements": {
        "mandatory_constitution": {
            "name": "Audit Committee — Mandatory Constitution",
            "statement": "Under S.177 of Companies Act 2013 read with Rule 6 of Companies (Meetings of Board and its Powers) Rules 2014, an Audit Committee is mandatory for: (a) every listed public company, (b) all public companies with paid-up share capital >= Rs. 10 crore, (c) all public companies with turnover >= Rs. 100 crore, (d) all public companies with aggregate outstanding loans, debentures and deposits > Rs. 50 crore. For private companies, an Audit Committee is required if the criteria in (b)-(d) are met. The Committee must have minimum 3 directors with independent directors forming a majority (for public companies), and every member must be able to read and understand financial statements."
        },
        "terms_of_reference": {
            "name": "Audit Committee — Terms of Reference",
            "statement": "The Audit Committee shall act in accordance with terms of reference specified by the Board, which shall include: (a) recommendation for appointment, remuneration and terms of appointment of auditors, (b) review and monitor the auditor's independence and performance, (c) examination of the financial statement and auditor's report, (d) approval or any subsequent modification of transactions with related parties, (e) scrutiny of inter-corporate loans and investments, (f) valuation of undertakings or assets of the company, (g) evaluation of internal financial controls and risk management systems, (h) monitoring end use of funds raised through public offers, (i) review the functioning of the Whistle Blower mechanism. The Committee has authority to investigate any matter within its terms of reference, full access to information from any employee, and power to obtain external professional advice."
        },
        "rpt_approval": {
            "name": "Audit Committee — RPT Prior Approval",
            "statement": "Under S.177(4)(iv), every related party transaction must receive prior approval of the Audit Committee. The Audit Committee may grant omnibus approval for RPTs that are repetitive in nature, subject to conditions: (a) maximum value per transaction and per quarter/year, (b) the basis for such approval criteria, (c) the manner of monitoring such transactions. The Committee must review, at least on a quarterly basis, the details of RPTs entered into by the company pursuant to omnibus approval. Any member of the Audit Committee who has a potential interest in any RPT shall abstain from voting on such matter."
        },
        "vigil_mechanism": {
            "name": "Audit Committee — Vigil Mechanism / Whistle-blower",
            "statement": "Under S.177(9) and (10), every listed company and every company accepting deposits or having borrowed money from banks and public financial institutions in excess of Rs. 50 crore shall establish a vigil mechanism for directors and employees to report genuine concerns. The vigil mechanism shall provide for adequate safeguards against victimization of persons who use the mechanism and make provision for direct access to the chairperson of the Audit Committee in appropriate cases. The details of establishment of such mechanism must be disclosed on the company's website and in the Board's Report."
        }
    },

    # ── 15. CSR RULES 2014 ─────────────────────────────────────────────
    "csr_rules_2014": {
        "rule_2_csr_committee": {
            "name": "Rule 2 — CSR Committee Composition",
            "statement": "The CSR Committee shall consist of 3 or more directors, out of which at least one shall be an independent director (for companies required to appoint independent directors under S.149(4)). For a private company that is not required to appoint an independent director, the CSR Committee shall have 2 or more directors. Where the amount to be spent does not exceed Rs. 50 lakhs, the CSR Committee need not be constituted and the Board may perform the functions of the CSR Committee. For a foreign company, the CSR Committee shall comprise of at least 2 persons, of which one shall be a resident Indian."
        },
        "rule_7_spend_calculation": {
            "name": "Rule 7 — CSR Spend Calculation",
            "statement": "The company shall spend at least 2% of the average net profits of the company made during the three immediately preceding financial years. Average net profit shall be calculated in accordance with S.198 of Companies Act 2013. Net profit shall not include: (a) any profit arising from any overseas branch, (b) dividend received from other companies in India where the dividend-paying company meets CSR criteria. CSR expenditure shall include administrative overheads not exceeding 5% of total CSR expenditure. CSR expenditure on impact assessment (mandatory for companies with average CSR obligation >= Rs. 10 crore in 3 preceding FYs) shall not exceed 5% of total CSR expenditure or Rs. 50 lakhs, whichever is less."
        },
        "rule_8_unspent_csr": {
            "name": "Rule 8 — Unspent CSR Amount Transfer",
            "statement": "If the company fails to spend the required CSR amount: (a) For ongoing projects: the unspent amount shall be transferred to a special account (Unspent CSR Account) within 30 days from the end of the financial year, and spent within a period of 3 financial years from the date of such transfer, failing which it shall be transferred to a Fund specified in Schedule VII within 30 days of completion of the 3-year period. (b) For other than ongoing projects: the unspent amount shall be transferred to a Fund specified in Schedule VII (PM CARES Fund, PM National Relief Fund, etc.) within 6 months of the end of the financial year. The Board's report must disclose: CSR Committee composition, CSR policy, amount required to be spent, amount spent, and shortfall with reasons."
        },
        "schedule_vii_activities": {
            "name": "Schedule VII — Eligible CSR Activities",
            "statement": "CSR activities include: (i) eradicating hunger, poverty, malnutrition; promoting healthcare and sanitation; (ii) promoting education, vocational skills, livelihood enhancement; (iii) promoting gender equality, women empowerment, senior citizens welfare; (iv) ensuring environmental sustainability, ecological balance, conservation; (v) protection of national heritage, art, culture; (vi) measures for benefit of armed forces veterans; (vii) training to promote rural/nationally recognized/Paralympic/Olympic sports; (viii) contribution to PM National Relief Fund, PM CARES Fund, or any other fund set up by the Central Government for socio-economic development; (ix) contribution to incubators funded by Central/State Govt; (x) rural development projects; (xi) slum area development; (xii) disaster management; (xiii) contribution to research bodies engaged in science, technology, engineering, medicine if approved by Central Government."
        }
    },

    # ── 16. TRANSFER PRICING ───────────────────────────────────────────
    "transfer_pricing": {
        "s92_definition": {
            "name": "S.92 — International and Specified Domestic Transactions",
            "statement": "Any income arising from an international transaction or specified domestic transaction shall be computed having regard to the arm's length price. Specified domestic transactions (S.92BA) include: (a) expenditure in respect of which payment has been or is to be made to a person referred to in S.40A(2)(b) exceeding Rs. 20 crore in aggregate in any previous year, (b) transactions referred to in S.80A, (c) any business transacted between the assessee and another person under an arrangement, (d) transfer of goods or services referred to in S.80-IA(8) or (10). For domestic RPTs exceeding Rs. 20 crore aggregate, transfer pricing documentation and Form 3CEB is mandatory."
        },
        "s92c_arms_length_methods": {
            "name": "S.92C — Arm's Length Price Computation",
            "statement": "The arm's length price in relation to an international or specified domestic transaction shall be determined by any of the following methods: (a) Comparable Uncontrolled Price (CUP) method, (b) Resale Price Method (RPM), (c) Cost Plus Method (CPM), (d) Profit Split Method (PSM), (e) Transactional Net Margin Method (TNMM), (f) any other method prescribed by the Board. The most appropriate method shall be applied having regard to the nature of the transaction, availability of reliable data, degree of comparability, and functions performed/risks assumed/assets employed. If more than one price is determined, the arm's length price shall be the arithmetical mean of such prices, with a tolerance band of +/- 1% (3% for wholesale trading) for international transactions."
        },
        "s92d_documentation": {
            "name": "S.92D — Transfer Pricing Documentation",
            "statement": "Every person entering into an international or specified domestic transaction shall keep and maintain prescribed information and documents: (a) ownership structure, (b) profile of the multinational group, (c) nature and terms of international transactions, (d) description of functions performed, risks assumed, and assets employed, (e) economic and market analysis, (f) comparable search process and selection of most appropriate method, (g) actual working showing computation of arm's length price, (h) assumptions, policies, and price negotiations. Documentation must be maintained for 8 years from the end of the relevant assessment year. Failure to maintain attracts penalty of 2% of the value of each transaction under S.271AA."
        },
        "form_3ceb": {
            "name": "Form 3CEB — Transfer Pricing Audit Report",
            "statement": "Every person who has entered into an international transaction or a specified domestic transaction during a previous year shall obtain a report from an accountant in Form 3CEB and furnish it on or before the due date for filing the return of income. Form 3CEB contains: (a) particulars of international transactions including nature, property transferred, terms, method used, arm's length price determined, (b) particulars of specified domestic transactions with similar details. The due date is one month prior to the due date of filing the return. Failure to furnish Form 3CEB attracts penalty of Rs. 1,00,000 under S.271BA."
        }
    },

    # ── 17. CUSTOMS & EXPORT INCENTIVES ─────────────────────────────────
    "customs_export_incentives": {
        "s50_shipping_bill": {
            "name": "Customs Act S.50 — Entry of Goods for Export",
            "statement": "The exporter of any goods shall make entry thereof by presenting a Shipping Bill (for goods exported by sea or air) or a Bill of Export (for goods exported by land) in the prescribed form. The Shipping Bill must correctly declare: description, quantity, value, applicable duty/cess, export incentive scheme (if any), country of destination, and port of loading. Let Export Order is issued by Customs after verification. Any misdeclaration in the Shipping Bill attracts penalty under S.114 (up to 5 times the value of goods or Rs. 50 lakhs, whichever is greater) and prosecution under S.135 (imprisonment up to 7 years)."
        },
        "s75_duty_drawback": {
            "name": "Customs Act S.75 — Duty Drawback on Exported Goods",
            "statement": "Where it appears to the Central Government that customs duty or excise duty has been paid on materials used in manufacture of exported goods, drawback may be allowed on such export. Drawback rates are notified through All Industry Rates (AIR) or Brand Rate (where AIR is not available or is inadequate). The claim must be filed at the time of export in the Shipping Bill. Time limit for claiming drawback: within 3 months of let export order (extendable by 9 months with condition of 90-95% drawback). Fraudulent drawback claims attract penalty under S.76 (recovery of drawback amount plus interest) and prosecution."
        },
        "export_obligations": {
            "name": "Foreign Trade Policy — Export Obligations",
            "statement": "If the company has availed duty-free import benefits under Advance Authorization or EPCG (Export Promotion Capital Goods) scheme, there are mandatory export obligations to fulfill. For Advance Authorization: exports must be completed within 18 months (extendable) and must be at least 15% of CIF value of imports plus 100% of duties saved. For EPCG: exports must be 6 times the duty saved, to be completed over 6 years. Non-fulfillment attracts: (a) recovery of customs duty with interest from the date of clearance of goods at 15% per annum, (b) confiscation of capital goods imported, (c) penalty up to 5 times the duty amount. The company must maintain proper records of import and export transactions for verification."
        },
        "firc_reconciliation": {
            "name": "FIRC — Foreign Inward Remittance Certificate Reconciliation",
            "statement": "For every export transaction, the company must obtain a Foreign Inward Remittance Certificate (FIRC) from the Authorized Dealer bank confirming receipt of foreign exchange. The FIRC must be reconciled with: (a) export invoices raised, (b) Shipping Bills filed with Customs, (c) BRC (Bank Realization Certificate) obtained from bank. Any discrepancies between invoice value, Shipping Bill value, and FIRC amount must be investigated and resolved. Unrealized export proceeds must be followed up and reported to the Authorized Dealer bank. Under FEMA, write-off of unrealized export receivables exceeding certain limits requires RBI approval. The company's foreign exchange income (duty drawback, MEIS/RoDTEP scrips) must also be properly reconciled and accounted for."
        }
    }
}

# Validate and write
import sys
try:
    json_str = json.dumps(rules, indent=2, ensure_ascii=False)
    # Quick validation
    json.loads(json_str)

    from pathlib import Path
    out_path = Path(__file__).resolve().parent / "compliance_rules.json"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json_str)

    # Count sections
    total = sum(len(v) for k, v in rules.items() if k != "metadata")
    cats = len([k for k in rules if k != "metadata"])
    print(f"Written {out_path}")
    print(f"  {cats} categories, {total} total sections")
    print(f"  File size: {len(json_str):,} bytes")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
