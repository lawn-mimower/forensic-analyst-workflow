"""End-to-end tests for the five analysis skills and the data quality helpers.

The skills run as subprocesses against a DuckDB workbench that was built from
synthetic documents for the fictional Acme Widgets Private Limited
(see ``forensic_db`` in conftest.py), exactly as the pipeline runs them.
"""

from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from conftest import SKILL_SCRIPTS, load_script  # noqa: E402

COMPANY = "Acme Widgets Private Limited"
PNL_ONLY = "table_id IN (SELECT table_id FROM source_tables WHERE table_type = 'profit_and_loss')"


# ---------------------------------------------------------------------------
# Benford's Law
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def benfords():
    return load_script(SKILL_SCRIPTS["benfords-analysis"], "benfords_skill")


def test_benford_digit_tests_separate_natural_and_invented_amounts(benfords):
    rng = random.Random(11)
    natural = pd.Series([10 ** rng.uniform(1, 7) for _ in range(20000)])
    invented = pd.Series([round(rng.uniform(1000, 9999), 2) for _ in range(2000)])

    ok = benfords.compute_digit_test(
        natural, benfords.extract_first_digit, benfords.benford_expected_first_digit(),
        "first_digit", 0.05,
    )
    bad = benfords.compute_digit_test(
        invented, benfords.extract_first_digit, benfords.benford_expected_first_digit(),
        "first_digit", 0.05,
    )
    assert ok["mad_conformity"] == "CLOSE_CONFORMITY"
    assert bad["verdict"] == "NON_CONFORMING"
    assert {d["digit"] for d in bad["flagged_digits"] if d["direction"] == "excess"} >= {"7", "8", "9"}

    overall, risk = benfords.compute_overall_verdict({"first_digit": bad, "first_two": bad, "last_two": bad})
    assert overall == "ANOMALOUS" and 8 <= risk <= 10


def test_benford_digit_extraction(benfords):
    s = pd.Series([0.0452, 123.0, 7.0, 98765.4])
    assert benfords.extract_first_digit(s).tolist() == ["4", "1", "7", "9"]
    assert benfords.extract_second_digit(s).tolist() == ["5", "2", None, "8"]
    assert benfords.extract_first_two_digits(s).tolist() == ["45", "12", None, "98"]
    assert benfords.extract_last_two_digits(pd.Series([12345.0, 7.0, 1200.4])).tolist() == ["45", None, "00"]


def test_benfords_skill_sweep(forensic_db, tmp_path, skill_runner):
    rc, out, err = skill_runner(
        "benfords-analysis", forensic_db, tmp_path / "benfords.json",
        "--table", "line_items", "--column", "amount", "--tests", "all", "--case-id", "ACME-TEST",
    )
    assert rc == 0, err
    assert set(out["tests"]) == {"first_digit", "second_digit", "first_two", "last_two", "summation"}
    assert out["meta"]["case_id"] == "ACME-TEST"
    assert out["meta"]["records_analyzed"] >= 250
    # The ledger amounts are log-uniform, so the leading digits follow Benford
    assert out["tests"]["first_digit"]["verdict"] == "CONFORMING"
    assert out["overall_verdict"] in {"CONFORMING", "MARGINALLY_NON_CONFORMING", "NON_CONFORMING", "ANOMALOUS"}
    assert 1 <= out["overall_risk_score"] <= 10
    assert out["flagged_ranges"] or out["overall_verdict"] == "CONFORMING"


def test_benfords_skill_rejects_small_samples(forensic_db, tmp_path, skill_runner):
    rc, out, _ = skill_runner(
        "benfords-analysis", forensic_db, tmp_path / "small.json",
        "--table", "line_items", "--filter", PNL_ONLY,
    )
    assert rc == 1
    assert out["error"]["type"] == "INSUFFICIENT_RECORDS"
    assert out["overall_verdict"] == "ERROR"


def test_benfords_skill_reports_missing_table(forensic_db, tmp_path, skill_runner):
    rc, out, _ = skill_runner("benfords-analysis", forensic_db, tmp_path / "missing.json")
    assert rc == 1  # default --table is 'transactions'
    assert out["error"]["type"] == "TABLE_NOT_FOUND"
    assert "line_items" in out["error"]["message"]


# ---------------------------------------------------------------------------
# Duplicate detector
# ---------------------------------------------------------------------------
def test_duplicate_detector_finds_planted_duplicates(forensic_db, tmp_path, skill_runner):
    rc, out, err = skill_runner("duplicate-detector", forensic_db, tmp_path / "dups.json")
    assert rc == 0, err
    findings = out["findings"]

    exact = findings["exact_duplicates"]["details"]
    assert [(d["account_name"], d["amount"], d["count"]) for d in exact] == [("Office supplies", 45210.0, 2)]

    fuzzy = findings["fuzzy_name_duplicates"]["details"]
    assert {(d["name_a"], d["name_b"]) for d in fuzzy} == {("Office Supplies Expense", "Office Supplies Expenses")}

    near = {(d["account_name"], d["amount_a"], d["amount_b"]) for d in findings["near_amount_duplicates"]["details"]}
    assert ("Freight outward", 12500.0, 12540.0) in near

    # 'Equity share capital' is 100 in both balance-sheet years
    cross = {d["account_name"] for d in findings["cross_period_duplicates"]["details"]}
    assert "Equity share capital" in cross

    assert out["summary"]["total_records_analyzed"] == findings["round_number_concentration"]["n_analyzed"]
    assert 2 <= out["risk_score"] <= 10
    assert any("exact duplicate group" in s for s in out["investigation_suggestions"])


def test_duplicate_detector_on_empty_selection(forensic_db, tmp_path, skill_runner):
    rc, out, _ = skill_runner(
        "duplicate-detector", forensic_db, tmp_path / "none.json", "--filter", "account_name = 'No such account'",
    )
    assert rc == 0
    assert out["summary"] == {"total_records_analyzed": 0}
    assert out["risk_score"] == 1


# ---------------------------------------------------------------------------
# Ratio analyzer
# ---------------------------------------------------------------------------
def test_ratio_analyzer_on_profit_and_loss(forensic_db, tmp_path, skill_runner):
    rc, out, err = skill_runner(
        "ratio-analyzer", forensic_db, tmp_path / "ratios.json",
        "--filter", PNL_ONLY, "--change-threshold", "0.15",
    )
    assert rc == 0, err
    assert out["meta"]["periods_found"] == ["FY 2023-24", "FY 2024-25"]
    assert out["account_matching"]["Revenue from operations"]["category"] == "revenue"
    assert out["account_matching"]["Cost of materials consumed"]["category"] == "cogs"

    current, prior = out["ratios_by_period"]["FY 2024-25"], out["ratios_by_period"]["FY 2023-24"]
    assert current["gross_margin"] == pytest.approx((850 - 410) / 850, abs=1e-6)
    assert prior["gross_margin"] == pytest.approx((720 - 355) / 720, abs=1e-6)
    assert current["employee_expense_to_revenue"] == pytest.approx(145 / 850, abs=1e-6)

    revenue = out["yoy_growth"]["revenue"]
    assert (revenue["prior_amount"], revenue["current_amount"]) == (720.0, 850.0)
    assert revenue["pct_change"] == pytest.approx(130 / 720, abs=1e-4)
    # Revenue (+18%) and tax expense (+50%) move by more than the 15% threshold
    flagged = {f.get("account_category") for f in out["flagged_changes"] if f["type"] == "yoy_growth"}
    assert {"revenue", "tax_expense"} <= flagged
    assert 1 <= out["risk_score"] <= 10


def test_ratio_analyzer_with_a_single_period(forensic_db, tmp_path, skill_runner):
    rc, out, _ = skill_runner(
        "ratio-analyzer", forensic_db, tmp_path / "one.json",
        "--filter", f"{PNL_ONLY} AND period_label = 'FY 2024-25'",
    )
    assert rc == 0
    assert out["ratio_changes"] == [] and out["flagged_changes"] == []
    assert out["risk_score"] == 1
    assert "Only one period detected" in out["investigation_suggestions"][0]


# ---------------------------------------------------------------------------
# Anomaly detector
# ---------------------------------------------------------------------------
def test_anomaly_detector_flags_the_planted_outlier(forensic_db, tmp_path, skill_runner):
    rc, out, err = skill_runner(
        "anomaly-detector", forensic_db, tmp_path / "anomalies.json",
        "--table", "line_items", "--column", "amount",
    )
    assert rc == 0, err
    top = out["anomalies"][0]
    assert top["account_name"] == "Consultancy - Sample Advisors LLP"
    assert top["amount"] == 98500000.0
    assert top["is_consensus_anomaly"]
    assert {"iqr", "zscore"} <= set(top["methods_flagged"])

    summary = out["summary"]
    assert summary["consensus_anomalies"] >= 1
    assert set(summary["breakdown_by_table_type"]) == {"other", "profit_and_loss", "balance_sheet"}
    if out["meta"]["pyod_available"]:
        assert "iforest" in summary["methods_used"]
    assert 1 <= out["risk_score"] <= 10


def test_anomaly_detector_needs_variance(forensic_db, tmp_path, skill_runner):
    rc, out, _ = skill_runner(
        "anomaly-detector", forensic_db, tmp_path / "flat.json",
        "--filter", "li.account_name = 'Equity share capital'",
    )
    assert rc == 1
    assert out["error"]["type"] == "NO_VARIANCE"


# ---------------------------------------------------------------------------
# Network analyzer
# ---------------------------------------------------------------------------
def test_network_analyzer_builds_related_party_graph(forensic_db, tmp_path, skill_runner):
    rc, out, err = skill_runner("network-analyzer", forensic_db, tmp_path / "network.json")
    assert rc == 0, err

    nodes = {n["entity"]: n for n in out["nodes"]}
    assert set(nodes) == {
        COMPANY, "Jane Doe", "Richard Roe", "Acme Holdings Private Limited",
        "Widget Tools LLP", "Sample Advisors LLP",
    }
    assert nodes[COMPANY]["degree"] == 5
    assert nodes["Jane Doe"]["total_amount"] == pytest.approx(1_200_000.0)
    # Widget Tools LLP both buys from and sells to the company: a two-party cycle
    assert [sorted(c) for c in out["cycles"]] == [[COMPANY, "Widget Tools LLP"]]
    assert out["graph_stats"]["n_nodes"] == 6 and out["graph_stats"]["is_connected"]
    assert out["risk_score"] >= 3
    assert any("circular relationship" in s for s in out["investigation_suggestions"])


def test_network_analyzer_without_related_parties(tmp_path, skill_runner):
    db = tmp_path / "no_rp.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE line_items (account_name TEXT, amount DOUBLE)")
    con.close()

    rc, out, _ = skill_runner("network-analyzer", db, tmp_path / "net.json")
    assert rc == 0
    assert "not found" in out["error"]
    assert out["nodes"] == [] and out["risk_score"] == 0


# ---------------------------------------------------------------------------
# Data inspector and curator
# ---------------------------------------------------------------------------
def test_inspector_profiles_the_workbench(forensic_db):
    from skills.shared.data_inspector import profile_database

    profile = profile_database(str(forensic_db)).to_dict()

    # '31 Mar 2025' and 'FY 2024-25' describe the same fiscal year
    assert profile["periods"]["suggested_map"] == {"31 Mar 2024": "FY 2023-24", "31 Mar 2025": "FY 2024-25"}
    assert profile["periods"]["canonical_labels"] == ["FY 2023-24", "FY 2024-25"]
    assert profile["duplicates"]["total_dup_groups"] == 1
    assert profile["units"]["mixed_units"] is False
    assert profile["related_parties"]["total_distinct"] == 5
    assert "Acme Holdings Private Limited" in profile["related_parties"]["suggested_whitelist"]
    assert profile["needs_curation"] is True


def test_inspector_on_missing_database(tmp_path):
    from skills.shared.data_inspector import profile_database

    profile = profile_database(str(tmp_path / "nope.duckdb"))
    assert profile.issues and "not found" in profile.issues[0]


def test_curator_builds_views_without_touching_raw_tables(forensic_db_copy):
    from skills.shared.data_curator import CurationConfig, auto_curate, curate, has_curated_views
    from skills.shared.data_inspector import profile_database

    assert not has_curated_views(str(forensic_db_copy))
    result = auto_curate(str(forensic_db_copy), profile_database(str(forensic_db_copy)).to_dict())

    assert result.views_created == ["curated_line_items", "curated_related_parties"]
    assert result.line_items_after == result.line_items_before - 1  # planted duplicate removed
    assert has_curated_views(str(forensic_db_copy))

    con = duckdb.connect(str(forensic_db_copy), read_only=True)
    periods = {r[0] for r in con.execute("SELECT DISTINCT period_label FROM curated_line_items").fetchall()}
    raw = con.execute("SELECT COUNT(*) FROM line_items").fetchone()[0]
    con.close()
    assert periods == {"FY 2023-24", "FY 2024-25"}
    assert raw == result.line_items_before

    # Manual config: exclude an account by regex and keep one related party
    manual = curate(str(forensic_db_copy), CurationConfig(
        deduplicate=False, exclude_account_patterns=["^Office"], entity_whitelist=["Jane Doe"],
    ))
    assert manual.related_parties_after == 2
    con = duckdb.connect(str(forensic_db_copy), read_only=True)
    office = con.execute(
        "SELECT COUNT(*) FROM curated_line_items WHERE account_name LIKE 'Office%'"
    ).fetchone()[0]
    con.close()
    assert office == 0


def test_skills_run_on_curated_views(forensic_db_copy, tmp_path, skill_runner):
    from skills.shared.data_curator import auto_curate
    from skills.shared.data_inspector import profile_database

    auto_curate(str(forensic_db_copy), profile_database(str(forensic_db_copy)).to_dict())

    rc, dups, err = skill_runner(
        "duplicate-detector", forensic_db_copy, tmp_path / "dups.json", "--table", "curated_line_items",
    )
    assert rc == 0, err
    assert dups["findings"]["exact_duplicates"]["duplicate_groups"] == 0

    rc, net, err = skill_runner(
        "network-analyzer", forensic_db_copy, tmp_path / "net.json", "--table", "curated_related_parties",
    )
    assert rc == 0, err
    assert net["graph_stats"]["n_nodes"] == 6

    assert np.isfinite(dups["risk_score"])
