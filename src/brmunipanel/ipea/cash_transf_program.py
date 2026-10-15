"""Programa Bolsa Família (IPEA Data, OData4 API, series FAM_PBF and VAL_PBF).

Downloads annual December series at the municipal level and consolidates the 2006–2023 panel:
- FAM_PBF: number of benefits in December (Int64)
- VAL_PBF: total value of benefits in December in thousand R$ (Float64)

In 2013 and 2016 the source's municipal value is anomalous in part of the municipalities. It remains as received, without column flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from ..core import Request, InvalidResponse, download_batch, read_raw

BASE = "https://www.ipeadata.gov.br/api/odata4"
SERIES = ("FAM_PBF", "VAL_PBF")
PANEL_YEARS = tuple(range(2006, 2024))
EXPECTED_UNIT_VAL = "R$ (mil)"


def series_request(series: str) -> Request:
    return Request(
        key=series,
        url=f"{BASE}/ValoresSerie(SERCODIGO='{series}')",
        file=f"{series}.json.gz",
    )


def metadata_request(series: str) -> Request:
    return Request(
        key=f"{series}/metadata",
        url=f"{BASE}/Metadados('{series}')",
        file=f"{series}_metadata.json.gz",
    )


def validate_values(content: bytes) -> None:
    """Rejects responses that are not JSON with the 'value' key containing more than 100 thousand items."""
    try:
        data = json.loads(content)
    except ValueError as error:
        raise InvalidResponse(f"response is not JSON: {content[:80]!r}") from error
    if not isinstance(data, dict) or "value" not in data:
        raise InvalidResponse(f"response without the 'value' key: {content[:80]!r}")
    items = data["value"]
    if not isinstance(items, list) or len(items) <= 100_000:
        total = len(items) if isinstance(items, list) else type(items)
        raise InvalidResponse(f"response with {total} items (expected > 100,000)")


def validate_metadata(content: bytes) -> None:
    """Rejects metadata responses that do not contain exactly 1 item in the 'value' key."""
    try:
        data = json.loads(content)
    except ValueError as error:
        raise InvalidResponse(f"response is not JSON: {content[:80]!r}") from error
    if not isinstance(data, dict) or "value" not in data:
        raise InvalidResponse(f"response without the 'value' key: {content[:80]!r}")
    items = data["value"]
    if not isinstance(items, list) or len(items) != 1:
        total = len(items) if isinstance(items, list) else type(items)
        raise InvalidResponse(f"response with {total} items in metadata (expected exactly 1)")


def download(folder: Path, **options) -> list[dict]:
    """Downloads FAM_PBF and VAL_PBF series and their metadata to folder."""
    folder = Path(folder)
    reqs_meta = [metadata_request(s) for s in SERIES]
    reqs_values = [series_request(s) for s in SERIES]
    records_meta = download_batch(reqs_meta, folder, validate=validate_metadata, **options)
    records_values = download_batch(reqs_values, folder, validate=validate_values, **options)
    return records_meta + records_values


def _read_raw_series(folder: Path, series: str) -> tuple[pl.DataFrame, list[str]]:
    """Reads the raw series from the folder, filtering only 'Municípios' level and extracting municipality_code, year, and value."""
    content = read_raw(folder, f"{series}.json.gz")
    data = json.loads(content)
    items = data.get("value", [])

    rows: list[tuple[str, int, float | None]] = []
    invalid_codes: list[str] = []

    for it in items:
        if it.get("NIVNOME") == "Municípios":
            tercodigo = str(it.get("TERCODIGO") or "").strip()
            if len(tercodigo) != 7 or not tercodigo.isdigit():
                invalid_codes.append(tercodigo)
                continue
            valdata = str(it.get("VALDATA") or "")
            if len(valdata) < 4:
                continue
            year = int(valdata[:4])
            rows.append((tercodigo, year, it.get("VALVALOR")))

    df = pl.DataFrame(
        rows,
        schema={"municipality_code": pl.String, "year": pl.Int16, "value": pl.Float64},
        orient="row",
    )
    return df, invalid_codes


def check_unit(folder: Path) -> str:
    """Checks and returns the declared unit of measurement in VAL_PBF metadata."""
    path = Path(folder) / "VAL_PBF_metadata.json.gz"
    if not path.exists():
        return ""
    meta = json.loads(read_raw(folder, "VAL_PBF_metadata.json.gz"))
    items = meta.get("value", [])
    if items and isinstance(items, list):
        return items[0].get("UNINOME", "")
    return ""


def harmonize(folder: Path) -> pl.DataFrame:
    """Harmonizes FAM_PBF and VAL_PBF series for the 2006–2023 panel.

    Returns a pl.DataFrame sorted by municipality_code and year, with columns:
    - municipality_code (String, 7 digits)
    - year (Int16)
    - cash_transf_benefits (Int64, number of benefits in December)
    - cash_transf_value_thousand_brl (Float64, total value in thousand R$ in December)
    """
    folder = Path(folder)
    unit = check_unit(folder)
    if unit and unit != EXPECTED_UNIT_VAL:
        print(f"WARNING: VAL_PBF unit is {unit!r} (expected: {EXPECTED_UNIT_VAL!r})")

    df_fam, invalid_fam = _read_raw_series(folder, "FAM_PBF")
    df_val, invalid_val = _read_raw_series(folder, "VAL_PBF")

    invalid_total = invalid_fam + invalid_val
    if invalid_total:
        print(f"WARNING: {len(invalid_total)} municipality codes did not have 7 digits and were discarded: {set(invalid_total)}")

    df_fam = df_fam.select(
        "municipality_code",
        "year",
        pl.col("value").round().cast(pl.Int64).alias("cash_transf_benefits"),
    )
    df_val = df_val.select(
        "municipality_code",
        "year",
        pl.col("value").cast(pl.Float64).alias("cash_transf_value_thousand_brl"),
    )

    panel = df_fam.join(df_val, on=["municipality_code", "year"], how="full", coalesce=True)

    return (
        panel.filter(pl.col("year").is_in(PANEL_YEARS))
        .select([
            "municipality_code", "year", "cash_transf_benefits", "cash_transf_value_thousand_brl"
        ])
        .sort("municipality_code", "year")
    )
