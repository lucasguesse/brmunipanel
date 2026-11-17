"""Tests for School Census federal schools and network enrollment module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import zipfile

import polars as pl
import pytest

from brmunipanel.core import Request
from brmunipanel.inep import school_census
from brmunipanel.inep.school_census import (
    classify_federal_school,
    harmonize_network,
    normalize_school_name,
    read_network_year,
)


def test_normalize_school_name() -> None:
    assert normalize_school_name("Colégio de Aplicação - UFPE") == "COLEGIO DE APLICACAO UFPE"
    assert normalize_school_name("IFRO - CAMPUS COLORADO DO OESTE") == "IFRO CAMPUS COLORADO DO OESTE"


def test_classify_federal_school() -> None:
    cases = [
        (["COLÉGIO MILITAR DE BRASÍLIA"], "military"),
        (["COLÉGIO DE APLICAÇÃO DA UFPE"], "laboratory_school"),
        (["INSTITUTO FEDERAL DE EDUCAÇÃO, CIÊNCIA E TECNOLOGIA DO PARÁ - CAMPUS BELÉM"], "federal_network"),
        (["IFRO - CAMPUS COLORADO DO OESTE"], "federal_network"),
        (["ESCOLA DE MÚSICA DA UFRN"], "university_linked"),
        (["UNIVERSIDADE FEDERAL DE VIÇOSA - CAMPUS FLORESTAL"], "university_linked"),
        (["ESCOLA AGROPECUARIA R CEPLAC RO EMARC"], "other_federal"),
        (["IFPA - CAMPUS ABAETETUBA", "COLÉGIO MILITAR DE BELÉM"], "military"),
        (["ESCOLA AGROTÉCNICA FEDERAL DE COLORADO DO OESTE", "IFRO - CAMPUS COLORADO DO OESTE"], "federal_network"),
    ]
    for names, expected_type in cases:
        assert classify_federal_school(names) == expected_type

    with pytest.raises(ValueError):
        classify_federal_school([])


def test_read_network_year_latin1_and_quotes(tmp_path: Path) -> None:
    census_dir = tmp_path / "school-census"
    census_dir.mkdir(parents=True, exist_ok=True)
    zip_path = census_dir / "school-census_2020.zip"

    content = (
        "NU_ANO_CENSO;CO_MUNICIPIO;CO_ENTIDADE;NO_ENTIDADE;TP_DEPENDENCIA;TP_SITUACAO_FUNCIONAMENTO;QT_MAT_BAS;QT_MAT_MED;QT_MAT_FUND_AF;QT_MAT_PROF;QT_MAT_PROF_TEC;QT_MAT_EJA_MED\n"
        "2020;1100205;11000001;COLÉGIO DE APLICAÇÃO;1;1;300;120;90;0;0;0\n"
        '2020;1100205;11000002;"ESCOLA ESTADUAL RUA A; 10";2;1;500;200;300;0;0;10\n'
        "2020;1100205;11000003;ESCOLA PARALISADA;3;2;;;;;;\n"
    )

    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr(
            "microdados_ed_basica_2020/dados/microdados_ed_basica_2020.CSV",
            content.encode("latin-1"),
        )

    df = read_network_year(tmp_path, 2020, {"1100205"})
    assert df.height == 3
    assert df["school_code"].to_list() == ["11000001", "11000002", "11000003"]

    r1 = df.filter(pl.col("school_code") == "11000001").row(0, named=True)
    assert r1["school_name"] == "COLÉGIO DE APLICAÇÃO"
    assert r1["admin_dependency"] == "federal"
    assert r1["operating_status"] == "active"
    assert r1["enroll_secondary"] == 120
    assert r1["enroll_elementary_final_years"] == 90

    r2 = df.filter(pl.col("school_code") == "11000002").row(0, named=True)
    assert r2["school_name"] == "ESCOLA ESTADUAL RUA A; 10"
    assert r2["admin_dependency"] == "state"
    assert r2["enroll_eja_secondary"] == 10

    r3 = df.filter(pl.col("school_code") == "11000003").row(0, named=True)
    assert r3["operating_status"] == "paused"
    assert r3["enroll_secondary"] is None

    assert df["year"].dtype == pl.Int16
    for col in [
        "enroll_basic_edu",
        "enroll_secondary",
        "enroll_elementary_final_years",
        "enroll_vocational",
        "enroll_vocational_technical",
        "enroll_eja_secondary",
    ]:
        assert df[col].dtype == pl.Int64


def test_read_network_year_errors(tmp_path: Path) -> None:
    census_dir = tmp_path / "school-census"
    census_dir.mkdir(parents=True, exist_ok=True)
    zip_path = census_dir / "school-census_2020.zip"

    base_lines = [
        "NU_ANO_CENSO;CO_MUNICIPIO;CO_ENTIDADE;NO_ENTIDADE;TP_DEPENDENCIA;TP_SITUACAO_FUNCIONAMENTO;QT_MAT_BAS;QT_MAT_MED;QT_MAT_FUND_AF;QT_MAT_PROF;QT_MAT_PROF_TEC;QT_MAT_EJA_MED",
        "2020;1100205;11000001;COLÉGIO DE APLICAÇÃO;1;1;300;120;90;0;0;0",
        '2020;1100205;11000002;"ESCOLA ESTADUAL RUA A; 10";2;1;500;200;300;0;0;10',
        "2020;1100205;11000003;ESCOLA PARALISADA;3;2;;;;;;",
    ]

    def write_csv(lines: list[str]) -> None:
        content = "\n".join(lines) + "\n"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(
                "microdados_ed_basica_2020/dados/microdados_ed_basica_2020.CSV",
                content.encode("latin-1"),
            )

    # 1. TP_DEPENDENCIA == 5
    lines1 = list(base_lines)
    lines1[1] = "2020;1100205;11000001;COLÉGIO DE APLICAÇÃO;5;1;300;120;90;0;0;0"
    write_csv(lines1)
    with pytest.raises(ValueError, match="TP_DEPENDENCIA"):
        read_network_year(tmp_path, 2020, {"1100205"})

    # 2. TP_SITUACAO_FUNCIONAMENTO == 9
    lines2 = list(base_lines)
    lines2[1] = "2020;1100205;11000001;COLÉGIO DE APLICAÇÃO;1;9;300;120;90;0;0;0"
    write_csv(lines2)
    with pytest.raises(ValueError, match="TP_SITUACAO_FUNCIONAMENTO"):
        read_network_year(tmp_path, 2020, {"1100205"})

    # 3. valid_municipalities == {"3550308"}
    write_csv(base_lines)
    with pytest.raises(ValueError, match="CO_MUNICIPIO"):
        read_network_year(tmp_path, 2020, {"3550308"})

    # 4. header without QT_MAT_FUND_AF
    header_no_fund = (
        "NU_ANO_CENSO;CO_MUNICIPIO;CO_ENTIDADE;NO_ENTIDADE;TP_DEPENDENCIA;TP_SITUACAO_FUNCIONAMENTO;QT_MAT_BAS;QT_MAT_MED;QT_MAT_PROF;QT_MAT_PROF_TEC;QT_MAT_EJA_MED"
    )
    lines4 = [header_no_fund] + [
        "2020;1100205;11000001;COLÉGIO DE APLICAÇÃO;1;1;300;120;0;0;0",
        '2020;1100205;11000002;"ESCOLA ESTADUAL RUA A; 10";2;1;500;200;0;0;10',
        "2020;1100205;11000003;ESCOLA PARALISADA;3;2;;;;;",
    ]
    write_csv(lines4)
    with pytest.raises(ValueError, match="QT_MAT_FUND_AF"):
        read_network_year(tmp_path, 2020, {"1100205"})


def test_harmonize_network_samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census_dir = tmp_path / "school-census"
    census_dir.mkdir(parents=True, exist_ok=True)

    data_dir = Path(__file__).parent / "data"
    sample_2007 = (data_dir / "school_census_2007_sample.csv").read_bytes()
    sample_2023 = (data_dir / "school_census_2023_sample.csv").read_bytes()

    zip_2007 = census_dir / "school-census_2007.zip"
    with zipfile.ZipFile(zip_2007, "w") as z:
        z.writestr("microdados_ed_basica_2007.csv", sample_2007)

    zip_2023 = census_dir / "school-census_2023.zip"
    with zipfile.ZipFile(zip_2023, "w") as z:
        z.writestr("MICRODADOS_ED_BASICA_2023.CSV", sample_2023)

    monkeypatch.setattr(school_census, "NETWORK_YEARS", [2007, 2023])

    municipalities = pl.DataFrame({
        "municipality_code": ["1100015", "1100023", "1100114", "1100205", "1100064", "1100106", "1100700"]
    })

    federal, enrollment = harmonize_network(tmp_path, municipalities)

    assert federal.height == 2
    row0 = federal.row(0)
    assert row0 == (
        "11007877",
        2007,
        "1100023",
        "ESCOLA AGROPECUARIA R CEPLAC RO EMARC",
        "other_federal",
        "active",
        224,
        0,
        224,
        224,
        0,
    )

    row1 = federal.row(1)
    assert row1 == (
        "11037016",
        2023,
        "1100064",
        "IFRO - CAMPUS COLORADO DO OESTE",
        "federal_network",
        "active",
        579,
        579,
        579,
        579,
        0,
    )

    assert enrollment.height == 40

    r_other = enrollment.filter(
        (pl.col("municipality_code") == "1100023")
        & (pl.col("year") == 2007)
        & (pl.col("network") == "federal_other")
    ).select([
        "secondary_schools",
        "enroll_secondary",
        "enroll_elementary_final_years",
        "enroll_vocational_technical",
    ]).row(0)
    assert r_other == (0, 0, 0, 224)

    r_fed = enrollment.filter(
        (pl.col("municipality_code") == "1100064")
        & (pl.col("year") == 2023)
        & (pl.col("network") == "federal_network")
    ).select([
        "secondary_schools",
        "enroll_secondary",
        "enroll_elementary_final_years",
        "enroll_vocational_technical",
    ]).row(0)
    assert r_fed == (1, 579, 0, 579)

    r_priv = enrollment.filter(
        (pl.col("municipality_code") == "1100205")
        & (pl.col("year") == 2023)
        & (pl.col("network") == "private")
    ).select([
        "secondary_schools",
        "enroll_secondary",
        "enroll_elementary_final_years",
        "enroll_vocational_technical",
    ]).row(0)
    assert r_priv == (1, 354, 500, 0)

    r_mun = enrollment.filter(
        (pl.col("municipality_code") == "1100700")
        & (pl.col("year") == 2023)
        & (pl.col("network") == "municipal")
    ).select([
        "secondary_schools",
        "enroll_secondary",
        "enroll_elementary_final_years",
        "enroll_vocational_technical",
    ]).row(0)
    assert r_mun == (0, 0, 0, 0)

    sum_2023_secondary = enrollment.filter(pl.col("year") == 2023)["enroll_secondary"].sum()
    assert sum_2023_secondary == 933

    for col in [
        "secondary_schools",
        "enroll_secondary",
        "enroll_elementary_final_years",
        "enroll_vocational_technical",
    ]:
        assert enrollment[col].dtype == pl.Int64
        assert enrollment[col].null_count() == 0


def test_download_network_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_requests: list[Request] = []

    def mock_download_batch(reqs: list[Request], folder: Path | str, **options: Any) -> None:
        captured_requests.extend(reqs)

    monkeypatch.setattr(school_census, "download_batch", mock_download_batch)

    school_census.download_network("dummy")

    assert len(captured_requests) == 18
    for i, year in enumerate(range(2007, 2025)):
        req = captured_requests[i]
        assert req.key == f"school-census/{year}"
        assert req.file == f"school-census/school-census_{year}.zip"
        assert req.url == f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{year}.zip"
        assert req.compress is False
