"""Tests for the shared SIDRA client (brmunipanel.ibge.sidra)."""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ibge import sidra
from brmunipanel.core import InvalidResponse

FOLDER_DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture
def sample_5938_2022_bytes() -> bytes:
    path = FOLDER_DATA / "sidra_t5938_2022_sample.json"
    return path.read_bytes()


@pytest.fixture
def sample_1685_2012_bytes() -> bytes:
    path = FOLDER_DATA / "sidra_t1685_2012_sample.json"
    return path.read_bytes()


def test_validate_values(sample_5938_2022_bytes: bytes) -> None:
    # 1. Accepts valid real response (with min_municipalities matching the sample)
    sidra.validate_values(sample_5938_2022_bytes, min_municipalities=4)

    # 2. Rejects invalid JSON
    with pytest.raises(InvalidResponse, match="response is not JSON"):
        sidra.validate_values(b"<html>Erro no servidor</html>")

    # 3. Rejects empty list
    with pytest.raises(InvalidResponse, match="response without variables"):
        sidra.validate_values(b"[]")

    # 4. Rejects response with fewer municipalities than the configured minimum
    with pytest.raises(InvalidResponse, match="with 4 municipalities"):
        sidra.validate_values(sample_5938_2022_bytes, min_municipalities=100)


def test_read_table(tmp_path: Path, sample_5938_2022_bytes: bytes) -> None:
    folder_table = tmp_path / "t5938"
    folder_table.mkdir(parents=True, exist_ok=True)
    (folder_table / "t5938_2022.json.gz").write_bytes(gzip.compress(sample_5938_2022_bytes, mtime=0))

    df_long = sidra.read_table(tmp_path, 5938, [2022])

    assert df_long.schema == {
        "municipality_code": pl.String,
        "year": pl.Int16,
        "variable": pl.Int32,
        "raw_value": pl.String,
    }
    assert df_long.height == 7 * 4  # 7 variables x 4 municipalities
    assert df_long["year"].unique().to_list() == [2022]
    assert df_long["raw_value"].dtype == pl.String


def test_to_panel_converts_markers_and_dash(
    tmp_path: Path, sample_1685_2012_bytes: bytes, sample_5938_2022_bytes: bytes
) -> None:
    # Sets up tables in tmp_path
    (tmp_path / "t1685").mkdir(parents=True, exist_ok=True)
    (tmp_path / "t1685" / "t1685_2012.json.gz").write_bytes(gzip.compress(sample_1685_2012_bytes, mtime=0))

    df_long_cempre = sidra.read_table(tmp_path, 1685, [2012])
    columns_cempre_test = {
        706: ("establishments_number", pl.Int64),
        367: ("empresas_atuantes", pl.Int64),
        707: ("employed_total", pl.Int64),
        708: ("employed_salaried", pl.Int64),
        5944: ("salaried_employees_avg", pl.Float64),
        662: ("wages_thousand_brl", pl.Float64),
        1606: ("avg_monthly_wage_mw", pl.Float64),
        10143: ("avg_monthly_wage_brl", pl.Float64),
    }
    panel_cempre, markers_cempre = sidra.to_panel(df_long_cempre, columns_cempre_test)

    # 1. 4220000 has '-' in employed_salaried (var 708) -> must become 0
    row_4220000 = panel_cempre.filter(pl.col("municipality_code") == "4220000")
    assert row_4220000["employed_salaried"].item() == 0

    # 2. 4220000 has 'X' in salaried_employees_avg (var 5944) -> must be null in panel
    assert row_4220000["salaried_employees_avg"].item() is None

    # 3. Markers store 'X' in markers table
    marks_4220000 = markers_cempre.filter(pl.col("municipality_code") == "4220000")
    assert "X" in marks_4220000["marker"].to_list()
    # '-' must NOT be in markers (because it is numeric zero)
    assert "-" not in markers_cempre["marker"].to_list()

    # 4. In table 5938 from 2022, impostos_liquidos and VAB are '...'
    (tmp_path / "t5938").mkdir(parents=True, exist_ok=True)
    (tmp_path / "t5938" / "t5938_2022.json.gz").write_bytes(gzip.compress(sample_5938_2022_bytes, mtime=0))
    df_long_gdp = sidra.read_table(tmp_path, 5938, [2022])
    columns_gdp_test = {
        37: ("gdp", pl.Float64),
        543: ("impostos_liquidos", pl.Float64),
        498: ("vab_total", pl.Float64),
        513: ("vab_agropecuaria", pl.Float64),
        517: ("vab_industria", pl.Float64),
        6575: ("vab_servicos", pl.Float64),
        525: ("vab_adm_publica", pl.Float64),
    }
    panel_gdp, markers_gdp = sidra.to_panel(df_long_gdp, columns_gdp_test)

    # GDP has a numeric value
    assert panel_gdp["gdp"].null_count() == 0
    # Impostos and VAB are null
    assert panel_gdp["impostos_liquidos"].null_count() == 4
    assert panel_gdp["vab_total"].null_count() == 4
    # Marker '...' present in the GDP markers
    assert all(m == "..." for m in markers_gdp["marker"].to_list())
    assert markers_gdp.height == 6 * 4  # 6 columns without value x 4 municipalities

    # 5. Explicit synthetic test for '..'
    df_colon = pl.DataFrame(
        {
            "municipality_code": ["1100015"],
            "year": [2020],
            "variable": [37],
            "raw_value": [".."],
        },
        schema={"municipality_code": pl.String, "year": pl.Int16, "variable": pl.Int32, "raw_value": pl.String},
    )
    p_dp, m_dp = sidra.to_panel(df_colon, {37: ("gdp", pl.Float64)})
    assert p_dp["gdp"].item() is None
    assert m_dp["marker"].to_list() == [".."]
