"""Tests for INEP school performance rates module."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
import zipfile

import openpyxl
import polars as pl
import pytest

from brmunipanel.inep import pass_rates
from brmunipanel.inep.pass_rates import (
    column_positions,
    normalize_location,
    normalize_network,
    parse_code,
    parse_rate,
    parse_rows,
)


def test_parse_rate() -> None:
    assert parse_rate("77.9") == 77.9
    assert parse_rate("78,4") == 78.4
    assert parse_rate(8) == 8.0
    assert parse_rate(74.5) == 74.5

    assert parse_rate("--") is None
    assert parse_rate(" -- ") is None
    assert parse_rate("-") is None
    assert parse_rate("") is None
    assert parse_rate(None) is None

    with pytest.raises(ValueError):
        parse_rate("abc")
    with pytest.raises(ValueError):
        parse_rate(True)


def test_column_positions() -> None:
    expected_2007 = {
        "pass_rate_final_years": 17,
        "failure_rate_final_years": 35,
        "dropout_rate_final_years": 53,
        "pass_rate_secondary": 24,
        "failure_rate_secondary": 42,
        "dropout_rate_secondary": 60,
    }
    assert column_positions(2007) == expected_2007
    assert column_positions(2010) == expected_2007

    expected_2011 = {
        "pass_rate_final_years": 9,
        "failure_rate_final_years": 27,
        "dropout_rate_final_years": 45,
        "pass_rate_secondary": 19,
        "failure_rate_secondary": 37,
        "dropout_rate_secondary": 55,
    }
    assert column_positions(2011) == expected_2011
    assert column_positions(2025) == expected_2011

    with pytest.raises(ValueError):
        column_positions(2006)
    with pytest.raises(ValueError):
        column_positions(2026)


def test_normalize_network_and_location() -> None:
    assert normalize_network("Publico") == "public"
    assert normalize_network("Pública") == "public"
    assert normalize_network("Particular") == "private"
    assert normalize_network("Privada") == "private"
    assert normalize_network(" Estadual ") == "state"

    with pytest.raises(ValueError):
        normalize_network("Outra")

    assert normalize_location("Urbana") == "urban"
    assert normalize_location("Total") == "total"

    with pytest.raises(ValueError):
        normalize_location("Centro")


def test_parse_code() -> None:
    assert parse_code(1100015.0) == "1100015"
    assert parse_code(1100015) == "1100015"
    assert parse_code("1100015") == "1100015"

    assert parse_code(None) is None
    assert parse_code("Código do Município") is None
    assert parse_code(12345) is None
    assert parse_code(1100015.5) is None
    assert parse_code(True) is None


def test_parse_rows() -> None:
    # 2012 test case
    row_data_2012 = [None] * 56
    row_data_2012[3] = 1100015
    row_data_2012[5] = "Total"
    row_data_2012[6] = "Publico"
    row_data_2012[9] = 74.5
    row_data_2012[27] = 17.3
    row_data_2012[45] = 8.2
    row_data_2012[19] = "78,4"
    row_data_2012[37] = 8
    row_data_2012[55] = "--"

    header_row_1 = ["Taxas de Rendimento"]
    header_row_2 = [None] * 56
    header_row_2[3] = "Código do Município"
    footer_row = [None] * 56
    footer_row[3] = "Fonte: INEP"

    rows_2012 = [header_row_1, header_row_2, row_data_2012, footer_row]
    res_2012 = parse_rows(rows_2012, 2012)
    assert res_2012 == [
        {
            "municipality_code": "1100015",
            "year": 2012,
            "location": "total",
            "network": "public",
            "pass_rate_final_years": 74.5,
            "failure_rate_final_years": 17.3,
            "dropout_rate_final_years": 8.2,
            "pass_rate_secondary": 78.4,
            "failure_rate_secondary": 8.0,
            "dropout_rate_secondary": None,
        }
    ]

    # 2010 test case
    row_data_2010 = [None] * 61
    row_data_2010[3] = 1100015.0
    row_data_2010[5] = "Rural"
    row_data_2010[6] = "Municipal"
    row_data_2010[17] = 78.6
    row_data_2010[35] = 10.3
    row_data_2010[53] = 11.1
    row_data_2010[24] = "--"
    row_data_2010[42] = "--"
    row_data_2010[60] = "--"

    res_2010 = parse_rows([row_data_2010], 2010)
    assert len(res_2010) == 1
    d_2010 = res_2010[0]
    assert d_2010["location"] == "rural"
    assert d_2010["network"] == "municipal"
    assert d_2010["pass_rate_final_years"] == 78.6
    assert d_2010["failure_rate_final_years"] == 10.3
    assert d_2010["dropout_rate_final_years"] == 11.1
    assert d_2010["pass_rate_secondary"] is None
    assert d_2010["failure_rate_secondary"] is None
    assert d_2010["dropout_rate_secondary"] is None

    # Error case: short row with less than required cells
    short_row = [None] * 20
    short_row[3] = 1100015
    short_row[5] = "Total"
    short_row[6] = "Total"
    with pytest.raises(ValueError):
        parse_rows([short_row], 2012)


def test_harmonize_reads_xlsx_inside_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Region1"

    row_data_1 = [None] * 56
    row_data_1[3] = 1100015
    row_data_1[5] = "Total"
    row_data_1[6] = "Publico"
    row_data_1[9] = 74.5
    row_data_1[27] = 17.3
    row_data_1[45] = 8.2
    row_data_1[19] = "78,4"
    row_data_1[37] = 8
    row_data_1[55] = "--"
    ws1.append(["Taxas de Rendimento"])
    ws1.append(row_data_1)

    ws2 = wb.create_sheet(title="Region2")
    row_data_2 = [None] * 56
    row_data_2[3] = "1100015"
    row_data_2[5] = "Urbana"
    row_data_2[6] = "Estadual"
    row_data_2[9] = 70
    row_data_2[27] = 20
    row_data_2[45] = 10
    row_data_2[19] = "--"
    row_data_2[37] = "--"
    row_data_2[55] = "--"
    ws2.append(row_data_2)

    bio = io.BytesIO()
    wb.save(bio)
    wb_bytes = bio.getvalue()

    zip_path = tmp_path / "pass-rates_2012.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("tx_rendimento_municipios_2012/tx_rendimento_municipios_2012.xlsx", wb_bytes)
        z.writestr("tx_rendimento_municipios_2012/leia-me.txt", "readme")

    monkeypatch.setattr(pass_rates, "YEARS", (2012,))
    df = pass_rates.harmonize(tmp_path, pl.DataFrame({"municipality_code": ["1100015"]}))

    assert df.height == 2
    assert df.row(0) == ("1100015", 2012, "total", "public", 74.5, 17.3, 8.2, 78.4, 8.0, None)
    assert df.row(1) == ("1100015", 2012, "urban", "state", 70.0, 20.0, 10.0, None, None, None)
    assert df.schema["year"] == pl.Int16
    for rate_col in [
        "pass_rate_final_years",
        "failure_rate_final_years",
        "dropout_rate_final_years",
        "pass_rate_secondary",
        "failure_rate_secondary",
        "dropout_rate_secondary",
    ]:
        assert df.schema[rate_col] == pl.Float64

    # Invalid municipality code
    with pytest.raises(ValueError):
        pass_rates.harmonize(tmp_path, pl.DataFrame({"municipality_code": ["3550308"]}))

    # Two .xlsx inside zip
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("a.xlsx", wb_bytes)
        z.writestr("b.xlsx", wb_bytes)

    with pytest.raises(ValueError):
        pass_rates.harmonize(tmp_path, pl.DataFrame({"municipality_code": ["1100015"]}))


def test_download_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_reqs: list[Any] = []

    def mock_download_batch(reqs: list[Any], folder: Path, **options: Any) -> None:
        captured_reqs.extend(reqs)

    monkeypatch.setattr(pass_rates, "download_batch", mock_download_batch)
    pass_rates.download("dummy")

    assert len(captured_reqs) == 19
    for r in captured_reqs:
        ano = int(r.key.split("/")[1])
        assert r.key == f"pass-rates/{ano}"
        assert r.file == f"pass-rates_{ano}.zip"
        assert r.url == pass_rates.URLS[ano]
        assert r.method == "GET"
        assert r.compress is False

    assert pass_rates.URLS[2011].endswith("tx_rendimento_municipios_2011_2.zip")
    assert pass_rates.URLS[2016].endswith("TAXA_REND_2016_MUNICIPIOS.zip")
