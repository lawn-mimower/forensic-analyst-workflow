-- =============================================================================
-- FORENSIC ACCOUNTING ANALYSIS SYSTEM — RELATIONAL DATA MODEL
-- =============================================================================
-- Target: DuckDB (portable, embedded, zero-config)
-- Convention: All monetary amounts stored in ABSOLUTE RUPEES (paise precision)
--             Source unit (lakhs/crores) recorded for audit trail
--             Indian FY convention: FY 2023-24 = April 2023 to March 2024
--
-- Design principles:
--   1. Every number traceable to a specific page of a specific document
--   2. Same economic fact from multiple sources linked, not duplicated
--   3. Schedule III hierarchy baked into chart of accounts
--   4. Immutable audit trail — corrections via new rows, not updates
-- =============================================================================


-- =============================================================================
-- TABLE 1: entities
-- =============================================================================
-- Companies, subsidiaries, associates, JVs involved in the analysis.
-- Supports group structures (parent → subsidiary tree).
-- =============================================================================

CREATE TABLE IF NOT EXISTS entities (
    entity_id           TEXT PRIMARY KEY,                    -- e.g., 'EXAMPLE_ENG_PVT'
    legal_name          TEXT NOT NULL,                       -- 'Example Engineering Private Limited'
    short_name          TEXT,                                -- 'Example Engineering'
    cin                 TEXT,                                -- Corporate Identity Number (U00000XX0000PTC000000)
    pan                 TEXT,                                -- AAACH1234A
    gstin               TEXT,                                -- 29AAACH1234A1Z5
    entity_type         TEXT NOT NULL DEFAULT 'company'      -- 'company','subsidiary','associate','jv','trust','llp','proprietorship'
                        CHECK (entity_type IN ('company','subsidiary','associate','jv',
                                               'trust','llp','proprietorship','individual','other')),
    parent_entity_id    TEXT REFERENCES entities(entity_id), -- NULL for ultimate parent
    ownership_pct       DOUBLE,                              -- Parent's ownership percentage (0-100)
    incorporation_date  TEXT,                                -- ISO date 'YYYY-MM-DD'
    registered_address  TEXT,
    industry_code       TEXT,                                -- NIC code
    industry_desc       TEXT,                                -- 'Industrial Machinery'
    listing_status      TEXT DEFAULT 'unlisted'              -- 'listed_bse','listed_nse','listed_both','unlisted','delisted'
                        CHECK (listing_status IN ('listed_bse','listed_nse','listed_both',
                                                  'unlisted','delisted','sme_platform')),
    accounting_standard TEXT DEFAULT 'ind_as'                -- 'ind_as','igaap','ifrs'
                        CHECK (accounting_standard IN ('ind_as','igaap','ifrs')),
    functional_currency TEXT DEFAULT 'INR',
    is_active           BOOLEAN DEFAULT TRUE,                 -- FALSE = dissolved/struck-off
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    metadata_json       TEXT                                 -- Flexible overflow for unstructured attributes
);

CREATE INDEX idx_entities_parent ON entities(parent_entity_id);
CREATE INDEX idx_entities_cin ON entities(cin);


-- =============================================================================
-- TABLE 2: documents
-- =============================================================================
-- Metadata about every source document ingested into the system.
-- A single PDF may contain multiple financial statements (P&L, BS, CF).
-- =============================================================================

CREATE TABLE IF NOT EXISTS documents (
    document_id         TEXT PRIMARY KEY,                    -- UUID or deterministic hash
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),
    file_name           TEXT NOT NULL,                       -- 'sample_docs/sample_statement.pdf'
    file_path           TEXT,                                -- Relative path in user_documents/
    file_hash_sha256    TEXT,                                -- Content hash for deduplication
    file_size_bytes     INTEGER,
    mime_type           TEXT DEFAULT 'application/pdf',
    document_type       TEXT NOT NULL                        -- Classification of the document
                        CHECK (document_type IN (
                            'annual_report','standalone_financials','consolidated_financials',
                            'profit_and_loss','balance_sheet','cash_flow_statement',
                            'notes_to_accounts','schedules','significant_policies',
                            'auditor_report','directors_report','secretarial_audit',
                            'board_resolution','aoc_4_xbrl',
                            'general_ledger','trial_balance','bank_statement',
                            'tax_return','gst_return','tds_return',
                            'related_party_disclosures','segment_report',
                            'caro_report','mgmt_discussion_analysis',
                            'prospectus','offer_document',
                            'investigation_report','charge_sheet',
                            'other'
                        )),
    document_subtype    TEXT,                                -- Further classification ('schedule_iii_div_i', 'form_26as', etc.)
    statement_scope     TEXT DEFAULT 'standalone'            -- 'standalone' vs 'consolidated'
                        CHECK (statement_scope IN ('standalone','consolidated','combined')),
    audit_status        TEXT DEFAULT 'audited'               -- Reliability indicator
                        CHECK (audit_status IN ('audited','limited_review','unaudited',
                                                'draft','management_certified','provisional')),
    auditor_name        TEXT,                                -- 'PGBHAGWAT LLP, Chartered Accountants'
    auditor_opinion     TEXT,                                -- 'unmodified','qualified','adverse','disclaimer'
                        -- CHECK omitted for flexibility
    period_start        TEXT,                                -- '2023-04-01' (ISO date)
    period_end          TEXT,                                -- '2024-03-31'
    period_label        TEXT,                                -- 'FY 2023-24', 'Q2 FY 2023-24'
    period_type         TEXT DEFAULT 'annual'                -- 'annual','half_yearly','quarterly','monthly','ytd','custom'
                        CHECK (period_type IN ('annual','half_yearly','quarterly','monthly','ytd','custom')),
    reporting_currency  TEXT DEFAULT 'INR',
    source_unit         TEXT DEFAULT 'absolute'              -- Unit in which numbers appear in the document
                        CHECK (source_unit IN ('absolute','thousands','lakhs','crores','millions','billions')),
    source_unit_multiplier DOUBLE DEFAULT 1.0,               -- 1, 1000, 100000, 10000000, 1000000, 1000000000
    total_pages         INTEGER,
    ingestion_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    extraction_method   TEXT,                                -- 'docling','camelot','manual','xbrl_parse','ocr'
    extraction_confidence DOUBLE,                            -- 0.0 to 1.0 overall confidence
    notes               TEXT,
    metadata_json       TEXT                                 -- Overflow for custom attributes
);

CREATE INDEX idx_documents_entity ON documents(entity_id);
CREATE INDEX idx_documents_type ON documents(document_type);
CREATE INDEX idx_documents_period ON documents(period_start, period_end);
CREATE INDEX idx_documents_hash ON documents(file_hash_sha256);


-- =============================================================================
-- TABLE 3: tables_extracted
-- =============================================================================
-- Metadata about each individual table extracted from a document.
-- A single PDF page may contain multiple tables; a single financial statement
-- (e.g., Balance Sheet) may span multiple pages.
-- =============================================================================

CREATE TABLE IF NOT EXISTS tables_extracted (
    table_id            TEXT PRIMARY KEY,                    -- UUID
    document_id         TEXT NOT NULL REFERENCES documents(document_id),
    page_numbers        TEXT,                                -- JSON array: [12, 13] for multi-page tables
    table_index_on_page INTEGER,                             -- 0-based index if multiple tables on same page
    heading_text        TEXT,                                -- Extracted heading: 'Statement of Profit and Loss'
    sub_heading_text    TEXT,                                -- 'for the year ended March 31, 2024'
    table_type          TEXT                                 -- Semantic classification
                        CHECK (table_type IN (
                            'balance_sheet','profit_and_loss','cash_flow',
                            'changes_in_equity','notes_schedule',
                            'fixed_assets_schedule','depreciation_schedule',
                            'trade_receivables_ageing','trade_payables_ageing',
                            'related_party_summary','segment_information',
                            'tax_reconciliation','fair_value_hierarchy',
                            'maturity_analysis','ratio_analysis',
                            'gl_extract','trial_balance','bank_statement',
                            'csr_expenditure','contingent_liabilities',
                            'capital_commitments','other'
                        )),
    row_count           INTEGER,                             -- Number of data rows extracted
    col_count           INTEGER,                             -- Number of columns
    column_headers_json TEXT,                                -- JSON: ["Particulars","FY 2023-24","FY 2022-23"]
    source_unit         TEXT,                                -- May differ from document-level unit
    extraction_method   TEXT,                                -- 'docling_table','camelot','manual_entry'
    extraction_confidence DOUBLE,                            -- Per-table confidence 0.0 to 1.0
    raw_text            TEXT,                                -- Raw text dump before structuring
    structured_json     TEXT,                                -- Full table as JSON array of row-dicts
    bbox_json           TEXT,                                -- Bounding box coordinates on page
    notes               TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tables_document ON tables_extracted(document_id);
CREATE INDEX idx_tables_type ON tables_extracted(table_type);


-- =============================================================================
-- TABLE 4: accounts
-- =============================================================================
-- Chart of Accounts / Account Taxonomy aligned with Schedule III.
-- Hierarchical: top-level categories → sub-categories → leaf accounts.
-- Maps company-specific GL account names to standardized Schedule III line items.
-- =============================================================================

CREATE TABLE IF NOT EXISTS accounts (
    account_id          TEXT PRIMARY KEY,                    -- Hierarchical code: 'BS.A.NCA.FA.TA'
    account_code        TEXT UNIQUE,                         -- Numeric code: '1.1.1.1'
    account_name        TEXT NOT NULL,                       -- 'Property, Plant and Equipment'
    account_name_hindi  TEXT,                                -- Hindi translation (some MCA filings)
    parent_account_id   TEXT REFERENCES accounts(account_id),-- Hierarchy link
    account_level       INTEGER NOT NULL DEFAULT 0,          -- 0=root, 1=major, 2=sub, 3=detail, 4=leaf
    account_type        TEXT NOT NULL                        -- Fundamental accounting type
                        CHECK (account_type IN (
                            'asset','liability','equity',
                            'revenue','expense',
                            'contra_asset','contra_liability','contra_equity',
                            'contra_revenue','contra_expense',
                            'gain','loss',
                            'header','subtotal','total'      -- Non-posting aggregation nodes
                        )),
    statement_type      TEXT NOT NULL                        -- Which financial statement
                        CHECK (statement_type IN (
                            'balance_sheet','profit_and_loss','cash_flow',
                            'changes_in_equity','notes','off_balance_sheet','ratio'
                        )),
    schedule_iii_ref    TEXT,                                -- Schedule III reference: 'Part I, I(1)(a)'
    ind_as_ref          TEXT,                                -- Relevant Ind AS: 'Ind AS 16'
    xbrl_element        TEXT,                                -- MCA XBRL taxonomy element name
    normal_balance      TEXT DEFAULT 'debit'                 -- Expected balance direction
                        CHECK (normal_balance IN ('debit','credit','not_applicable')),
    is_posting          BOOLEAN DEFAULT TRUE,                 -- leaf account (postable) vs header/subtotal
    is_mandatory        BOOLEAN DEFAULT TRUE,                 -- TRUE = required by Schedule III; FALSE = optional detail
    display_order       INTEGER,                             -- Sort order within parent for presentation
    formula_json        TEXT,                                -- For computed accounts: JSON formula spec
    description         TEXT,
    metadata_json       TEXT
);

CREATE INDEX idx_accounts_parent ON accounts(parent_account_id);
CREATE INDEX idx_accounts_type ON accounts(account_type);
CREATE INDEX idx_accounts_statement ON accounts(statement_type);
CREATE INDEX idx_accounts_schedule_ref ON accounts(schedule_iii_ref);


-- =============================================================================
-- TABLE 5: line_items
-- =============================================================================
-- THE CORE TABLE: Every extracted financial number lives here.
-- Each row = one number from one source, for one account, for one period.
-- Supports the "same number in multiple documents" problem via canonical_group_id.
-- =============================================================================

CREATE TABLE IF NOT EXISTS line_items (
    line_item_id        TEXT PRIMARY KEY,                    -- UUID
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),
    account_id          TEXT NOT NULL REFERENCES accounts(account_id),
    document_id         TEXT NOT NULL REFERENCES documents(document_id),
    table_id            TEXT REFERENCES tables_extracted(table_id),

    -- Period identification
    period_start        TEXT NOT NULL,                       -- '2023-04-01'
    period_end          TEXT NOT NULL,                       -- '2024-03-31'
    period_label        TEXT,                                -- 'FY 2023-24'
    period_type         TEXT DEFAULT 'annual'
                        CHECK (period_type IN ('annual','half_yearly','quarterly','monthly',
                                               'ytd','as_at','custom')),
    is_comparative      BOOLEAN DEFAULT FALSE,                -- TRUE if this is the prior-period comparative column

    -- The actual value
    amount_original     DOUBLE NOT NULL,                     -- Value as it appears in the document
    source_unit         TEXT DEFAULT 'absolute'              -- Unit of amount_original
                        CHECK (source_unit IN ('absolute','thousands','lakhs','crores','millions','billions')),
    amount_absolute     DOUBLE NOT NULL,                     -- Normalized to absolute rupees (= amount_original * multiplier)
    amount_paise        INTEGER,                             -- Integer paise for exact arithmetic (amount_absolute * 100)
    currency            TEXT DEFAULT 'INR',

    -- Debit/Credit semantics
    debit_credit        TEXT                                 -- 'debit','credit', or NULL if not applicable
                        CHECK (debit_credit IN ('debit','credit') OR debit_credit IS NULL),
    sign_convention     TEXT DEFAULT 'positive_normal',      -- How to interpret the sign
                        -- 'positive_normal': positive = expected direction for account type
                        -- 'negative_means_opposite': negative revenue = expense character
                        -- 'parenthetical_negative': (123.45) in source = negative

    -- Provenance (which exact spot in which document)
    source_page         INTEGER,                             -- Page number in PDF
    source_row          INTEGER,                             -- Row index in extracted table
    source_col          INTEGER,                             -- Column index in extracted table
    source_cell_text    TEXT,                                -- Raw cell text: '₹ 1,234.56' or '(43.20)'
    source_label_text   TEXT,                                -- Row label as extracted: 'Revenue from operations'

    -- Cross-document linking
    canonical_group_id  TEXT,                                -- Groups the same economic fact across documents
                                                             -- e.g., Revenue FY24 appears in P&L, CF notes, Director's Report
    is_primary_source   BOOLEAN DEFAULT FALSE,                -- TRUE = authoritative source

    -- Quality
    extraction_confidence DOUBLE,                            -- 0.0 to 1.0
    is_derived          BOOLEAN DEFAULT FALSE,                -- TRUE = computed from other line_items, not directly extracted
    derivation_formula  TEXT,                                -- If derived: 'SUM(line_item_id_1, line_item_id_2)'
    is_audited          BOOLEAN DEFAULT TRUE,                 -- Inherited from document.audit_status
    is_restated         BOOLEAN DEFAULT FALSE,                -- TRUE = restated figure (differs from original filing)
    original_line_item_id TEXT REFERENCES line_items(line_item_id), -- Points to pre-restatement value

    -- Annotation
    notes               TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_line_items_entity ON line_items(entity_id);
CREATE INDEX idx_line_items_account ON line_items(account_id);
CREATE INDEX idx_line_items_document ON line_items(document_id);
CREATE INDEX idx_line_items_table ON line_items(table_id);
CREATE INDEX idx_line_items_period ON line_items(period_start, period_end);
CREATE INDEX idx_line_items_canonical ON line_items(canonical_group_id);
CREATE INDEX idx_line_items_entity_account_period ON line_items(entity_id, account_id, period_start, period_end);


-- =============================================================================
-- TABLE 6: transactions
-- =============================================================================
-- Individual GL / journal entries when General Ledger data is available.
-- Each transaction has 2+ legs (debits and credits that must balance).
-- =============================================================================

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      TEXT PRIMARY KEY,                    -- UUID
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),
    document_id         TEXT REFERENCES documents(document_id), -- GL export document
    journal_number      TEXT,                                -- Original journal entry number from source system
    journal_type        TEXT,                                -- 'sales','purchase','receipt','payment','journal','contra',
                                                             --  'opening','closing','depreciation','provision','reversal'
    transaction_date    TEXT NOT NULL,                       -- ISO date of the transaction
    posting_date        TEXT,                                -- Date posted to ledger (may differ from txn date)
    value_date          TEXT,                                -- Bank value date
    period_label        TEXT,                                -- 'FY 2023-24'
    narration           TEXT,                                -- Description / narration from voucher
    reference_number    TEXT,                                -- Invoice/cheque/UTR number
    reference_type      TEXT,                                -- 'invoice','cheque','utr','receipt','debit_note','credit_note'
    counterparty_name   TEXT,                                -- Name of the other party
    counterparty_pan    TEXT,                                -- PAN of counterparty (for TDS matching)
    is_related_party    BOOLEAN DEFAULT FALSE,                -- TRUE = identified as related party transaction
    related_party_id    TEXT REFERENCES related_parties(relationship_id),
    total_amount        DOUBLE NOT NULL,                     -- Total debit (= total credit) for this entry
    currency            TEXT DEFAULT 'INR',
    exchange_rate       DOUBLE DEFAULT 1.0,                  -- For foreign currency transactions
    is_reversed         BOOLEAN DEFAULT FALSE,                -- TRUE = this entry has been reversed
    reversal_txn_id     TEXT REFERENCES transactions(transaction_id),
    source_system       TEXT,                                -- 'tally','sap','zoho','manual'
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    metadata_json       TEXT
);

CREATE INDEX idx_txn_entity ON transactions(entity_id);
CREATE INDEX idx_txn_date ON transactions(transaction_date);
CREATE INDEX idx_txn_counterparty ON transactions(counterparty_name);
CREATE INDEX idx_txn_journal ON transactions(journal_number);
CREATE INDEX idx_txn_reference ON transactions(reference_number);
CREATE INDEX idx_txn_related_party ON transactions(related_party_id);


-- =============================================================================
-- TABLE 6b: transaction_legs
-- =============================================================================
-- Each leg of a journal entry (the debit side and credit side).
-- A single transaction has >= 2 legs that must sum to zero.
-- =============================================================================

CREATE TABLE IF NOT EXISTS transaction_legs (
    leg_id              TEXT PRIMARY KEY,                    -- UUID
    transaction_id      TEXT NOT NULL REFERENCES transactions(transaction_id),
    account_id          TEXT NOT NULL REFERENCES accounts(account_id),
    debit_amount        DOUBLE DEFAULT 0.0,                 -- Only one of debit/credit is non-zero
    credit_amount       DOUBLE DEFAULT 0.0,
    amount_absolute     DOUBLE NOT NULL,                     -- Signed: positive for debit, negative for credit
    narration           TEXT,                                -- Leg-specific narration
    cost_center         TEXT,                                -- Department / division / branch
    project_code        TEXT,
    metadata_json       TEXT,

    CHECK (
        (debit_amount > 0 AND credit_amount = 0) OR
        (credit_amount > 0 AND debit_amount = 0)
    )
);

CREATE INDEX idx_legs_txn ON transaction_legs(transaction_id);
CREATE INDEX idx_legs_account ON transaction_legs(account_id);


-- =============================================================================
-- TABLE 7: related_parties
-- =============================================================================
-- Related party relationships and transaction summaries per Ind AS 24.
-- Tracks both the relationship and aggregate transaction data per period.
-- =============================================================================

CREATE TABLE IF NOT EXISTS related_parties (
    relationship_id     TEXT PRIMARY KEY,                    -- UUID
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id), -- The reporting entity
    related_entity_id   TEXT REFERENCES entities(entity_id), -- If the related party is also in our entities table
    related_party_name  TEXT NOT NULL,                       -- 'Related Party X'
    related_party_pan   TEXT,
    related_party_din   TEXT,                                -- DIN if individual director
    relationship_type   TEXT NOT NULL                        -- Ind AS 24 categories
                        CHECK (relationship_type IN (
                            'holding_company','subsidiary','fellow_subsidiary',
                            'associate','joint_venture',
                            'key_management_personnel','kmp_relative',
                            'entity_controlled_by_kmp','entity_influenced_by_kmp',
                            'post_employment_benefit_plan',
                            'promoter','promoter_group',
                            'significant_influence','joint_control',
                            'other'
                        )),
    relationship_detail TEXT,                                -- 'Director on both boards', 'Son of Managing Director'
    designation         TEXT,                                -- 'Managing Director','CFO','Company Secretary','Independent Director'
    effective_from      TEXT,                                -- When relationship began
    effective_to        TEXT,                                -- NULL if still active
    is_active           BOOLEAN DEFAULT TRUE,
    disclosed_in_document_id TEXT REFERENCES documents(document_id), -- Where was this relationship disclosed
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    metadata_json       TEXT
);

CREATE INDEX idx_rp_entity ON related_parties(entity_id);
CREATE INDEX idx_rp_related ON related_parties(related_entity_id);
CREATE INDEX idx_rp_type ON related_parties(relationship_type);
CREATE INDEX idx_rp_name ON related_parties(related_party_name);


-- =============================================================================
-- TABLE 7b: related_party_transactions
-- =============================================================================
-- Aggregate transaction summaries with related parties, per period.
-- Links to individual GL transactions where available.
-- =============================================================================

CREATE TABLE IF NOT EXISTS related_party_transactions (
    rpt_id              TEXT PRIMARY KEY,
    relationship_id     TEXT NOT NULL REFERENCES related_parties(relationship_id),
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    period_label        TEXT,                                -- 'FY 2023-24'
    transaction_nature  TEXT NOT NULL,                       -- 'sales','purchases','remuneration','dividend_paid',
                                                             --  'dividend_received','loans_given','loans_taken',
                                                             --  'interest_paid','interest_received','rent_paid',
                                                             --  'rent_received','services_received','services_rendered',
                                                             --  'guarantee_given','guarantee_received','other'
    amount_absolute     DOUBLE NOT NULL,                     -- In absolute rupees
    outstanding_balance DOUBLE,                              -- Balance as at period end
    outstanding_balance_type TEXT,                           -- 'receivable' or 'payable'
    provision_for_doubtful DOUBLE DEFAULT 0.0,               -- Provision for doubtful debts on this balance
    is_arms_length      BOOLEAN DEFAULT TRUE,                 -- TRUE = at arm's length; FALSE = below/above market
    disclosed_in_document_id TEXT REFERENCES documents(document_id),
    source_line_item_id TEXT REFERENCES line_items(line_item_id),
    notes               TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rpt_relationship ON related_party_transactions(relationship_id);
CREATE INDEX idx_rpt_period ON related_party_transactions(period_start, period_end);
CREATE INDEX idx_rpt_nature ON related_party_transactions(transaction_nature);


-- =============================================================================
-- TABLE 8: ratios
-- =============================================================================
-- Computed financial ratios with full formula provenance.
-- Includes both mandatory Schedule III ratios (per 2021 amendment)
-- and forensic-specific ratios.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ratios (
    ratio_id            TEXT PRIMARY KEY,                    -- UUID
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    period_label        TEXT,

    ratio_name          TEXT NOT NULL,                       -- 'current_ratio','debt_equity_ratio','net_profit_margin'
    ratio_category      TEXT NOT NULL                        -- Grouping
                        CHECK (ratio_category IN (
                            'liquidity','solvency','profitability','efficiency',
                            'valuation','cash_flow','forensic','schedule_iii_mandatory','custom'
                        )),
    ratio_value         DOUBLE,                              -- The computed ratio value
    numerator_value     DOUBLE,                              -- Numerator used in calculation
    denominator_value   DOUBLE,                              -- Denominator used
    numerator_formula   TEXT,                                -- Human-readable: 'Current Assets'
    denominator_formula TEXT,                                -- 'Current Liabilities'
    formula_detail_json TEXT,                                -- JSON: {"numerator_items": ["li_id_1","li_id_2"], ...}
    numerator_account_ids TEXT,                              -- JSON array of account_ids used
    denominator_account_ids TEXT,                            -- JSON array of account_ids used
    unit                TEXT DEFAULT 'ratio',                -- 'ratio','percentage','times','days','rupees'
    prior_period_value  DOUBLE,                              -- Same ratio for prior period (for variance)
    variance_pct        DOUBLE,                              -- ((current - prior) / prior) * 100
    variance_explanation TEXT,                               -- Explanation if variance > 25% (Schedule III requirement)
    benchmark_value     DOUBLE,                              -- Industry benchmark if available
    benchmark_source    TEXT,                                -- 'rbi_industry_avg','crisil','icra','manual'
    is_schedule_iii     BOOLEAN DEFAULT FALSE,                -- TRUE = one of the 11 mandatory ratios
    is_anomalous        BOOLEAN DEFAULT FALSE,                -- TRUE = flagged by forensic analysis
    flag_id             TEXT REFERENCES flags(flag_id),      -- Link to anomaly flag if flagged
    computed_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    notes               TEXT,
    metadata_json       TEXT
);

CREATE INDEX idx_ratios_entity ON ratios(entity_id);
CREATE INDEX idx_ratios_period ON ratios(period_start, period_end);
CREATE INDEX idx_ratios_name ON ratios(ratio_name);
CREATE INDEX idx_ratios_category ON ratios(ratio_category);


-- =============================================================================
-- TABLE 9: flags
-- =============================================================================
-- Anomaly flags from forensic analysis tests.
-- Each flag = one potential issue detected by an automated test or manual review.
-- =============================================================================

CREATE TABLE IF NOT EXISTS flags (
    flag_id             TEXT PRIMARY KEY,                    -- UUID
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),
    document_id         TEXT REFERENCES documents(document_id),
    line_item_id        TEXT REFERENCES line_items(line_item_id),
    transaction_id      TEXT REFERENCES transactions(transaction_id),
    ratio_id            TEXT REFERENCES ratios(ratio_id),
    reconciliation_id   TEXT REFERENCES reconciliation(reconciliation_id),

    -- Classification
    flag_type           TEXT NOT NULL                        -- Type of forensic test
                        CHECK (flag_type IN (
                            'benford_first_digit','benford_second_digit','benford_first_two',
                            'duplicate_amount','duplicate_entry','round_number_excess',
                            'weekend_holiday_transaction','just_below_threshold',
                            'unusual_journal_entry','manual_journal_anomaly',
                            'revenue_expense_mismatch','cut_off_error',
                            'related_party_undisclosed','related_party_pricing',
                            'ratio_anomaly','trend_break','outlier_zscore','outlier_iqr',
                            'missing_disclosure','inconsistent_disclosure',
                            'restatement_detected','prior_period_adjustment',
                            'cash_flow_vs_profit_divergence',
                            'receivables_ageing_anomaly','payables_ageing_anomaly',
                            'inventory_buildup','inventory_write_down',
                            'contingent_liability_change',
                            'auditor_qualification','emphasis_of_matter',
                            'going_concern','material_weakness',
                            'cross_document_mismatch','reconciliation_break',
                            'custom'
                        )),
    flag_subtype        TEXT,                                -- Further detail: 'digit_1_excess_for_7'
    severity            TEXT NOT NULL DEFAULT 'medium'
                        CHECK (severity IN ('critical','high','medium','low','info')),
    confidence          DOUBLE,                              -- 0.0 to 1.0 — how confident is the detection

    -- Description
    title               TEXT NOT NULL,                       -- 'Benford First Digit Anomaly in Sales Ledger'
    description         TEXT NOT NULL,                       -- Detailed explanation
    evidence_json       TEXT,                                -- JSON: supporting data, expected vs actual distributions, etc.
    affected_amount     DOUBLE,                              -- Total rupee value affected
    affected_period     TEXT,                                -- 'FY 2023-24'
    affected_accounts   TEXT,                                -- JSON array of account_ids

    -- Resolution tracking
    status              TEXT DEFAULT 'open'
                        CHECK (status IN ('open','under_review','explained','escalated',
                                          'confirmed_issue','false_positive','resolved')),
    reviewer_notes      TEXT,                                -- Analyst's notes after investigation
    resolution          TEXT,                                -- Final conclusion
    resolved_at         TEXT,
    resolved_by         TEXT,

    -- Test parameters
    test_parameters_json TEXT,                               -- JSON: parameters used for this test run
    test_run_id         TEXT,                                -- Groups flags from the same test execution

    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_flags_entity ON flags(entity_id);
CREATE INDEX idx_flags_type ON flags(flag_type);
CREATE INDEX idx_flags_severity ON flags(severity);
CREATE INDEX idx_flags_status ON flags(status);
CREATE INDEX idx_flags_line_item ON flags(line_item_id);
CREATE INDEX idx_flags_transaction ON flags(transaction_id);
CREATE INDEX idx_flags_test_run ON flags(test_run_id);


-- =============================================================================
-- TABLE 10: reconciliation
-- =============================================================================
-- Cross-document and cross-statement reconciliation results.
-- Compares the same economic fact across different sources.
-- =============================================================================

CREATE TABLE IF NOT EXISTS reconciliation (
    reconciliation_id   TEXT PRIMARY KEY,                    -- UUID
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),

    -- What is being reconciled
    reconciliation_type TEXT NOT NULL
                        CHECK (reconciliation_type IN (
                            'pl_vs_bs',                      -- P&L profit = BS reserves movement
                            'pl_vs_cf',                      -- P&L items vs Cash Flow adjustments
                            'bs_vs_cf',                      -- BS changes vs Cash Flow
                            'bs_vs_notes',                   -- BS line item vs Note detail
                            'pl_vs_notes',                   -- P&L line item vs Note detail
                            'bs_equation',                   -- Assets = Liabilities + Equity
                            'cf_opening_closing',            -- Opening cash + CF = Closing cash
                            'gl_vs_tb',                      -- GL total vs Trial Balance
                            'tb_vs_financials',              -- Trial Balance vs Financial Statements
                            'bank_vs_books',                 -- Bank statement vs Cash/Bank ledger
                            'gst_vs_books',                  -- GSTR-1/2B vs Sales/Purchase register
                            'tds_vs_books',                  -- 26AS/AIS vs TDS ledger
                            'standalone_vs_consolidated',    -- Standalone numbers within consolidated
                            'current_vs_prior_comparative',  -- This year's comparative = last year's actual
                            'inter_company',                 -- Eliminate inter-company transactions
                            'audited_vs_draft',              -- Changes between draft and audited
                            'annual_vs_quarterly',           -- Sum of quarters = annual
                            'custom'
                        )),
    description         TEXT NOT NULL,                       -- 'Revenue from Operations: P&L vs Note 20'

    -- Period
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    period_label        TEXT,

    -- Source A (typically the "primary" or "control" document)
    source_a_document_id TEXT REFERENCES documents(document_id),
    source_a_line_item_id TEXT REFERENCES line_items(line_item_id),
    source_a_label      TEXT,                                -- 'Balance Sheet: Total Assets'
    source_a_amount     DOUBLE NOT NULL,

    -- Source B (the "secondary" or "detail" document)
    source_b_document_id TEXT REFERENCES documents(document_id),
    source_b_line_item_id TEXT REFERENCES line_items(line_item_id),
    source_b_label      TEXT,                                -- 'Note 5: Total Fixed Assets'
    source_b_amount     DOUBLE NOT NULL,

    -- Result
    difference          DOUBLE NOT NULL,                     -- source_a - source_b
    difference_pct      DOUBLE,                              -- ABS(difference) / MAX(ABS(a), ABS(b)) * 100
    tolerance           DOUBLE DEFAULT 0.0,                  -- Acceptable rounding difference
    is_matched          INTEGER NOT NULL,                    -- TRUE = within tolerance; zero = break
    match_status        TEXT DEFAULT 'unreviewed'
                        CHECK (match_status IN ('matched','rounding','break','explained','unreviewed')),

    -- If break, link to flag
    flag_id             TEXT REFERENCES flags(flag_id),

    explanation         TEXT,                                -- Analyst explanation of difference
    computed_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    notes               TEXT
);

CREATE INDEX idx_recon_entity ON reconciliation(entity_id);
CREATE INDEX idx_recon_type ON reconciliation(reconciliation_type);
CREATE INDEX idx_recon_period ON reconciliation(period_start, period_end);
CREATE INDEX idx_recon_matched ON reconciliation(is_matched);


-- =============================================================================
-- TABLE 11: account_mappings (SUPPLEMENTARY)
-- =============================================================================
-- Maps company-specific GL account names/codes to standardized accounts.
-- Essential when ingesting GL exports from Tally, SAP, Zoho, etc.
-- =============================================================================

CREATE TABLE IF NOT EXISTS account_mappings (
    mapping_id          TEXT PRIMARY KEY,
    entity_id           TEXT NOT NULL REFERENCES entities(entity_id),
    source_system       TEXT,                                -- 'tally','sap','zoho','quickbooks'
    source_account_code TEXT NOT NULL,                       -- Company's own code: '31001'
    source_account_name TEXT NOT NULL,                       -- 'Sales - Domestic Hydraulic'
    source_group        TEXT,                                -- Tally group: 'Sales Accounts'
    mapped_account_id   TEXT NOT NULL REFERENCES accounts(account_id), -- Our standard account
    mapping_confidence  DOUBLE DEFAULT 1.0,                  -- 1.0 = manual/certain; Less than 1.0 = AI-suggested
    mapping_method      TEXT DEFAULT 'manual'                -- 'manual','rule_based','llm_suggested','xbrl_tag'
                        CHECK (mapping_method IN ('manual','rule_based','llm_suggested','xbrl_tag','historical')),
    is_verified         BOOLEAN DEFAULT FALSE,
    verified_by         TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    notes               TEXT
);

CREATE INDEX idx_mapping_entity ON account_mappings(entity_id);
CREATE INDEX idx_mapping_source ON account_mappings(source_account_code);
CREATE INDEX idx_mapping_target ON account_mappings(mapped_account_id);


-- =============================================================================
-- TABLE 12: unit_conversions (SUPPLEMENTARY)
-- =============================================================================
-- Lookup table for Indian number system unit conversions.
-- Used to normalize all amounts to absolute rupees.
-- =============================================================================

CREATE TABLE IF NOT EXISTS unit_conversions (
    unit_name           TEXT PRIMARY KEY,                    -- 'lakhs', 'crores', etc.
    unit_label          TEXT NOT NULL,                       -- Display label: '₹ in Lakhs'
    multiplier          DOUBLE NOT NULL,                     -- Factor to convert to absolute: 100000 for lakhs
    description         TEXT
);

INSERT INTO unit_conversions VALUES ('absolute',   '₹',              1,           'Absolute rupees');
INSERT INTO unit_conversions VALUES ('thousands',  '₹ in Thousands', 1000,        'Thousands of rupees');
INSERT INTO unit_conversions VALUES ('lakhs',      '₹ in Lakhs',     100000,      'Lakhs of rupees (1 Lakh = 100,000)');
INSERT INTO unit_conversions VALUES ('crores',     '₹ in Crores',    10000000,    'Crores of rupees (1 Crore = 10,000,000)');
INSERT INTO unit_conversions VALUES ('millions',   '₹ in Millions',  1000000,     'Millions of rupees');
INSERT INTO unit_conversions VALUES ('billions',   '₹ in Billions',  1000000000,  'Billions of rupees');


-- =============================================================================
-- SEED DATA: Schedule III Chart of Accounts (Ind AS — Division II)
-- =============================================================================
-- Top 3 levels of the hierarchy. Leaf accounts added per company.
-- =============================================================================

-- Balance Sheet: EQUITY AND LIABILITIES
INSERT INTO accounts (account_id, account_code, account_name, parent_account_id, account_level, account_type, statement_type, schedule_iii_ref, normal_balance, is_posting, display_order)
VALUES
-- Root
('BS',         '0',      'Balance Sheet',                        NULL,       0, 'header',    'balance_sheet', NULL,                       'not_applicable', 0, 0),

-- EQUITY AND LIABILITIES
('BS.EL',      '1',      'Equity and Liabilities',               'BS',       1, 'header',    'balance_sheet', 'Part I',                   'credit',         0, 1),

-- 1. Shareholders Funds
('BS.EL.SF',   '1.1',    'Shareholders Funds',                   'BS.EL',    2, 'header',    'balance_sheet', 'Part I, I(1)',              'credit',         0, 1),
('BS.EL.SF.SC','1.1.1',  'Share Capital',                        'BS.EL.SF', 3, 'equity',    'balance_sheet', 'Part I, I(1)(a)',           'credit',         1, 1),
('BS.EL.SF.RS','1.1.2',  'Reserves and Surplus',                 'BS.EL.SF', 3, 'equity',    'balance_sheet', 'Part I, I(1)(b)',           'credit',         1, 2),
('BS.EL.SF.MW','1.1.3',  'Money Received Against Share Warrants', 'BS.EL.SF', 3, 'equity',    'balance_sheet', 'Part I, I(1)(c)',           'credit',         1, 3),

-- 2. Share Application Money Pending Allotment
('BS.EL.SA',   '1.2',    'Share Application Money Pending Allotment', 'BS.EL', 2, 'equity', 'balance_sheet', 'Part I, I(2)',             'credit',         1, 2),

-- 3. Non-Current Liabilities
('BS.EL.NCL',     '1.3',    'Non-Current Liabilities',           'BS.EL',       2, 'header',    'balance_sheet', 'Part I, I(3)',           'credit',         0, 3),
('BS.EL.NCL.LTB', '1.3.1',  'Long-Term Borrowings',             'BS.EL.NCL',   3, 'liability', 'balance_sheet', 'Part I, I(3)(a)',        'credit',         1, 1),
('BS.EL.NCL.DTL', '1.3.2',  'Deferred Tax Liabilities (Net)',    'BS.EL.NCL',   3, 'liability', 'balance_sheet', 'Part I, I(3)(b)',        'credit',         1, 2),
('BS.EL.NCL.OTL', '1.3.3',  'Other Long-Term Liabilities',      'BS.EL.NCL',   3, 'liability', 'balance_sheet', 'Part I, I(3)(c)',        'credit',         1, 3),
('BS.EL.NCL.LTP', '1.3.4',  'Long-Term Provisions',             'BS.EL.NCL',   3, 'liability', 'balance_sheet', 'Part I, I(3)(d)',        'credit',         1, 4),

-- 4. Current Liabilities
('BS.EL.CL',      '1.4',    'Current Liabilities',              'BS.EL',       2, 'header',    'balance_sheet', 'Part I, I(4)',           'credit',         0, 4),
('BS.EL.CL.STB',  '1.4.1',  'Short-Term Borrowings',            'BS.EL.CL',    3, 'liability', 'balance_sheet', 'Part I, I(4)(a)',        'credit',         1, 1),
('BS.EL.CL.TP',   '1.4.2',  'Trade Payables',                   'BS.EL.CL',    3, 'liability', 'balance_sheet', 'Part I, I(4)(b)',        'credit',         1, 2),
('BS.EL.CL.OCL',  '1.4.3',  'Other Current Liabilities',        'BS.EL.CL',    3, 'liability', 'balance_sheet', 'Part I, I(4)(c)',        'credit',         1, 3),
('BS.EL.CL.STP',  '1.4.4',  'Short-Term Provisions',            'BS.EL.CL',    3, 'liability', 'balance_sheet', 'Part I, I(4)(d)',        'credit',         1, 4),

-- ASSETS
('BS.A',       '2',      'Assets',                               'BS',       1, 'header',    'balance_sheet', 'Part I, II',               'debit',          0, 2),

-- 1. Non-Current Assets
('BS.A.NCA',       '2.1',    'Non-Current Assets',               'BS.A',        2, 'header',    'balance_sheet', 'Part I, II(1)',          'debit',          0, 1),
('BS.A.NCA.PPE',   '2.1.1',  'Property, Plant and Equipment',    'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(a)(i)',    'debit',          1, 1),
('BS.A.NCA.IA',    '2.1.2',  'Intangible Assets',                'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(a)(ii)',   'debit',          1, 2),
('BS.A.NCA.CWIP',  '2.1.3',  'Capital Work-in-Progress',         'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(a)(iii)',  'debit',          1, 3),
('BS.A.NCA.IAUD',  '2.1.4',  'Intangible Assets under Development','BS.A.NCA',  3, 'asset',     'balance_sheet', 'Part I, II(1)(a)(iv)',   'debit',          1, 4),
('BS.A.NCA.NCI',   '2.1.5',  'Non-Current Investments',          'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(b)',       'debit',          1, 5),
('BS.A.NCA.DTA',   '2.1.6',  'Deferred Tax Assets (Net)',         'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(c)',       'debit',          1, 6),
('BS.A.NCA.LTLA',  '2.1.7',  'Long-Term Loans and Advances',     'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(d)',       'debit',          1, 7),
('BS.A.NCA.ONCA',  '2.1.8',  'Other Non-Current Assets',         'BS.A.NCA',    3, 'asset',     'balance_sheet', 'Part I, II(1)(e)',       'debit',          1, 8),

-- 2. Current Assets
('BS.A.CA',        '2.2',    'Current Assets',                   'BS.A',        2, 'header',    'balance_sheet', 'Part I, II(2)',          'debit',          0, 2),
('BS.A.CA.CI',     '2.2.1',  'Current Investments',              'BS.A.CA',     3, 'asset',     'balance_sheet', 'Part I, II(2)(a)',       'debit',          1, 1),
('BS.A.CA.INV',    '2.2.2',  'Inventories',                      'BS.A.CA',     3, 'asset',     'balance_sheet', 'Part I, II(2)(b)',       'debit',          1, 2),
('BS.A.CA.TR',     '2.2.3',  'Trade Receivables',                'BS.A.CA',     3, 'asset',     'balance_sheet', 'Part I, II(2)(c)',       'debit',          1, 3),
('BS.A.CA.CCE',    '2.2.4',  'Cash and Cash Equivalents',        'BS.A.CA',     3, 'asset',     'balance_sheet', 'Part I, II(2)(d)',       'debit',          1, 4),
('BS.A.CA.STLA',   '2.2.5',  'Short-Term Loans and Advances',    'BS.A.CA',     3, 'asset',     'balance_sheet', 'Part I, II(2)(e)',       'debit',          1, 5),
('BS.A.CA.OCA',    '2.2.6',  'Other Current Assets',             'BS.A.CA',     3, 'asset',     'balance_sheet', 'Part I, II(2)(f)',       'debit',          1, 6),

-- STATEMENT OF PROFIT AND LOSS
('PL',             '3',      'Statement of Profit and Loss',     NULL,          0, 'header',    'profit_and_loss', NULL,                    'not_applicable', 0, 0),

-- Revenue
('PL.REV',         '3.1',    'Revenue',                          'PL',          1, 'header',    'profit_and_loss', 'Part II, I',            'credit',         0, 1),
('PL.REV.OPS',     '3.1.1',  'Revenue from Operations',          'PL.REV',      2, 'revenue',   'profit_and_loss', 'Part II, I(i)',         'credit',         1, 1),
('PL.REV.OTH',     '3.1.2',  'Other Income',                     'PL.REV',      2, 'revenue',   'profit_and_loss', 'Part II, I(ii)',        'credit',         1, 2),
('PL.REV.TOT',     '3.1.3',  'Total Revenue (I+II)',             'PL.REV',      2, 'subtotal',  'profit_and_loss', 'Part II, I(iii)',       'credit',         0, 3),

-- Expenses
('PL.EXP',         '3.2',    'Expenses',                         'PL',          1, 'header',    'profit_and_loss', 'Part II, II',           'debit',          0, 2),
('PL.EXP.CMAT',    '3.2.1',  'Cost of Materials Consumed',       'PL.EXP',      2, 'expense',   'profit_and_loss', 'Part II, II(a)',        'debit',          1, 1),
('PL.EXP.PURCH',   '3.2.2',  'Purchases of Stock-in-Trade',      'PL.EXP',      2, 'expense',   'profit_and_loss', 'Part II, II(b)',        'debit',          1, 2),
('PL.EXP.CINV',    '3.2.3',  'Changes in Inventories of FG, WIP and Stock-in-Trade','PL.EXP',2,'expense','profit_and_loss','Part II, II(c)','debit',       1, 3),
('PL.EXP.EMP',     '3.2.4',  'Employee Benefits Expense',        'PL.EXP',      2, 'expense',   'profit_and_loss', 'Part II, II(d)',        'debit',          1, 4),
('PL.EXP.FIN',     '3.2.5',  'Finance Costs',                    'PL.EXP',      2, 'expense',   'profit_and_loss', 'Part II, II(e)',        'debit',          1, 5),
('PL.EXP.DEP',     '3.2.6',  'Depreciation and Amortisation Expense','PL.EXP',  2, 'expense',   'profit_and_loss', 'Part II, II(f)',        'debit',          1, 6),
('PL.EXP.OTH',     '3.2.7',  'Other Expenses',                   'PL.EXP',      2, 'expense',   'profit_and_loss', 'Part II, II(g)',        'debit',          1, 7),
('PL.EXP.TOT',     '3.2.8',  'Total Expenses',                   'PL.EXP',      2, 'subtotal',  'profit_and_loss', 'Part II, II(h)',        'debit',          0, 8),

-- Profit items
('PL.PBT',         '3.3',    'Profit Before Exceptional Items and Tax','PL',     1, 'subtotal',  'profit_and_loss', 'Part II, III',          'credit',         0, 3),
('PL.EXCEP',       '3.4',    'Exceptional Items',                'PL',          1, 'header',    'profit_and_loss', 'Part II, IV',           'not_applicable', 1, 4),
('PL.PBET',        '3.5',    'Profit Before Tax',                'PL',          1, 'subtotal',  'profit_and_loss', 'Part II, V',            'credit',         0, 5),
('PL.TAX',         '3.6',    'Tax Expense',                      'PL',          1, 'header',    'profit_and_loss', 'Part II, VI',           'debit',          0, 6),
('PL.TAX.CUR',     '3.6.1',  'Current Tax',                      'PL.TAX',      2, 'expense',   'profit_and_loss', 'Part II, VI(1)',        'debit',          1, 1),
('PL.TAX.DEF',     '3.6.2',  'Deferred Tax',                     'PL.TAX',      2, 'expense',   'profit_and_loss', 'Part II, VI(2)',        'debit',          1, 2),
('PL.PAT',         '3.7',    'Profit After Tax',                 'PL',          1, 'subtotal',  'profit_and_loss', 'Part II, VII',          'credit',         0, 7),
('PL.OCI',         '3.8',    'Other Comprehensive Income',       'PL',          1, 'header',    'profit_and_loss', 'Part II, VIII',         'credit',         1, 8),
('PL.TCI',         '3.9',    'Total Comprehensive Income',       'PL',          1, 'subtotal',  'profit_and_loss', 'Part II, IX',           'credit',         0, 9),
('PL.EPS',         '3.10',   'Earnings Per Share',               'PL',          1, 'header',    'profit_and_loss', 'Part II, X',            'not_applicable', 0, 10),
('PL.EPS.BASIC',   '3.10.1', 'Basic EPS',                        'PL.EPS',      2, 'total',     'profit_and_loss', 'Part II, X(i)',         'not_applicable', 1, 1),
('PL.EPS.DILUTED', '3.10.2', 'Diluted EPS',                      'PL.EPS',      2, 'total',     'profit_and_loss', 'Part II, X(ii)',        'not_applicable', 1, 2),

-- CASH FLOW STATEMENT
('CF',             '4',      'Cash Flow Statement',              NULL,          0, 'header',    'cash_flow',       NULL,                    'not_applicable', 0, 0),
('CF.OPS',         '4.1',    'Cash Flow from Operating Activities','CF',        1, 'header',    'cash_flow',       'Ind AS 7',              'debit',          1, 1),
('CF.INV',         '4.2',    'Cash Flow from Investing Activities','CF',        1, 'header',    'cash_flow',       'Ind AS 7',              'debit',          1, 2),
('CF.FIN',         '4.3',    'Cash Flow from Financing Activities','CF',        1, 'header',    'cash_flow',       'Ind AS 7',              'debit',          1, 3),
('CF.NET',         '4.4',    'Net Increase/(Decrease) in Cash',   'CF',         1, 'subtotal',  'cash_flow',       'Ind AS 7',              'debit',          0, 4),
('CF.OPEN',        '4.5',    'Cash and Cash Equivalents at Beginning','CF',     1, 'total',     'cash_flow',       'Ind AS 7',              'debit',          1, 5),
('CF.CLOSE',       '4.6',    'Cash and Cash Equivalents at End',  'CF',         1, 'total',     'cash_flow',       'Ind AS 7',              'debit',          1, 6);


-- =============================================================================
-- VIEWS: Pre-built analytical queries
-- =============================================================================

-- View: Primary (de-duplicated) line items per entity/account/period
CREATE VIEW IF NOT EXISTS v_primary_line_items AS
SELECT
    li.line_item_id,
    e.legal_name AS entity_name,
    a.account_name,
    a.account_type,
    a.statement_type,
    a.schedule_iii_ref,
    li.period_label,
    li.period_start,
    li.period_end,
    li.amount_absolute,
    li.source_unit,
    li.amount_original,
    li.is_comparative,
    d.document_type,
    d.audit_status,
    li.source_page,
    li.extraction_confidence
FROM line_items li
JOIN entities e ON li.entity_id = e.entity_id
JOIN accounts a ON li.account_id = a.account_id
JOIN documents d ON li.document_id = d.document_id
WHERE li.is_primary_source = TRUE;


-- View: Balance Sheet equation check
CREATE VIEW IF NOT EXISTS v_bs_equation_check AS
SELECT
    li.entity_id,
    li.period_label,
    SUM(CASE WHEN a.account_id LIKE 'BS.A.%' THEN li.amount_absolute ELSE 0 END) AS total_assets,
    SUM(CASE WHEN a.account_id LIKE 'BS.EL.%' THEN li.amount_absolute ELSE 0 END) AS total_equity_liabilities,
    SUM(CASE WHEN a.account_id LIKE 'BS.A.%' THEN li.amount_absolute ELSE 0 END)
    - SUM(CASE WHEN a.account_id LIKE 'BS.EL.%' THEN li.amount_absolute ELSE 0 END) AS difference
FROM line_items li
JOIN accounts a ON li.account_id = a.account_id
WHERE li.is_primary_source = TRUE
  AND a.statement_type = 'balance_sheet'
  AND a.is_posting = TRUE
GROUP BY li.entity_id, li.period_label;


-- View: Open forensic flags summary
CREATE VIEW IF NOT EXISTS v_open_flags_summary AS
SELECT
    f.flag_type,
    f.severity,
    COUNT(*) AS flag_count,
    SUM(f.affected_amount) AS total_affected_amount,
    e.legal_name AS entity_name
FROM flags f
JOIN entities e ON f.entity_id = e.entity_id
WHERE f.status IN ('open', 'under_review', 'escalated')
GROUP BY f.flag_type, f.severity, e.legal_name
ORDER BY
    CASE f.severity
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        WHEN 'low' THEN 4
        WHEN 'info' THEN 5
    END,
    flag_count DESC;


-- View: Reconciliation breaks
CREATE VIEW IF NOT EXISTS v_reconciliation_breaks AS
SELECT
    r.reconciliation_type,
    r.description,
    r.period_label,
    r.source_a_label,
    r.source_a_amount,
    r.source_b_label,
    r.source_b_amount,
    r.difference,
    r.difference_pct,
    r.match_status,
    e.legal_name AS entity_name
FROM reconciliation r
JOIN entities e ON r.entity_id = e.entity_id
WHERE r.is_matched = 0
ORDER BY ABS(r.difference) DESC;
