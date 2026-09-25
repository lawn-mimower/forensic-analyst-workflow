# Benchmark results

Two questions, each asked of the repository's methods and of conventional baselines:

1. **Question answering.** Does the LightRAG knowledge graph answer questions about a company's financial statements better than a basic retrieve-then-read pipeline, or than putting the whole report into one prompt?
2. **Issue detection.** Do the forensic workbench and the compliance audit flag issues planted in the statements, compared with one LLM call and with a few simple rules?

Everything is small and synthetic: 5 fictional companies, 30 questions, 14 planted issues. The main runs use a local gpt-oss:20b for every LLM call, so nothing here cost anything to run; the cheapest baseline was also run on the Gemini API free tier. Read the numbers as a smoke test of the methods, not as accuracy figures that carry over to real annual reports. Conditions and caveats follow the tables.

## Data

`benchmarks/generate_dataset.py` builds five fictional Indian private companies from specifications in the script with fixed seeds. Re-running it reproduces the files (`tests/test_benchmarks.py` checks the text files byte for byte). No real company documents or figures are used. For each company, `benchmarks/data/<company>/` holds:

| File | Content |
|---|---|
| `annual_report.md`, `.pdf` | Directors' report extract (with the directors' interests disclosed in Form MBP-1 and the Section 188 / AOC-2 statement), balance sheet, P&L, selected notes (borrowings, other expenses, related parties under AS 18), the independent auditor's report and, where present, the CARO annexure. 2,085–2,547 tokens (o200k_base). |
| `financials.xlsx` | Balance sheet, P&L and related-party schedule, Rs. lakhs |
| `general_ledger.csv` | Expense-voucher register for FY 2024-25 in rupees, 827–858 rows: amounts log-uniform between Rs. 100 and Rs. 10 lakh (four whole decades, so the leading digits follow Benford's law), plus monthly rent and security payments of fixed amounts |

`benchmarks/data/ground_truth.json` has every figure, the planted issues and the decoys. `benchmarks/data/qa.json` has the 30 questions (6 per company: 10 lookups, 6 calculations, 7 related-party facts, 7 multi-hop questions that need two notes) with gold answers computed from the same specifications.

Planted issues (14 of the 45 company × issue-type pairs):

| Company | Planted issues | Decoys |
|---|---|---|
| Kestrel Polymers | sale of land to a director's LLP for 23% of net worth, reported as needing no members' approval (`rpt_threshold_no_approval`); no CARO statement (`caro_missing`); 4 vouchers posted twice (`duplicate_entries`); one Rs. 1.85 crore consultancy payment (`unusual_large_payment`) | |
| Tarangini Foods | purchases from a director's firm, visible in MBP-1 and the expense note, missing from the related-party note (`rp_omitted_from_schedule`); 35% of ledger amounts rounded to thousands (`round_number_entries`); 120 invoices just below the Rs. 50,000 two-director approval limit (`benford_nonconformity`) | |
| Northfield Fabricators | 5 vouchers posted twice; gross margin up 23 points on 4% revenue growth, inventories up 78% (`ratio_anomaly`); a Rs. 4.50 lakh loan accepted in cash from a director's relative (`cash_loan_269ss`) | |
| Vardhan Precision Castings | none (control) | a related-party machinery purchase at 11% of net worth that *was* approved by special resolution and disclosed in AOC-2; a sentence saying no loan was accepted in cash; a director's firm that is paid in the ledger *and* listed in the related-party note |
| Meridian Agro Exports | payments to a director's LLP missing from the related-party note; no CARO statement; 35% round amounts; trade receivables up 95% on 6% revenue growth (`ratio_anomaly`) | |

## Systems

| System | What runs | Inputs | LLM calls |
|---|---|---|---|
| LightRAG *mode* | The repo's knowledge graph: `skills.shared.lightrag_init.get_rag_instance` (1,200-token chunks, 100 overlap, all-MiniLM-L6-v2 embeddings), one store per company, queried with `QueryParam(mode, top_k=40)` and LightRAG's own answer prompt | `annual_report.md` | indexing: entity extraction per chunk plus gleaning; per question: keyword extraction + answer (naive mode: answer only) |
| A: basic RAG | 256-token chunks (32 overlap), top 4 by Okapi BM25 or by MiniLM cosine, one answer call (`benchmarks/basic_rag.py`) | `annual_report.md` | 1 per question |
| B: whole report | The whole report in the prompt; either one call per question, or one call per company that answers that company's 6 questions as JSON | `annual_report.md` | 1 per question, or 1 per company |
| Workbench (raw) | The repo's table pipeline (`TableExtractor` → `DataNormalizer` → DuckDB) and the five forensic tests on the raw tables, as `pipeline.test_normalization --run-skills` runs them | `financials.xlsx`, `general_ledger.csv` | none |
| Workbench (auto-curated) | The same through `frontend.pipeline_runner.run_pipeline`, which inspects and auto-curates the tables first (the app and agent path) | same | none |
| Compliance audit | The repo's five phases (`skills/compliance-checker/scripts/run_pipeline.py`) on the company's LightRAG store, with the law file restricted to three sections: Companies Act s.143 → `caro_missing`, Income Tax Act s.269SS → `cash_loan_269ss`, SA 550 → `rp_omitted_from_schedule` | LightRAG store of `annual_report.md` | profile, category choice, one atomisation call per section, one retrieval (keyword) call and one adjudication per question |
| B: one LLM call per company | Whole report and ledger in one prompt, asked for red flags in the nine categories as JSON | `annual_report.md`, `general_ledger.csv` (~27k tokens) | 1 per company |
| Floor | Simple rules, one per issue type: exact duplicate (date, account, party, amount); ≥ 15% of amounts multiples of Rs. 1,000; ≥ 8% of amounts in the 20% band below the stated approval limit; a payment ≥ 2% of revenue; a ≥ 10-point move in gross margin, receivables/revenue or inventories/revenue; a related-party transaction ≥ 10% of net worth; a director-interest entity paid in the ledger but absent from the related-party schedule; no mention of the CARO order; a sentence with "loan"/"deposit" and "in cash" (`benchmarks/floor_rules.py`) | all three files | none |

How outputs become flags was fixed in `benchmarks/run_issues.py` before the systems were run. Workbench: Benford first-digit verdict `NON_CONFORMING` → `benford_nonconformity`; at least one exact-duplicate group → `duplicate_entries`; amounts ending in 00 ≥ 15% (the duplicate detector's own lowest round-number risk tier) → `round_number_entries`; any ratio-analyzer flag → `ratio_anomaly`; at least one consensus anomaly → `unusual_large_payment`; the network analyzer's findings (hubs, cycles) have no matching planted type and are not scored. Compliance audit: any `VIOLATION` verdict on a section flags that section's type.

## Question answering

All 30 questions, every LLM call by gpt-oss:20b (see *Exact conditions*). Strict = the `ANSWER:` line matches the gold answer; lenient = the gold answer appears anywhere in the response.

| System | Correct, strict [95% CI] | Lenient | lookup | calculation | related_party | multi_hop | LLM calls / q | Prompt tokens / q | Median latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|
| B: whole report, 1 call per question | 29/30 (97%) [83–99%] | 29/30 (97%) | 9/10 (90%) | 6/6 (100%) | 7/7 (100%) | 7/7 (100%) | 1 | 2,426 | 1.9 |
| A: basic RAG (BM25 top-4) | 26/30 (87%) [70–95%] | 26/30 (87%) | 7/10 (70%) | 6/6 (100%) | 7/7 (100%) | 6/7 (86%) | 1 | 1,162 | 1.9 |
| A: basic RAG (MiniLM top-4) | 21/30 (70%) [52–83%] | 21/30 (70%) | 4/10 (40%) | 5/6 (83%) | 7/7 (100%) | 5/7 (71%) | 1 | 1,162 | 2.2 |
| B: whole report, 1 call per company | 27/30 (90%) [74–96%] | 27/30 (90%) | 10/10 (100%) | 4/6 (67%) | 7/7 (100%) | 6/7 (86%) | 0.2 | 440 | 1.4 |
| LightRAG hybrid | 30/30 (100%) [89–100%] | 30/30 (100%) | 10/10 (100%) | 6/6 (100%) | 7/7 (100%) | 7/7 (100%) | 2 | 7,450 | 12.4 |
| LightRAG mix | 30/30 (100%) [89–100%] | 30/30 (100%) | 10/10 (100%) | 6/6 (100%) | 7/7 (100%) | 7/7 (100%) | 2 | 7,451 | 12.4 |
| LightRAG naive | 28/30 (93%) [79–98%] | 28/30 (93%) | 10/10 (100%) | 6/6 (100%) | 7/7 (100%) | 5/7 (71%) | 1 | 3,362 | 2.3 |
| LightRAG local | 28/30 (93%) [79–98%] | 29/30 (97%) | 10/10 (100%) | 5/6 (83%) | 7/7 (100%) | 6/7 (86%) | 2 | 7,069 | 12.2 |
| LightRAG global | 29/30 (97%) [83–99%] | 30/30 (100%) | 10/10 (100%) | 5/6 (83%) | 7/7 (100%) | 7/7 (100%) | 2 | 6,619 | 12.1 |

The same questions through Gemini 3.1 Flash-Lite, cheapest form only (one call per company, six questions at a time):

| System | Correct, strict [95% CI] | Lenient | lookup | calculation | related_party | multi_hop | LLM calls / q | Prompt tokens / q | Median latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|
| B: whole report, 1 call per company | 30/30 (100%) [89–100%] | 30/30 (100%) | 10/10 (100%) | 6/6 (100%) | 7/7 (100%) | 7/7 (100%) | 0.2 | 440 | 3.3 |

And through llama3.2 (3B), the two one-call baselines on all 30 questions, for the size of the model effect:

| System | Correct, strict [95% CI] | Lenient | lookup | calculation | related_party | multi_hop | LLM calls / q | Prompt tokens / q | Median latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|
| B: whole report, 1 call per question | 16/30 (53%) [36–70%] | 18/30 (60%) | 8/10 (80%) | 0/6 (0%) | 5/7 (71%) | 3/7 (43%) | 1 | 2,426 | 11.1 |
| A: basic RAG (BM25 top-4) | 16/30 (53%) [36–70%] | 17/30 (57%) | 7/10 (70%) | 2/6 (33%) | 6/7 (86%) | 1/7 (14%) | 1 | 1,162 | 33.6 |

Knowledge-graph indexing with gpt-oss:20b (one LightRAG store per company; the QA rows above do not include these costs):

| Company | Status | Entities | Relations | LLM calls | Prompt tokens | Completion tokens | Wall time (s) |
|---|---|---|---|---|---|---|---|
| kestrel | processed | 27 | 23 | 6 | 28,269 | 3,704 | 151.6 |
| meridian | processed | 28 | 27 | 4 | 20,503 | 3,248 | 125.9 |
| northfield | processed | 59 | 40 | 6 | 29,268 | 5,299 | 205.6 |
| tarangini | processed | 51 | 42 | 6 | 29,968 | 4,885 | 209.6 |
| vardhan | processed | 65 | 61 | 6 | 30,982 | 6,553 | 239.4 |

For comparison, llama3.2 took 1,048 s to index Kestrel and produced a graph of 14 entities and 2 relations; its partial LightRAG results are in `qa_local-llama3.2.json`.

## Issue detection

All five companies for every system. TP/FP/FN are counted over the 45 company × issue-type pairs (14 planted).

| System | LLM | Companies | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|
| Floor: simple rules | none | 5 | 14 | 2 | 0 | 0.88 | 1.00 | 0.93 |
| Workbench (raw tables) | none | 5 | 6 | 7 | 8 | 0.46 | 0.43 | 0.44 |
| Workbench (auto-curated) | none | 5 | 6 | 7 | 8 | 0.46 | 0.43 | 0.44 |
| B: one LLM call per company | gemini-3.1-flash-lite | 5 | 12 | 15 | 2 | 0.44 | 0.86 | 0.58 |
| B: one LLM call per company | gpt-oss-20b-ctx32k | 5 | 8 | 7 | 6 | 0.53 | 0.57 | 0.55 |
| Compliance audit (3 sections) | gpt-oss-20b-ctx16k | 5 | 1 | 2 | 13 | 0.33 | 0.07 | 0.12 |

Per issue type (planted issues found / planted; false positives):

| Issue type | Floor: simple rules | Workbench (raw tables) | Workbench (auto-curated) | B: one LLM call per company [gemini-3.1-flash-lite] | B: one LLM call per company [gpt-oss-20b-ctx32k] | Compliance audit (3 sections) [gpt-oss-20b-ctx16k] |
|---|---|---|---|---|---|---|
| rpt_threshold_no_approval | 1/1, 1 FP | 0/1 | 0/1 | 1/1, 2 FP | 1/1 | 0/1 |
| rp_omitted_from_schedule | 2/2 | 0/2 | 0/2 | 2/2, 3 FP | 1/2 | 0/2, 2 FP |
| duplicate_entries | 2/2 | 2/2, 3 FP | 0/2 | 0/2 | 0/2 | 0/2 |
| round_number_entries | 2/2 | 2/2 | 2/2 | 2/2, 1 FP | 1/2, 3 FP | 0/2 |
| benford_nonconformity | 1/1 | 1/1 | 1/1 | 1/1, 3 FP | 0/1 | 0/1 |
| caro_missing | 2/2 | 0/2 | 0/2 | 2/2 | 2/2 | 1/2 |
| ratio_anomaly | 2/2 | 0/2 | 2/2, 3 FP | 2/2, 2 FP | 2/2, 1 FP | 0/2 |
| cash_loan_269ss | 1/1, 1 FP | 0/1 | 0/1 | 1/1 | 0/1 | 0/1 |
| unusual_large_payment | 1/1 | 1/1, 4 FP | 1/1, 4 FP | 1/1, 4 FP | 1/1, 3 FP | 0/1 |

Cost per company (median over the five companies; the floor and the workbench make no LLM calls and run in seconds):

| System | LLM calls | Prompt tokens | Wall time |
|---|---|---|---|
| B: one LLM call per company, Gemini 3.1 Flash-Lite | 1 | 27,200 | 41 s (10–116 s, including retries) |
| B: one LLM call per company, gpt-oss:20b (32k context) | 1 | 27,200 | 320 s (254–472 s) |
| Compliance audit, three sections, gpt-oss:20b | 21–30 | 55,000–83,000 | 192 s (189–255 s), after indexing |

## What the results say

**Question answering.**

1. With gpt-oss:20b the QA set is close to its ceiling. LightRAG hybrid and mix answer 30/30, global and the whole-report baseline 29/30, naive and local 28/30. The 95% intervals all overlap; a difference of one or two questions is noise at this size. The set cannot separate the strong systems. It does separate them on cost: a graph query is 2 LLM calls and about 7,400 prompt tokens per question, against 2,400 for the whole report in one call and 1,200 for basic RAG, and a median 12 s against 2 s. Building the graph costs another 4–6 calls and 20,000–31,000 tokens per company (2–4 minutes each here).
2. Retrieval, not the graph, is what separates the cheaper systems. Basic RAG over 256-token chunks answers 26/30 with BM25 and 21/30 with MiniLM embeddings (lookups 7/10 and 4/10: the chunk holding the figure is not retrieved). LightRAG's naive mode, which is plain vector retrieval over its 1,200-token chunks and one answer call, answers 28/30. Chunk size matters more than the retrieval method on these documents.
3. The graph modes' only edge over naive mode is on the multi-hop questions (7/7 against 5/7), which need two notes at once. That is what the graph is for, but it rests on two questions.
4. The cheapest system is at the ceiling with the API model: one call per company answering six questions at once scores 30/30 on Gemini 3.1 Flash-Lite at 440 prompt tokens per question. On gpt-oss it scores 27/30, losing two of six calculations: the local model slips on arithmetic when answering six questions in one reply.
5. Model size dominates every method. On the identical whole-report prompt llama3.2 answers 16/30 (0/6 calculations) against gpt-oss's 29/30, and its knowledge graph for Kestrel had 14 entities and 2 relations after 17 minutes, against 27 entities and 23 relations in 2.5 minutes. The graph path needs a model at least as capable as gpt-oss:20b.

**Issue detection.**

1. The floor rules find all 14 planted issues with 2 false positives, both on the control company's decoys (the approved 11%-of-net-worth purchase trips the 10% threshold rule; the sentence saying no loan was taken in cash trips the "loan … in cash" rule). They were written knowing the plants; see the caveats.
2. The workbench (F1 0.44) finds the numeric issues it has tests for: duplicates (raw tables), round numbers, Benford non-conformity, ratio anomalies (curated tables, where the P&L figures are scaled correctly) and the large payment. Its false positives are systematic: the consensus anomaly detector flags an "unusual payment" in every ledger, including the four without one, and the ratio analyzer flags every curated company; the raw-table duplicate check fires on the three ledgers with no planted duplicates. The four text-only issue types are outside its inputs by design. Raw and curated runs differ in which tests work: curation dedups rows before the duplicate test can see them, and un-curated P&L figures are read as rupees, not lakhs, so the ratios do not fire.
3. One LLM call per company with the whole report and ledger is the best LLM system, and the two models fail differently. Gemini 3.1 Flash-Lite flags almost everything in every company (recall 0.86, precision 0.44; 4 false flags on the clean control company, "unusual payment" and "Benford" on all five). gpt-oss:20b is more conservative (recall 0.57, precision 0.53): it finds the text issues (CARO missing 2/2, the unapproved related-party sale, one of the two schedule omissions) and misses the ledger-level ones (duplicates 0/2, Benford 0/1, the cash loan), and it too reports an unusual payment and round numbers in clean ledgers. Neither model can count 800 ledger rows; both flag what a reader would flag from the narrative.
4. The compliance audit (F1 0.12: 1 true flag, 2 false, on 21–30 LLM calls per company) is the weakest system and the finding that matters most for this repository. Five of the fourteen planted issues fall under its three law sections; it found one, and that one by coincidence: a generated question asking whether the auditor reported any fraud was judged a violation on Kestrel because the report is silent, and the same question on Meridian was judged compliant. The causes are in the pipeline, not the model. (a) The atomiser turns a section into questions about what the auditor's report *states* ("does the report mention…"), so verdicts test wording, not facts. (b) The SA 550 questions ask whether the related-party note discloses the transactions it lists, which every note does; catching an omission needs the MBP-1 interests cross-referenced against the expense note, and no generated question does that. (c) Phase 0 chose only two of the three categories for Northfield, so Section 269SS never ran there; the SA 550 pass did see the Rs. 4.50 lakh cash loan and called it a violation, which the fixed mapping counts as a false "schedule omission". Targeted questions per section, derived from the planted mechanisms, would be the first thing to try.

## Exact conditions

Four runs, each in its own results files under `benchmarks/results/`:

- **deterministic** (`issues_deterministic.json`): floor rules and both workbench variants on all five companies. No LLM. Python 3.12.12, DuckDB 1.5.5, PyOD 3.6.6; every forensic test with its default parameters.
- **gemini-3.1-flash-lite** (`qa_gemini-3.1-flash-lite.json`, `issues_gemini-3.1-flash-lite.json`): Baseline B only, on all five companies, through the repo's `GeminiProvider` (google-genai 1.57.0) on the Gemini API free tier, temperature 0, the model's default thinking settings. 10 calls (5 for QA, one per company; 5 for issue detection, one per company) plus one 3-token availability probe. The intended model, gemini-2.5-flash-lite, and gemini-2.5-flash had already used up their free daily request quota on the shared key when the run started (HTTP 429, `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), so the next free-tier flash-lite model that answered was used. Several requests failed with HTTP 503 ("high demand") and were retried; the recorded latencies include the SDK's automatic retries.
- **local-gpt-oss-20b** (`qa_local-gpt-oss-20b.json`, `issues_local-gpt-oss-20b.json`, `issues_local-gpt-oss-20b-ctx32k.json`): every LLM call by gpt-oss:20b (21B parameters, 3.6B active, MXFP4, Ollama digest 17052f91) on Ollama 0.12.5 with an RTX 4070 SUPER (12 GB), through the `openai_compat` provider with `reasoning_effort: low` (`benchmarks/configs/ollama-gpt-oss-20b.yaml`). Two derived models with temperature 0 and seed 42: `gpt-oss-20b-ctx16k` (16k context, 80% of the weights on the GPU) built the five knowledge graphs, answered every QA system and ran the compliance audit; `gpt-oss-20b-ctx32k` (32k context, 77% on the GPU) answered the whole-report issue-detection prompt, which at about 27,000 tokens does not fit 16k. The same weights answered for every system, so the QA comparison is like for like. LightRAG's `LLM_TIMEOUT` was raised to 3,600 s and `EMBEDDING_TIMEOUT` to 600 s, and its own response cache was switched off so that every call went through the benchmark's cache and meter. The embedding model ran on the CPU. Nothing else was using the machine.
- **local-llama3.2** (`qa_local-llama3.2-all30.json`, `qa_local-llama3.2.json`): llama3.2 (3.2B, Q4_K_M, Ollama digest a80c4f17) with a 32k context, temperature 0, seed 42 and 4 threads (`benchmarks/configs/ollama-llama3.2.yaml`, `--model llama3.2-ctx32k-t4`), CPU only, on a machine shared with other jobs. The two one-call baselines on all 30 questions; a partial run of the other systems (18 questions, and LightRAG hybrid on Kestrel only) that was stopped once it was clear the model was too small for the graph path.

Token counts are o200k_base estimates of the text sent (system prompt, history and user prompt) and received, not provider-reported usage. Latency is wall-clock per question on that machine; a per-company call is split evenly over its six questions.

## Caveats

- **Small N.** 30 questions and 5 companies (14 planted issues, 45 scored pairs). The 95% intervals are wide; a difference of one or two questions or flags is noise.
- **Ceiling.** With gpt-oss:20b, six of the nine QA systems answer 28 or more of 30. The set is too easy to rank them; it separates them on cost, and it separates them from the weaker retrieval setups and the smaller model.
- **Short, clean documents.** Each report is about 2,300 tokens, so the whole report fits in any prompt and each LightRAG store has only 2–3 chunks. Retrieval barely matters at this size, which favours Baseline B. Real annual reports are 50–100 times longer; there, whole-document prompts cost more and retrieval matters more. This benchmark does not measure that regime.
- **Not the repo's configured models.** The repo is configured for Mistral `ministral-14b-2512` (graph building) and Gemini 3 Flash (compliance reasoning). The Mistral key was invalid and the Gemini free quota could not cover the call-heavy paths, so the knowledge-graph and compliance results here are from a local gpt-oss:20b. The Gemini numbers exist only for Baseline B; comparing them with the local runs mixes model and method.
- **The floor was written knowing the plants.** The same author planted the issues and wrote the floor rules, which target exactly those mechanisms (one rule per issue type), and one bug in them (sentence splitting at "Rs.") was fixed after running them on this data. Read the floor as what a targeted script can do here, not as a neutral baseline.
- **The LLM baseline was given the checklist.** Its prompt lists the nine issue categories so that its answer can be parsed; that is a strong hint an unprompted reviewer would not have.
- **Coverage by design.** The workbench reads only the XLSX and CSV tables, so the four text-only issue types (related-party approval and disclosure, CARO, cash loan) are outside its reach. The compliance audit ran on three law sections; the repo's law file has no entry for Section 188 or for CARO itself (its s.143 entry does not mention CARO), and no section covers the numeric issue types. Its F1 is computed over all 14 planted issues; over the 5 within its sections it is 1 found, 2 false.
- **Changes made after seeing outputs, before the reported runs.** (1) The first ledgers drew amounts from a non-whole number of decades and had about 400 rows, so the *clean* ledgers already failed Nigrini's first-digit MAD cut-off; the range was fixed and the ledgers enlarged (in simulation, 400-row clean ledgers with the monthly payments fail the cut-off about 40% of the time, 800-row ones about 2%). (2) Tarangini's ledger was shortened so that its issue-detection prompt fits a 32k context. (3) The answer-format instruction gained examples after llama3.2 put placeholder values such as "ANSWER: 1" on the answer line. (4) Numeric matching was tightened from a 0.5% tolerance to "equal to the precision written" after a wrong subtraction (51.35 for 51.15) was accepted. (5) The `openai_compat` provider gained a `reasoning_effort` setting for the gpt-oss run. All reported numbers come from the final data, prompts and scoring; the deterministic run was repeated on the final data.
- **Latency is indicative only.** The 20B model did not fit the 12 GB card entirely, and the 32k-context calls spent most of their 4–8 minutes processing the prompt on the CPU; on a larger GPU those calls take seconds. llama.cpp reuses the prompt prefix between consecutive calls with the same document (which helps the whole-report baseline), and the Gemini figures include retries.
- **Strict vs lenient.** The strict score reads only the `ANSWER:` line (or, failing that, the last line). LightRAG's own answer prompt asks for Markdown with a references section, and the answer-line instruction is passed as its `user_prompt`. The lenient column (gold answer anywhere in the response) shows how much of a gap is formatting; it is a diagnostic, not the headline.

## Reproducing and resuming

```bash
python benchmarks/generate_dataset.py      # rewrites benchmarks/data/ (identical output)

# No LLM
python benchmarks/run_issues.py --systems floor,workbench_raw,workbench_curated --run-label deterministic

# Local Ollama with gpt-oss:20b; create the two model variants once:
#   curl http://localhost:11434/api/create -d '{"model": "gpt-oss-20b-ctx16k", "from": "gpt-oss:20b",
#     "parameters": {"num_ctx": 16384, "temperature": 0, "seed": 42}}'
#   curl http://localhost:11434/api/create -d '{"model": "gpt-oss-20b-ctx32k", "from": "gpt-oss:20b",
#     "parameters": {"num_ctx": 32768, "temperature": 0, "seed": 42}}'
export CUDA_VISIBLE_DEVICES=""    # keep the embedding model off the GPU Ollama is using
LOCAL="--config benchmarks/configs/ollama-gpt-oss-20b.yaml --run-label local-gpt-oss-20b --resume"
python benchmarks/run_qa.py $LOCAL \
    --systems whole_doc,bm25,dense,whole_doc_batched,lightrag:hybrid,lightrag:mix,lightrag:naive,lightrag:local,lightrag:global
python benchmarks/run_issues.py $LOCAL --systems compliance_audit
python benchmarks/run_issues.py --config benchmarks/configs/ollama-gpt-oss-20b.yaml --model gpt-oss-20b-ctx32k \
    --run-label local-gpt-oss-20b-ctx32k --resume --systems llm_whole_doc

# Gemini free tier (GEMINI_API_KEY in the environment); calls are capped and paced
python benchmarks/run_qa.py --config benchmarks/configs/gemini-3.1-flash-lite.yaml \
    --run-label gemini-3.1-flash-lite --systems whole_doc_batched --max-new-calls 6 --min-interval 12
python benchmarks/run_issues.py --config benchmarks/configs/gemini-3.1-flash-lite.yaml \
    --run-label gemini-3.1-flash-lite --systems llm_whole_doc --max-new-calls 6 --min-interval 15

python benchmarks/summarise.py                                     # tables
```

LLM responses are cached in `benchmarks/.cache/` and per-item records (with the raw responses) are kept in `benchmarks/.work/<run-label>/`; both are git-ignored, so the committed results hold scores, parsed answers and costs but not raw model text. `--resume` continues a run; `--aggregate-only` rewrites a results file without calling any model; `--max-new-calls` stops a run cleanly when a cap or a provider quota is hit.

Not run: the other QA systems on Gemini (the free daily quota did not cover them) and the intended cheap model, gemini-2.5-flash-lite (`benchmarks/configs/gemini-2.5-flash-lite.yaml`); the llama3.2 config remains for a smaller-model comparison.
