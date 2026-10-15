"""Estimated resident population by municipality (SIDRA, Table 6579, variable 9324).

The table has no values for 2007, 2010, 2022, and 2023. These years are completed by geometric interpolation
(linear in logarithms) between neighboring estimates, and the source of each value is recorded in `population_source`.
The 2024 estimate is downloaded only to interpolate 2022 and 2023 and is not included in the panel.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import sidra

TABLE = 6579
VARIABLE = 9324
PANEL_YEARS = tuple(range(2006, 2024))
YEARS_WITHOUT_ESTIMATE = (2007, 2010, 2022, 2023)
DOWNLOAD_YEARS = tuple(year for year in range(2006, 2025) if year not in YEARS_WITHOUT_ESTIMATE)


def download(sidra_folder: Path, **options) -> list[dict]:
    return sidra.download_table(TABLE, DOWNLOAD_YEARS, [VARIABLE], sidra_folder, **options)


def interpolate(estimates: pl.DataFrame, years: tuple[int, ...] = YEARS_WITHOUT_ESTIMATE) -> pl.DataFrame:
    """Interpolates `population` for the requested years, between the closest previous and next estimates.

    A municipality receives an interpolated value only when it has estimates in both neighboring years.
    """
    with_estimate = sorted(estimates["year"].unique().to_list())
    parts = []
    for year in years:
        before = max(a for a in with_estimate if a < year)
        after = min(a for a in with_estimate if a > year)
        weight = (year - before) / (after - before)
        start = estimates.filter(pl.col("year") == before).select("municipality_code", pl.col("population").alias("p0"))
        end = estimates.filter(pl.col("year") == after).select("municipality_code", pl.col("population").alias("p1"))
        log_pop = pl.col("p0").log() + weight * (pl.col("p1").log() - pl.col("p0").log())
        parts.append(
            start.join(end, on="municipality_code", how="inner")
            .filter((pl.col("p0") > 0) & (pl.col("p1") > 0))
            .select(
                "municipality_code",
                pl.lit(year, dtype=pl.Int16).alias("year"),
                log_pop.exp().round().cast(pl.Int64).alias("population"),
            )
        )
    return pl.concat(parts)


def harmonize(sidra_folder: Path) -> pl.DataFrame:
    """Panel 2006–2023: `municipality_code`, `year`, `population`, and `population_source` (`estimate` or `interpolated`)."""
    long = sidra.read_table(sidra_folder, TABLE, DOWNLOAD_YEARS)
    estimates, _ = sidra.to_panel(long, {VARIABLE: ("population", pl.Int64)})
    estimates = estimates.drop_nulls("population")
    panel = pl.concat(
        [
            estimates.with_columns(pl.lit("estimate").alias("population_source")),
            interpolate(estimates).with_columns(pl.lit("interpolated").alias("population_source")),
        ]
    )
    return panel.filter(pl.col("year").is_in(PANEL_YEARS)).sort("municipality_code", "year")
