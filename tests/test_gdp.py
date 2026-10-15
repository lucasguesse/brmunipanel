"""Tests for the Gross Domestic Product module (brmunipanel.ibge.gdp)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ibge import gdp
from brmunipanel.ibge import sidra


@pytest.fixture
def sample_5938_2022_bytes() -> bytes:
    path = Path(__file__).resolve().parent / "data" / "sidra_t5938_2022_sample.json"
    return path.read_bytes()


def test_harmonize(tmp_path: Path, sample_5938_2022_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    folder_table = tmp_path / "t5938"
    folder_table.mkdir(parents=True, exist_ok=True)
    (folder_table / "t5938_2022.json.gz").write_bytes(gzip.compress(sample_5938_2022_bytes, mtime=0))
    monkeypatch.setattr(gdp, "YEARS", [2022])

    panel = gdp.harmonize(tmp_path)

    assert isinstance(panel, pl.DataFrame)
    assert panel.columns == ["municipality_code", "year", "gdp"]
    assert panel.schema == {
        "municipality_code": pl.String,
        "year": pl.Int16,
        "gdp": pl.Float64,
    }
    # GDP in the 2022 sample must not be null
    assert panel["gdp"].null_count() == 0


def test_harmonize_with_null_marker(tmp_path: Path, sample_5938_2022_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    folder_table = tmp_path / "t5938"
    folder_table.mkdir(parents=True, exist_ok=True)
    
    (folder_table / "t5938_2022.json.gz").write_bytes(gzip.compress(sample_5938_2022_bytes, mtime=0))
    monkeypatch.setattr(gdp, "YEARS", [2022])
    len_normal = len(gdp.harmonize(tmp_path))
    
    data = json.loads(sample_5938_2022_bytes)
    code_modified_municipality = None
    # Search for variable 37 and set "..." in the 2022 series
    for variable_obj in data:
        if variable_obj["id"] == "37":
            series = variable_obj["resultados"][0]["series"][0]
            series["serie"]["2022"] = "..."
            code_modified_municipality = series["localidade"]["id"]
    
    (folder_table / "t5938_2022.json.gz").write_bytes(gzip.compress(json.dumps(data).encode("utf-8"), mtime=0))

    panel = gdp.harmonize(tmp_path)
    
    assert len(panel) == len_normal
    assert panel.filter(pl.col("municipality_code") == code_modified_municipality)["gdp"].item() is None


def test_variables_download() -> None:
    # The request must contain exactly the expected variables string so as not to break
    # the manifest and download everything again.
    req = sidra.year_request(gdp.TABLE, 2022, gdp.DOWNLOAD_VARIABLES)
    assert req.url.endswith("variaveis/37|543|498|513|517|6575|525?localidades=N6[all]")

