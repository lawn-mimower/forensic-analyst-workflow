"""Tests for the relational schema helpers in schema/forensic_schema.py."""

from __future__ import annotations

import pytest

from schema import forensic_schema as fs


def test_example_data_is_empty_tables():
    tables = fs.create_example_data()
    assert set(tables) == set(fs.create_all_empty_dataframes())
    assert len(tables) == 13
    for name, df in tables.items():
        assert df.empty, name
        assert len(df.columns) > 0, name


@pytest.mark.parametrize("text,expected", [
    ("1,234.56", (1234.56, False)),
    ("(43.20)", (43.20, True)),
    ("₹ 420.30", (420.30, False)),
    ("Rs. 1,00,00,000", (10_000_000.0, False)),
    ("-57.25", (57.25, True)),
])
def test_parse_indian_number(text, expected):
    assert fs.parse_indian_number(text) == pytest.approx(expected)


def test_parse_indian_number_rejects_text():
    with pytest.raises(ValueError):
        fs.parse_indian_number("n/a")


def test_unit_conversion_round_trip():
    assert fs.normalize_to_absolute(850.0, "lakhs") == 85_000_000.0
    assert fs.normalize_to_absolute(2.5, "crores") == 25_000_000.0
    assert fs.absolute_to_display(85_000_000.0, "lakhs") == "₹ 850.00 L"
    assert fs.absolute_to_display(25_000_000.0, "crores") == "₹ 2.50 Cr"


def test_file_hash_and_ids(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"acme")
    assert len(fs.compute_file_hash(f)) == 64
    assert fs.generate_id() != fs.generate_id()


def test_sqlite_schema_initialises():
    conn = fs.init_sqlite(":memory:")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"entities", "documents", "line_items", "related_parties", "flags"} <= tables
