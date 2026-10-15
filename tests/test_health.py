"""Tests for harmonization of health tabulations from TabNet (DATASUS)."""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.datasus import health


def _create_html(header: list[str], rows: list[list[str]]) -> bytes:
    """Builds TabNet HTML inside <PRE> with semicolon separator in latin-1 compressed in gzip."""
    text_rows = [";".join(f'"{c}"' for c in header)]
    for r in rows:
        text_rows.append(";".join(f'"{c}"' for c in r))
    html = f"<PRE>\n{chr(10).join(text_rows)}\n</PRE>"
    return gzip.compress(html.encode("latin-1"))


def _write_html(folder: Path, subfolder: str, name_file: str, header: list[str], rows: list[list[str]]) -> None:
    target = folder / subfolder / name_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_create_html(header, rows))


def _build_default_structure(folder: Path, year: int) -> None:
    """Create a minimal and valid structure for all tabulations of the year."""
    p_cnes = f"{year:04d}07"
    p_sim = str(year)

    # 1. Inpatient beds
    _write_html(
        folder,
        "cnes_inpatient_beds",
        f"cnes_inpatient_beds_{p_cnes}.html.gz",
        ["Município", "Quantidade existente"],
        [
            ["110001 ALTA FLORESTA", "70"],
            ["Total", "70"],
        ],
    )

    # 2. Complementary beds (ICU)
    _write_html(
        folder,
        "cnes_complementary_beds",
        f"cnes_complementary_beds_{p_cnes}.html.gz",
        ["Município", "UTI adulto II", "UTI neonatal", "Unidade intermediária", "UTI adulto II COVID-19", "Total"],
        [
            ["110001 ALTA FLORESTA", "10", "5", "8", "4", "27"],
            ["Total", "10", "5", "8", "4", "27"],
        ],
    )

    # 3. Physicians (CBO 1994 for <=2007, CBO 2002 for >=2008)
    tab_med = "cnes_physicians_cbo1994" if year <= 2007 else "cnes_physicians_cbo2002"
    _write_html(
        folder,
        tab_med,
        f"{tab_med}_{p_cnes}.html.gz",
        ["Município", "Clinico", "Pediatra", "Total"],
        [
            ["110001 ALTA FLORESTA", "10", "6", "16"],
            ["Total", "10", "6", "16"],
        ],
    )

    # 4. Establishments
    _write_html(
        folder,
        "cnes_facilities",
        f"cnes_facilities_{p_cnes}.html.gz",
        ["Município", "CENTRO DE SAUDE/UNIDADE BASICA", "POSTO DE SAUDE", "Total"],
        [
            ["110001 ALTA FLORESTA", "3", "2", "5"],
            ["Total", "3", "2", "5"],
        ],
    )

    # 4.5 Equipment (Testing different column order)
    _write_html(
        folder,
        "cnes_equipment_group",
        f"cnes_equipment_group_{p_cnes}.html.gz",
        ["Município", "Equipamentos de Infra-Estrutura", "Equipamentos de Diagnostico por Imagem", "Outros Equipamentos", "Total"],
        [
            ["110001 ALTA FLORESTA", "1", "10", "4", "15"],
            ["Total", "1", "10", "4", "15"],
        ],
    )

    # 5. Deaths from assault
    _write_html(
        folder,
        "sim_assault_deaths",
        f"sim_assault_deaths_{p_sim}.html.gz",
        ["Município", "Óbitos p/Residênc"],
        [
            ["110001 ALTA FLORESTA", "6"],
            ["Total", "6"],
        ],
    )

    # 6. Infant deaths
    _write_html(
        folder,
        "sim_infant_deaths",
        f"sim_infant_deaths_{p_sim}.html.gz",
        ["Município", "Óbitos p/Residênc"],
        [
            ["110001 ALTA FLORESTA", "8"],
            ["Total", "8"],
        ],
    )

    # 7. Live births
    _write_html(
        folder,
        "sinasc_live_births",
        f"sinasc_live_births_{p_sim}.html.gz",
        ["Município", "Nascim p/resid.mãe"],
        [
            ["110001 ALTA FLORESTA", "476"],
            ["Total", "476"],
        ],
    )


@pytest.fixture
def df_municipalities() -> pl.DataFrame:
    """Minimal table of DTB municipalities."""
    return pl.DataFrame({
        "municipality_code": ["1100015", "1100023", "5300108"],
        "municipality_code_6": ["110001", "110002", "530010"],
    })


@pytest.fixture
def df_population() -> pl.DataFrame:
    """Population table with mock Nazária/absent."""
    return pl.DataFrame({
        "municipality_code": ["1100015", "1100015", "1100023", "5300108", "5300108"],
        "year": [2007, 2008, 2007, 2007, 2008],
        "population": [25000, 24000, 80000, 2500000, 2600000],
    }, schema_overrides={"year": pl.Int16, "population": pl.Int64})


def test_health_harmonization_rules(tmp_path: Path, df_municipalities: pl.DataFrame, df_population: pl.DataFrame):
    """Test: ignored municipality discarded, '-' becomes 0, ICU aggregates and excludes COVID/intermed,

    53xxxx summed into Brasília, absent receives 0, without population becomes null, and correct CBO version.
    """
    year = 2007
    p_cnes = f"{year:04d}07"

    _build_default_structure(tmp_path, year)

    # Overwrite complementares to test:
    # - ICU sum includes UTI adulto II and UTI neonatal
    # - excludes Unidade intermediária
    # - separates UTI adulto II COVID-19
    # - dash '-' becomes zero
    # - ignored municipality row is discarded
    # - 53xxxx codes summed into Brasília (530010)
    _write_html(
        tmp_path,
        "cnes_complementary_beds",
        f"cnes_complementary_beds_{p_cnes}.html.gz",
        ["Município", "UTI adulto II", "UTI neonatal", "Unidade intermediária", "UTI adulto II COVID-19", "Total"],
        [
            ["110001 ALTA FLORESTA", "2", "3", "5", "4", "14"],
            ["530010 BRASILIA", "10", "-", "2", "-", "12"],
            ["539999 REGIAO ADM DF", "5", "2", "1", "1", "9"],  # Another 53 code
            ["MUNICIPIO IGNORADO - RO", "99", "99", "99", "99", "396"],  # Ignored
            ["Total", "116", "104", "107", "104", "431"],
        ],
    )

    panel = health.harmonize(tmp_path, df_municipalities, df_population, years=(2007,))

    assert panel.shape == (3, 11)
    assert panel.columns == list(health.PANEL_COLUMNS)

    # 1. Municipality 1100015 (Alta Floresta):
    m11 = panel.filter(pl.col("municipality_code") == "1100015").to_dicts()[0]
    assert m11["icu_beds"] == 5  # 2 + 3 (excluded 5 intermediate and 4 COVID)
    assert m11["inpatient_beds"] == 70
    assert m11["imaging_equipment"] == 10

    # 2. Municipality 5300108 (Brasília):
    # Sum of 530010 (10 + 0 ICU) with 539999 (5 + 2 ICU)
    m53 = panel.filter(pl.col("municipality_code") == "5300108").to_dicts()[0]
    assert m53["icu_beds"] == 17  # 10 + 0 + 5 + 2
    # In tabulations where Brasília did not appear in the response, received 0
    assert m53["inpatient_beds"] == 0
    assert m53["assault_deaths"] == 0

    # 3. Municipality 1100023 in 2007 has population, but did not appear in any tabulation -> receives 0
    m1102 = panel.filter(pl.col("municipality_code") == "1100023").to_dicts()[0]
    assert m1102["inpatient_beds"] == 0
    assert m1102["icu_beds"] == 0
    assert m1102["imaging_equipment"] == 0
    assert m1102["physicians"] == 0
    
    # 4. Assertion of removed columns
    assert "inpatient_beds_sus" not in panel.columns
    assert "icu_beds_covid19" not in panel.columns
    assert "physicians_cbo" not in panel.columns


def test_municipality_without_population_stays_null(tmp_path: Path, df_municipalities: pl.DataFrame, df_population: pl.DataFrame):
    """Municipality and year without population record has all columns null."""
    year = 2008
    _build_default_structure(tmp_path, year)

    panel = health.harmonize(tmp_path, df_municipalities, df_population, years=(2008,))

    # Municipality 1100023 does NOT have population in 2008 in df_population
    m1102 = panel.filter(pl.col("municipality_code") == "1100023").to_dicts()[0]
    assert m1102["year"] == 2008
    assert m1102["inpatient_beds"] is None
    assert m1102["icu_beds"] is None
    assert m1102["imaging_equipment"] is None
    assert m1102["physicians"] is None
    assert m1102["primary_care_units"] is None
    assert m1102["health_posts"] is None
    assert m1102["assault_deaths"] is None
    assert m1102["infant_deaths"] is None
    assert m1102["live_births"] is None


def test_physicians_different_tabulations_by_year(tmp_path: Path, df_municipalities: pl.DataFrame, df_population: pl.DataFrame):
    """Test that physicians uses cbo1994 tabulation in 2007 and cbo2002 in 2008."""
    _build_default_structure(tmp_path, 2007)
    _build_default_structure(tmp_path, 2008)

    # Overwrite physicians in 2008 with a different value
    _write_html(
        tmp_path,
        "cnes_physicians_cbo2002",
        "cnes_physicians_cbo2002_200807.html.gz",
        ["Município", "Clinico", "Pediatra", "Total"],
        [
            ["110001 ALTA FLORESTA", "10", "6", "25"],
            ["Total", "10", "6", "25"],
        ],
    )

    panel = health.harmonize(tmp_path, df_municipalities, df_population, years=(2007, 2008))

    p2007 = panel.filter((pl.col("municipality_code") == "1100015") & (pl.col("year") == 2007)).to_dicts()[0]
    p2008 = panel.filter((pl.col("municipality_code") == "1100015") & (pl.col("year") == 2008)).to_dicts()[0]

    assert p2007["physicians"] == 16
    assert p2008["physicians"] == 25


def test_required_column_missing_raises_error(tmp_path: Path, df_municipalities: pl.DataFrame, df_population: pl.DataFrame):
    """Absence of required column ('Quantidade existente', 'POSTO DE SAUDE', etc.) raises ValueError."""
    _build_default_structure(tmp_path, 2007)

    # Corrupt cnes_inpatient_beds removing 'Quantidade existente'
    _write_html(
        tmp_path,
        "cnes_inpatient_beds",
        "cnes_inpatient_beds_200707.html.gz",
        ["Município", "Outra coluna"],
        [["110001 ALTA FLORESTA", "70"]],
    )

    with pytest.raises(ValueError, match="Required column 'Quantidade existente' missing"):
        health.harmonize(tmp_path, df_municipalities, df_population, years=(2007,))


def test_required_column_missing_equipment_raises_error(tmp_path: Path, df_municipalities: pl.DataFrame, df_population: pl.DataFrame):
    """Absence of required equipment column raises ValueError."""
    _build_default_structure(tmp_path, 2007)

    # Corrupt cnes_equipment_group removing required column
    _write_html(
        tmp_path,
        "cnes_equipment_group",
        "cnes_equipment_group_200707.html.gz",
        ["Município", "Equipamentos de Infra-Estrutura"],
        [["110001 ALTA FLORESTA", "1"]],
    )

    with pytest.raises(ValueError, match="Required column 'Equipamentos de Diagnostico por Imagem' missing"):
        health.harmonize(tmp_path, df_municipalities, df_population, years=(2007,))
