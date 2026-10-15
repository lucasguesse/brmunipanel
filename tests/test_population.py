"""Tests for the IBGE/SIDRA population module (brmunipanel.ibge.population)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ibge import population

FOLDER_DATA = Path(__file__).resolve().parent / "data"


def test_interpolate_manual() -> None:
    """Validate exact geometric interpolation calculation and discarding municipalities without neighbors."""
    estimates = pl.DataFrame(
        [
            # Municipality A ("1100015"): has 2006 (100) and 2008 (121) -> 2007 must be 110
            #                             has 2021 (1000) and 2024 (1331) -> 2022=1100, 2023=1210
            ("1100015", 2006, 100),
            ("1100015", 2008, 121),
            ("1100015", 2009, 500),
            ("1100015", 2011, 500),
            ("1100015", 2021, 1000),
            ("1100015", 2024, 1331),
            # Municipality B ("1200328"): has 2006, but does NOT have 2008 -> must not receive 2007
            #                             has 2021, but does NOT have 2024 -> must not receive 2022 nor 2023
            ("1200328", 2006, 100),
            ("1200328", 2009, 500),
            ("1200328", 2011, 500),
            ("1200328", 2021, 1000),
            # Municipality C ("3550308"): does NOT have 2006, has 2008 -> must not receive 2007
            ("3550308", 2008, 121),
            ("3550308", 2009, 500),
            ("3550308", 2011, 500),
            ("3550308", 2024, 1331),
        ],
        schema={"municipality_code": pl.String, "year": pl.Int16, "population": pl.Int64},
        orient="row",
    )

    interpolated = population.interpolate(estimates)

    # 1. Municipality A has 2007, 2010, 2022, and 2023
    res_a = interpolated.filter(pl.col("municipality_code") == "1100015").sort("year")
    assert res_a.filter(pl.col("year") == 2007)["population"].item() == 110
    assert res_a.filter(pl.col("year") == 2022)["population"].item() == 1100
    assert res_a.filter(pl.col("year") == 2023)["population"].item() == 1210

    # 2. Municipalities B and C must not receive years missing a neighbor
    assert interpolated.filter((pl.col("municipality_code") == "1200328") & (pl.col("year") == 2007)).height == 0
    assert interpolated.filter((pl.col("municipality_code") == "1200328") & (pl.col("year") == 2022)).height == 0
    assert interpolated.filter((pl.col("municipality_code") == "1200328") & (pl.col("year") == 2023)).height == 0
    assert interpolated.filter((pl.col("municipality_code") == "3550308") & (pl.col("year") == 2007)).height == 0
    assert interpolated.filter((pl.col("municipality_code") == "3550308") & (pl.col("year") == 2022)).height == 0


@pytest.fixture
def folder_sidra_population(tmp_path: Path) -> Path:
    folder_table = tmp_path / "t6579"
    folder_table.mkdir(parents=True, exist_ok=True)
    path_sample = FOLDER_DATA / "sidra_t6579_sample.json"
    samples_by_year = json.loads(path_sample.read_text(encoding="utf-8"))
    for year, blocks in samples_by_year.items():
        content = json.dumps(blocks).encode("utf-8")
        (folder_table / f"t6579_{year}.json.gz").write_bytes(gzip.compress(content, mtime=0))
    return tmp_path


def test_harmonize_sample(folder_sidra_population: Path) -> None:
    df = population.harmonize(folder_sidra_population)

    # 1. Schema
    assert df.schema == {
        "municipality_code": pl.String,
        "year": pl.Int16,
        "population": pl.Int64,
        "population_source": pl.String,
    }

    # 2. Window strictly 2006–2023 (without 2024)
    assert df["year"].min() == 2006
    assert df["year"].max() == 2023
    assert 2024 not in df["year"].unique().to_list()

    # 3. population_source is exactly 'interpolated' in 2007, 2010, 2022, and 2023, and 'estimate' in the others
    interpolated_years = {2007, 2010, 2022, 2023}
    for year in range(2006, 2024):
        sub = df.filter(pl.col("year") == year)
        sources = sub["population_source"].unique().to_list()
        if year in interpolated_years:
            assert sources == ["interpolated"], f"Expected only 'interpolated' for {year}, got {sources}"
        else:
            assert sources == ["estimate"], f"Expected only 'estimate' for {year}, got {sources}"

    # 4. No key duplication
    dups = df.group_by(["municipality_code", "year"]).agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    assert dups.height == 0
