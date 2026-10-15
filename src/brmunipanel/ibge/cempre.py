"""Cadastro Central de Empresas (CEMPRE), local units concept, totals by municipality.

Table 1685 in 2006–2021 and Table 9509 in 2022–2023. The panel maintains five harmonized variables.
Three variables remain only in the raw data: active enterprises, average monthly salary in minimum wages, and
average monthly salary in reais (calculated as wages_thousand_brl * 1000 / salaried_employees_avg / 13).
The source table for each period is 1685 until 2021, and 9509 in 2022 and 2023. IBGE reports a series
break in 2022 (Nota técnica 01/2024), which the dataset does not treat or mark in a column. A null value means
a municipality that did not yet exist or a value omitted by IBGE due to confidentiality.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import sidra

YEARS_BY_TABLE = {1685: tuple(range(2006, 2022)), 9509: (2022, 2023)}
DOWNLOAD_VARIABLES = [706, 367, 707, 708, 5944, 662, 1606, 10143]
COLUMNS = {
    706: ("establishments_number", pl.Int64),
    707: ("employed_total", pl.Int64),
    708: ("employed_salaried", pl.Int64),
    5944: ("salaried_employees_avg", pl.Float64),
    662: ("wages_thousand_brl", pl.Float64),
}


def download(sidra_folder: Path, **options) -> list[dict]:
    """Downloads CEMPRE tables (1685 for 2006–2021 and 9509 for 2022–2023) into `sidra_folder`.

    Returns the list of manifest records for metadata and annual responses.
    """
    records = []
    for table, years in YEARS_BY_TABLE.items():
        records += sidra.download_table(table, years, DOWNLOAD_VARIABLES, sidra_folder, **options)
    return records


def harmonize(sidra_folder: Path) -> pl.DataFrame:
    """Panel sorted by municipality_code and year, with the five selected variables."""
    panels = []
    for table, years in YEARS_BY_TABLE.items():
        panel, _ = sidra.to_panel(sidra.read_table(sidra_folder, table, years), COLUMNS)
        panels.append(panel)
    return pl.concat(panels).sort("municipality_code", "year")
