"""Harmonization of health tabulations from TabNet (DATASUS) at the municipal level.

Generates the municipal health panel (2006–2023) by consolidating nine indicators:
- CNES: inpatient beds, ICU beds, diagnostic imaging
  equipment (entire group), physicians, primary care units, and health posts;
- SIM: deaths from assault (ICD-10 X85–Y09) and infant deaths;
- Sinasc: live births.

SUS beds (general hospitalization subset), COVID-19
ICU beds (2020-2022 only), and the CBO version returned alongside physicians
(which repeats the year) are not included in the panel. COVID-19 beds are not added to
ICU beds. Physician counts switch classification between 2007 (CBO 1994)
and 2008 (CBO 2002).
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from .. import core
from . import tabnet

PANEL_YEARS: tuple[int, ...] = tuple(range(2006, 2024))

PANEL_COLUMNS: tuple[str, ...] = (
    "municipality_code",
    "year",
    "inpatient_beds",
    "icu_beds",
    "imaging_equipment",
    "physicians",
    "primary_care_units",
    "health_posts",
    "assault_deaths",
    "infant_deaths",
    "live_births",
)


def _convert_value(value: str) -> int:
    """Converts TabNet value string to integer (dash '-' becomes 0)."""
    v = value.strip()
    if not v or v == "-":
        return 0
    return int(v)


def _process_tabulation_rows(
    rows: list[list[str]],
    column_indices: dict[str, list[int]],
    mapping_6_to_7: dict[str, str],
) -> dict[str, dict[str, int]]:
    """Extracts and aggregates values by 7-digit municipality from the rows of a tabulation."""
    values_by_muni: dict[str, dict[str, int]] = {}

    for row in rows:
        label = row[0].strip()
        if label.lower() == "total":
            continue

        m = re.match(r"^(\d{6})(?:\s+(.*))?$", label)
        if not m:
            # Discard row without a 6-digit code at the beginning (e.g. 'MUNICIPIO IGNORADO - RJ')
            continue

        code6 = m.group(1)
        # Any code starting with 53 is summed into 530010 (Brasília / DF)
        if code6.startswith("53"):
            code6 = "530010"

        code7 = mapping_6_to_7.get(code6)
        if not code7:
            # TabNet code without a match in DTB is discarded
            continue

        if code7 not in values_by_muni:
            values_by_muni[code7] = {field: 0 for field in column_indices}

        for field, idxs in column_indices.items():
            sum_field = sum(_convert_value(row[idx]) for idx in idxs)
            values_by_muni[code7][field] += sum_field

    return values_by_muni


def _extract_inpatient_beds(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"cnes_inpatient_beds/cnes_inpatient_beds_{year:04d}07.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    for required in ("Quantidade existente",):
        if required not in header:
            raise ValueError(f"Required column '{required}' missing in cnes_inpatient_beds/{year:04d}07")

    indices = {
        "inpatient_beds": [header.index("Quantidade existente")],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_complementary_beds(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"cnes_complementary_beds/cnes_complementary_beds_{year:04d}07.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    idxs_uti = [i for i, c in enumerate(header) if c.startswith("UTI") and "COVID" not in c]

    indices = {
        "icu_beds": idxs_uti,
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_equipment(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"cnes_equipment_group/cnes_equipment_group_{year:04d}07.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    required = "Equipamentos de Diagnostico por Imagem"
    if required not in header:
        raise ValueError(f"Required column '{required}' missing in cnes_equipment_group/{year:04d}07")

    indices = {
        "imaging_equipment": [header.index(required)],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_physicians(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    if year in (2006, 2007):
        tab_name = "cnes_physicians_cbo1994"
    else:
        tab_name = "cnes_physicians_cbo2002"

    file = f"{tab_name}/{tab_name}_{year:04d}07.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    if "Total" not in header:
        raise ValueError(f"Required column 'Total' missing in {tab_name}/{year:04d}07")

    indices = {
        "physicians": [header.index("Total")],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_facilities(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"cnes_facilities/cnes_facilities_{year:04d}07.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    for required in ("CENTRO DE SAUDE/UNIDADE BASICA", "POSTO DE SAUDE"):
        if required not in header:
            raise ValueError(f"Required column '{required}' missing in cnes_facilities/{year:04d}07")

    indices = {
        "primary_care_units": [header.index("CENTRO DE SAUDE/UNIDADE BASICA")],
        "health_posts": [header.index("POSTO DE SAUDE")],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_assault_deaths(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"sim_assault_deaths/sim_assault_deaths_{year:04d}.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    if "Óbitos p/Residênc" not in header:
        raise ValueError(f"Required column 'Óbitos p/Residênc' missing in sim_assault_deaths/{year:04d}")

    indices = {
        "assault_deaths": [header.index("Óbitos p/Residênc")],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_infant_deaths(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"sim_infant_deaths/sim_infant_deaths_{year:04d}.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    if "Óbitos p/Residênc" not in header:
        raise ValueError(f"Required column 'Óbitos p/Residênc' missing in sim_infant_deaths/{year:04d}")

    indices = {
        "infant_deaths": [header.index("Óbitos p/Residênc")],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def _extract_live_births(tabnet_folder: Path, year: int, mapping_6_to_7: dict[str, str]) -> dict[str, dict[str, int]]:
    file = f"sinasc_live_births/sinasc_live_births_{year:04d}.html.gz"
    content = core.read_raw(tabnet_folder, file)
    header, rows = tabnet.extract_table(content)

    if "Nascim p/resid.mãe" not in header:
        raise ValueError(f"Required column 'Nascim p/resid.mãe' missing in sinasc_live_births/{year:04d}")

    indices = {
        "live_births": [header.index("Nascim p/resid.mãe")],
    }
    return _process_tabulation_rows(rows, indices, mapping_6_to_7)


def harmonize(
    tabnet_folder: Path,
    municipalities: pl.DataFrame,
    population: pl.DataFrame,
    *,
    years: tuple[int, ...] = PANEL_YEARS,
) -> pl.DataFrame:
    """Harmonizes TabNet tabulations for the municipal panel.

    Args:
        tabnet_folder: Directory containing raw files downloaded from TabNet.
        municipalities: DTB municipalities DataFrame with `municipality_code` and `municipality_code_6`.
        population: Population DataFrame with `municipality_code`, `year`, and `population`.
        years: Tuple of years to process (default: 2006 to 2023).

    Returns:
        Polars DataFrame with 1 row per municipality and year, sorted by `municipality_code` and `year`.
    """
    tabnet_folder = Path(tabnet_folder)
    mapping_6_to_7 = dict(zip(municipalities["municipality_code_6"].to_list(), municipalities["municipality_code"].to_list()))
    all_municipalities = sorted(municipalities["municipality_code"].unique().to_list())

    # Pairs (municipality_code, year) that have a valid population record
    pairs_with_population = set(
        zip(
            population.filter(pl.col("population").is_not_null())["municipality_code"].to_list(),
            population.filter(pl.col("population").is_not_null())["year"].to_list(),
        )
    )

    rows_panel: list[dict] = []

    for year in sorted(years):
        data_beds = _extract_inpatient_beds(tabnet_folder, year, mapping_6_to_7)
        complementary_data = _extract_complementary_beds(tabnet_folder, year, mapping_6_to_7)
        data_equipment = _extract_equipment(tabnet_folder, year, mapping_6_to_7)
        data_physicians = _extract_physicians(tabnet_folder, year, mapping_6_to_7)
        data_facilities = _extract_facilities(tabnet_folder, year, mapping_6_to_7)
        data_assault = _extract_assault_deaths(tabnet_folder, year, mapping_6_to_7)
        infant_data = _extract_infant_deaths(tabnet_folder, year, mapping_6_to_7)
        data_born = _extract_live_births(tabnet_folder, year, mapping_6_to_7)

        for code7 in all_municipalities:
            has_population = (code7, year) in pairs_with_population

            if not has_population:
                # Years in which the municipality has no population remain null in all columns
                rows_panel.append({
                    "municipality_code": code7,
                    "year": year,
                    "inpatient_beds": None,
                    "icu_beds": None,
                    "imaging_equipment": None,
                    "physicians": None,
                    "primary_care_units": None,
                    "health_posts": None,
                    "assault_deaths": None,
                    "infant_deaths": None,
                    "live_births": None,
                })
            else:
                # Municipality absent from the response receives zero
                m_law = data_beds.get(code7, {})
                m_comp = complementary_data.get(code7, {})
                m_equ = data_equipment.get(code7, {})
                m_med = data_physicians.get(code7, {})
                m_est = data_facilities.get(code7, {})
                m_agr = data_assault.get(code7, {})
                m_inf = infant_data.get(code7, {})
                m_nv = data_born.get(code7, {})

                rows_panel.append({
                    "municipality_code": code7,
                    "year": year,
                    "inpatient_beds": m_law.get("inpatient_beds", 0),
                    "icu_beds": m_comp.get("icu_beds", 0),
                    "imaging_equipment": m_equ.get("imaging_equipment", 0),
                    "physicians": m_med.get("physicians", 0),
                    "primary_care_units": m_est.get("primary_care_units", 0),
                    "health_posts": m_est.get("health_posts", 0),
                    "assault_deaths": m_agr.get("assault_deaths", 0),
                    "infant_deaths": m_inf.get("infant_deaths", 0),
                    "live_births": m_nv.get("live_births", 0),
                })

    return pl.DataFrame(
        rows_panel,
        schema_overrides={
            "municipality_code": pl.String,
            "year": pl.Int16,
            "inpatient_beds": pl.Int64,
            "icu_beds": pl.Int64,
            "imaging_equipment": pl.Int64,
            "physicians": pl.Int64,
            "primary_care_units": pl.Int64,
            "health_posts": pl.Int64,
            "assault_deaths": pl.Int64,
            "infant_deaths": pl.Int64,
            "live_births": pl.Int64,
        },
    ).sort("municipality_code", "year")
