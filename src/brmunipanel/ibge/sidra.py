"""IBGE aggregates API client (SIDRA), shared across municipal tables.

One call per table and year, with all municipalities (`N6[all]`): each national query takes about
one minute, and requests above roughly 50 thousand values fail (HTTP 500), so more than one year is never joined.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import polars as pl

from ..core import Request, InvalidResponse, download_batch, read_raw

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# SIDRA markers instead of value: absolute zero, unavailable, not applicable, and confidentiality.
ABSOLUTE_ZERO = "-"
NO_VALUE_MARKERS = ("...", "..", "X")


def year_request(table: int, year: int, variables: Sequence[int]) -> Request:
    ids = "|".join(str(v) for v in variables)
    return Request(
        key=f"t{table}/{year}",
        url=f"{BASE}/{table}/periodos/{year}/variaveis/{ids}?localidades=N6[all]",
        file=f"t{table}/t{table}_{year}.json.gz",
    )


def metadata_request(table: int) -> Request:
    return Request(
        key=f"t{table}/metadata",
        url=f"{BASE}/{table}/metadados",
        file=f"t{table}/t{table}_metadata.json.gz",
    )


def validate_values(content: bytes, min_municipalities: int = 5000) -> None:
    """Rejects responses that do not bring the list of variables with municipal series."""
    try:
        blocks = json.loads(content)
    except ValueError as error:
        raise InvalidResponse(f"response is not JSON: {content[:80]!r}") from error
    if not isinstance(blocks, list) or not blocks:
        raise InvalidResponse(f"response without variables: {content[:80]!r}")
    for block in blocks:
        series = block["resultados"][0]["series"]
        if len(series) < min_municipalities:
            raise InvalidResponse(f"variable {block['id']} with {len(series)} municipalities")


def download_table(table: int, years: Sequence[int], variables: Sequence[int], folder: Path, **options) -> list[dict]:
    """Downloads table metadata and one response per year into `folder` (the SIDRA folder)."""
    metadata = download_batch([metadata_request(table)], folder, **options)
    reqs = [year_request(table, year, variables) for year in years]
    return metadata + download_batch(reqs, folder, validate=validate_values, **options)


def read_table(folder: Path, table: int, years: Sequence[int]) -> pl.DataFrame:
    """Reads raw data from a table in long format: municipality, year, variable, and the value as received (text)."""
    rows = []
    for year in years:
        blocks = json.loads(read_raw(folder, year_request(table, year, ()).file))
        for block in blocks:
            variable = int(block["id"])
            for series in block["resultados"][0]["series"]:
                municipality = series["localidade"]["id"]
                for period, value in series["serie"].items():
                    rows.append((municipality, int(period), variable, value))
    return pl.DataFrame(
        rows,
        schema={"municipality_code": pl.String, "year": pl.Int16, "variable": pl.Int32, "raw_value": pl.String},
        orient="row",
    )


def to_panel(long: pl.DataFrame, columns: Mapping[int, tuple[str, pl.DataType]]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Converts long format into a panel (one row per municipality and year) and separates markers.

    `columns` associates each variable ID with the column name and type. Absolute zero (`-`) becomes 0;
    unavailable (`...`), not applicable (`..`), and confidentiality (`X`) become null in the panel and are returned in the
    second table, one row per cell, so that the reason for the null is not lost.
    """
    names = pl.DataFrame(
        {"variable": list(columns), "column": [name for name, _ in columns.values()]},
        schema={"variable": pl.Int32, "column": pl.String},
    )
    long = long.join(names, on="variable", how="inner")
    without_value = pl.col("raw_value").is_in(NO_VALUE_MARKERS)
    markers = (
        long.filter(without_value)
        .select("municipality_code", "year", "column", pl.col("raw_value").alias("marker"))
        .sort("municipality_code", "year", "column")
    )
    numeric = (
        pl.when(without_value)
        .then(None)
        .when(pl.col("raw_value") == ABSOLUTE_ZERO)
        .then(pl.lit("0"))
        .otherwise(pl.col("raw_value"))
        .cast(pl.Float64)
    )
    panel = (
        long.with_columns(numeric.alias("value"))
        .pivot(on="column", index=["municipality_code", "year"], values="value")
        .select("municipality_code", "year", *[pl.col(name).cast(kind) for name, kind in columns.values()])
        .sort("municipality_code", "year")
    )
    return panel, markers
