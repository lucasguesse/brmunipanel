"""Tests for the IBGE/SIDRA CEMPRE module (brmunipanel.ibge.cempre)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ibge import cempre, sidra

FOLDER_DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture
def folder_sidra_cempre(tmp_path: Path) -> Path:
    path_sample = FOLDER_DATA / "sidra_cempre_sample.json"
    samples = json.loads(path_sample.read_text(encoding="utf-8"))
    for key, blocks in samples.items():
        table, year = key.split("_")
        folder_tab = tmp_path / f"t{table}"
        folder_tab.mkdir(parents=True, exist_ok=True)
        content = json.dumps(blocks).encode("utf-8")
        (folder_tab / f"t{table}_{year}.json.gz").write_bytes(gzip.compress(content, mtime=0))
    return tmp_path


def test_harmonize_cempre_schema(folder_sidra_cempre: Path) -> None:
    panel = cempre.harmonize(folder_sidra_cempre)

    # 1. Expected schema: municipality_code, year, and the 5 harmonized columns
    expected_schema = {
        "municipality_code": pl.String,
        "year": pl.Int16,
        "establishments_number": pl.Int64,
        "employed_total": pl.Int64,
        "employed_salaried": pl.Int64,
        "salaried_employees_avg": pl.Float64,
        "wages_thousand_brl": pl.Float64,
    }
    assert panel.schema == expected_schema

    # 2. Window strictly 2006–2023
    assert panel["year"].min() == 2006
    assert panel["year"].max() == 2023

    # 3. There are rows for years from both source tables (e.g. 2021 and 2022)
    assert 2021 in panel["year"].unique().to_list()
    assert 2022 in panel["year"].unique().to_list()

    # 4. Unique key and sorting
    dups = panel.group_by(["municipality_code", "year"]).agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    assert dups.height == 0
    assert panel.equals(panel.sort(["municipality_code", "year"]))


def test_cempre_download_request() -> None:
    req_2021 = sidra.year_request(1685, 2021, cempre.DOWNLOAD_VARIABLES)
    assert req_2021.url.endswith("1685/periodos/2021/variaveis/706|367|707|708|5944|662|1606|10143?localidades=N6[all]")
    
    req_2022 = sidra.year_request(9509, 2022, cempre.DOWNLOAD_VARIABLES)
    assert req_2022.url.endswith("9509/periodos/2022/variaveis/706|367|707|708|5944|662|1606|10143?localidades=N6[all]")

