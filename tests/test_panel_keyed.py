import polars as pl
import pytest

from brmunipanel.panel import build_keyed_table


def test_build_keyed_table_sorts():
    municipalities = pl.DataFrame({"municipality_code": ["1100015", "3550308"]})
    table = pl.DataFrame({
        "municipality_code": ["3550308", "1100015", "1100015"],
        "year": pl.Series([2010, 2011, 2010], dtype=pl.Int16),
        "network": ["state", "state", "municipal"],
        "v": [1, 2, 3],
    })
    sorted_table = build_keyed_table(municipalities, table, ["municipality_code", "year", "network"], "t")
    assert sorted_table.rows() == [
        ("1100015", 2010, "municipal", 3),
        ("1100015", 2011, "state", 2),
        ("3550308", 2010, "state", 1),
    ]


def test_build_keyed_table_errors():
    municipalities = pl.DataFrame({"municipality_code": ["1100015", "3550308"]})

    # Null keys
    null_table = pl.DataFrame({
        "municipality_code": ["1100015"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "network": [None],
    })
    with pytest.raises(ValueError, match="null keys"):
        build_keyed_table(municipalities, null_table, ["municipality_code", "year", "network"], "t")

    # Repeated keys
    dup_table = pl.DataFrame({
        "municipality_code": ["1100015", "1100015"],
        "year": pl.Series([2010, 2010], dtype=pl.Int16),
        "network": ["state", "state"],
    })
    with pytest.raises(ValueError, match="repeated keys"):
        build_keyed_table(municipalities, dup_table, ["municipality_code", "year", "network"], "t")

    # Code not in municipalities table
    invalid_code_table = pl.DataFrame({
        "municipality_code": ["9999999"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "network": ["state"],
    })
    with pytest.raises(ValueError, match="not in the municipalities table"):
        build_keyed_table(municipalities, invalid_code_table, ["municipality_code", "year", "network"], "t")

    # Missing column
    missing_col_table = pl.DataFrame({
        "municipality_code": ["1100015"],
        "year": pl.Series([2010], dtype=pl.Int16),
    })
    with pytest.raises(ValueError, match="Missing column"):
        build_keyed_table(municipalities, missing_col_table, ["municipality_code", "year", "network"], "t")
