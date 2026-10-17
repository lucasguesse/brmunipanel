import gzip
import json

import polars as pl
import pytest

from brmunipanel import core
from brmunipanel.tesouro import revenue, siconfi, siconfi_revenue


def item(code, column, value):
    return {"cod_conta": code, "coluna": column, "valor": value}


def test_codings_and_columns_by_year():
    assert [siconfi_revenue.coding(y) for y in (2013, 2017, 2018, 2021, 2022, 2023)] == [
        "2013-2017", "2013-2017", "2018-2021", "2018-2021", "2022-2023", "2022-2023",
    ]
    assert siconfi_revenue.gross_column(2013) == "Receitas Realizadas"
    assert siconfi_revenue.gross_column(2014) == "Receitas Brutas Realizadas"
    assert siconfi_revenue.deduction_columns(2013) == ("Deduções da Receita",)
    assert siconfi_revenue.deduction_columns(2023) == (
        "Deduções - FUNDEB", "Deduções - Transferências Constitucionais", "Outras Deduções da Receita",
    )
    for accounts in siconfi_revenue.ACCOUNTS.values():
        assert sorted(accounts) == sorted(c for c in revenue.REVENUE_COLUMNS if c != "rev_current_deductions")


def test_statement_2013():
    items = [
        item("RO1.0.0.0.00.00.00", "Receitas Realizadas", 1000.0),
        item("RO1.0.0.0.00.00.00", "Deduções da Receita", 150.0),
        item("RO1.1.1.2.02.00.00", "Receitas Realizadas", 40.0),
        item("RO1.1.1.3.05.00.00", "Receitas Realizadas", 60.0),
        item("RO1.1.1.2.08.00.00", "Receitas Realizadas", 7.0),
        item("RO1.1.2.0.00.00.00", "Receitas Realizadas", 3.0),
        item("RO1.7.2.1.01.02.00", "Receitas Realizadas", 500.0),
        item("RO1.7.2.1.01.02.00", "Deduções da Receita", 100.0),
        item("RO1.7.2.2.01.01.00", "Receitas Realizadas", 250.0),
        item("RO1.9.3.1.00.00.00", "Receitas Realizadas", 9.0),
        item("RI7.0.0.0.00.00.00", "Receitas Realizadas", 80.0),
    ]
    ret, warnings = siconfi_revenue.process_revenue_statement(items, 2013)
    assert ret == {
        "rev_current_gross": 1000.0,
        "rev_current_deductions": 150.0,
        "rev_iptu": 40.0,
        "rev_iss": 60.0,
        "rev_itbi": 7.0,
        "rev_fees": 3.0,
        "rev_fpm": 500.0,
        "rev_icms_share": 250.0,
    }
    assert warnings == []


def test_statement_2015_sums_fpm_and_deduction_columns():
    gross = "Receitas Brutas Realizadas"
    items = [
        item("RO1.0.0.0.00.00.00", gross, 2000.0),
        item("RO1.0.0.0.00.00.00", "Deduções - FUNDEB", 200.0),
        item("RO1.0.0.0.00.00.00", "Deduções - Transferências Constitucionais", 30.0),
        item("RO1.0.0.0.00.00.00", "Outras Deduções da Receita", 5.0),
        item("RO1.7.2.1.01.02.00", gross, 800.0),
        item("RO1.7.2.1.01.03.00", gross, 8.0),
        item("RO1.7.2.1.01.04.00", gross, 4.0),
    ]
    ret, warnings = siconfi_revenue.process_revenue_statement(items, 2015)
    assert ret["rev_current_gross"] == 2000.0
    assert ret["rev_current_deductions"] == 235.0
    assert ret["rev_fpm"] == 812.0
    assert ret["rev_iptu"] == 0.0
    assert ret["rev_icms_share"] == 0.0
    assert warnings == []


def test_statement_2019_coding_and_unknown_column():
    gross = "Receitas Brutas Realizadas"
    items = [
        item("RO1.0.0.0.00.0.0", gross, 3000.0),
        item("RO1.0.0.0.00.0.0", "Deduções - FUNDEB", -300.0),
        item("RO1.1.1.8.01.1.0", gross, 90.0),
        item("RO1.1.1.8.02.3.0", gross, 110.0),
        item("RO1.1.1.8.01.4.0", gross, 20.0),
        item("RO1.1.2.0.00.0.0", gross, 15.0),
        item("RO1.7.1.8.01.0.0", gross, 1300.0),
        item("RO1.7.1.8.01.2.0", gross, 1200.0),
        item("RO1.7.1.8.01.3.0", gross, 12.0),
        item("RO1.7.1.8.01.4.0", gross, 11.0),
        item("RO1.7.1.8.01.5.0", gross, 77.0),
        item("RO1.7.2.8.01.1.0", gross, 600.0),
        item("RO1.1.1.8.01.1.0", "Coluna Nova", 1.0),
    ]
    ret, warnings = siconfi_revenue.process_revenue_statement(items, 2019)
    assert ret == {
        "rev_current_gross": 3000.0,
        "rev_current_deductions": -300.0,
        "rev_iptu": 90.0,
        "rev_iss": 110.0,
        "rev_itbi": 20.0,
        "rev_fees": 15.0,
        "rev_fpm": 1223.0,
        "rev_icms_share": 600.0,
    }
    assert warnings == ["unknown_column:Coluna Nova"]


def test_statement_2023_reads_fpm_parent_only():
    gross = "Receitas Brutas Realizadas"
    items = [
        item("RO1.0.0.0.00.0.0", gross, 5000.0),
        item("RO1.1.1.2.50.0.0", gross, 300.0),
        item("RO1.1.1.4.51.1.0", gross, 400.0),
        item("RO1.1.1.2.53.0.0", gross, 50.0),
        item("RO1.1.2.0.00.0.0", gross, 25.0),
        item("RO1.7.1.1.51.0.0", gross, 1900.0),
        item("RO1.7.1.1.51.1.0", gross, 1750.0),
        item("RO1.7.1.1.51.2.0", gross, 150.0),
        item("RO1.7.2.1.50.0.0", gross, 900.0),
    ]
    ret, warnings = siconfi_revenue.process_revenue_statement(items, 2023)
    assert ret["rev_fpm"] == 1900.0
    assert ret["rev_iptu"] == 300.0
    assert ret["rev_iss"] == 400.0
    assert ret["rev_itbi"] == 50.0
    assert ret["rev_fees"] == 25.0
    assert ret["rev_icms_share"] == 900.0
    assert ret["rev_current_deductions"] == 0.0
    assert warnings == []


def test_statement_missing_total_mixed_signs_nulls_and_duplicates():
    gross = "Receitas Brutas Realizadas"
    items = [
        item("RO1.1.1.2.02.00.00", gross, 12.0),
        item("RO1.7.2.2.01.01.00", gross, None),
    ]
    ret, warnings = siconfi_revenue.process_revenue_statement(items, 2014)
    assert ret["rev_current_gross"] is None
    assert ret["rev_iptu"] == 12.0
    assert ret["rev_icms_share"] == 0.0
    assert warnings == ["null_value:RO1.7.2.2.01.01.00", "no_current_revenue"]

    items = [
        item("RO1.0.0.0.00.0.0", gross, 100.0),
        item("RO1.0.0.0.00.0.0", "Deduções - FUNDEB", 20.0),
        item("RO1.0.0.0.00.0.0", "Outras Deduções da Receita", -5.0),
    ]
    ret, warnings = siconfi_revenue.process_revenue_statement(items, 2020)
    assert ret["rev_current_deductions"] == 15.0
    assert warnings == ["mixed_deduction_signs"]

    with pytest.raises(ValueError, match="Two rows for account"):
        siconfi_revenue.process_revenue_statement([item("RO1.0.0.0.00.0.0", gross, 1.0)] * 2, 2020)


def test_harmonize(tmp_path):
    def line(year, code, items):
        return json.dumps({"key": f"{year}/{code}", "url": "u", "http": 200, "body": json.dumps({"items": items, "hasMore": False})})

    data = {
        2013: [
            line(2013, "3550308", [item("RO1.0.0.0.00.00.00", "Receitas Realizadas", 10.0), item("RO1.7.2.1.01.02.00", "Receitas Realizadas", 4.0)]),
            line(2013, "1100015", []),
            line(2013, "5300108", [item("RO1.0.0.0.00.00.00", "Receitas Realizadas", 99.0)]),
            line(2013, "9999999", [item("RO1.0.0.0.00.00.00", "Receitas Realizadas", 99.0)]),
        ],
        2022: [
            line(2022, "1100015", [item("RO1.0.0.0.00.0.0", "Receitas Brutas Realizadas", 30.0), item("RO1.7.1.1.51.0.0", "Receitas Brutas Realizadas", 6.0)]),
            line(2022, "3550308", [item("RO1.0.0.0.00.0.0", "Receitas Brutas Realizadas", 20.0)]),
        ],
    }
    for year in siconfi.YEARS:
        file = siconfi.api_file(year, "I-C")
        text = "\n".join(data.get(year, [])) + "\n"
        (tmp_path / file).write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
        core.record_file(tmp_path, siconfi.api_manifest_key(year, "I-C"), file, url="u", method="GET", parameters={})
    municipalities = pl.DataFrame({"municipality_code": ["3550308", "1100015"]})
    report = []

    df = siconfi_revenue.harmonize(tmp_path, municipalities, report)

    assert df.schema == revenue.SCHEMA
    assert df.select(["municipality_code", "year"]).rows() == [("1100015", 2022), ("3550308", 2013), ("3550308", 2022)]
    assert df["rev_current_gross"].to_list() == [30.0, 10.0, 20.0]
    assert df["rev_fpm"].to_list() == [6.0, 4.0, 0.0]
    assert sorted((r["municipality_code"], r["year"], r["type"]) for r in report) == [
        ("1100015", 2013, "no_declaration"),
        ("5300108", 2013, "distrito_federal"),
        ("9999999", 2013, "outside_dtb"),
    ]


def test_harmonize_requires_every_year_in_the_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="dca_i_c_2013"):
        siconfi_revenue.harmonize(tmp_path, pl.DataFrame({"municipality_code": ["3550308"]}))
