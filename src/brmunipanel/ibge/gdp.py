"""Produto Interno Bruto dos Municípios (SIDRA, Table 5938, 2010 reference), in current thousand reais.

Only GDP is harmonized, because the source does not publish gross value added or taxes for 2022 and 2023. The table does not generate markers.
The municipality has null gdp in the years prior to its installation. The raw data continues to bring
the seven variables of the table.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import sidra

TABLE = 5938
YEARS = tuple(range(2006, 2024))
DOWNLOAD_VARIABLES = [37, 543, 498, 513, 517, 6575, 525]
COLUMNS = {
    37: ("gdp", pl.Float64),
}


def download(sidra_folder: Path, **options) -> list[dict]:
    return sidra.download_table(TABLE, YEARS, DOWNLOAD_VARIABLES, sidra_folder, **options)


def harmonize(sidra_folder: Path) -> pl.DataFrame:
    """Panel 2006–2023 (one row per municipality and year)."""
    panel, _ = sidra.to_panel(sidra.read_table(sidra_folder, TABLE, YEARS), COLUMNS)
    return panel
