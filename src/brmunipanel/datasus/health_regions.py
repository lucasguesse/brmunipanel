"""Health regions and macroregions by municipality (API de Dados Abertos of Ministério da Saúde).

Endpoint: https://apidadosabertos.saude.gov.br/macrorregiao-e-regiao-de-saude/municipio
Municipality codes arrive with 6 digits and are converted to the 7 digits of DTB.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import polars as pl
import requests

from .. import core
from ..core import Request, InvalidResponse

BASE_URL = "https://apidadosabertos.saude.gov.br/macrorregiao-e-regiao-de-saude/municipio"
RESPONSE_KEY = "macrorregiao_regiao_saude_municipios"
PAGE_LIMIT = 1000


def validate(content: bytes) -> None:
    """Validates whether the content is a JSON with the expected format from the health regions API."""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            raise InvalidResponse("The response is not a JSON object")
        items = data.get(RESPONSE_KEY)
        if not isinstance(items, list):
            raise InvalidResponse(f"Key '{RESPONSE_KEY}' is missing or is not a list")
    except (json.JSONDecodeError, InvalidResponse) as error:
        raise InvalidResponse(f"Invalid content from the health regions API: {error}") from error


def download(folder: Path, **options) -> list[dict]:
    """Downloads all pages from the health regions API, advancing the offset by the total number of items received."""
    folder = Path(folder)
    offset = 0
    records = []
    session = options.pop("session", None) or requests.Session()
    interval = options.pop("interval", 1.0)

    while True:
        key = f"offset{offset:04d}"
        file = f"health_regions_offset{offset:04d}.json.gz"
        url = f"{BASE_URL}?limit={PAGE_LIMIT}&offset={offset}"
        req = Request(key=key, url=url, file=file, compress=True)

        record, downloaded = core.download(req, folder, session=session, validate=validate, **options)
        records.append(record)
        if downloaded and interval:
            time.sleep(interval)

        content = core.read_raw(folder, req.file)
        data = json.loads(content)
        items = data.get(RESPONSE_KEY, [])
        if not items:
            break
        offset += len(items)

    return records


def process_items(
    items: list[dict[str, Any]],
    municipalities: pl.DataFrame,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Converts API items into a harmonized table using `municipality_code_6` from `municipalities`.

    Returns the harmonized DataFrame and the list of items discarded due to lack of match in DTB.
    Raises ValueError if there are repeated municipality codes among the received items.
    """
    seen: set[str] = set()
    repeated: set[str] = set()
    for item in items:
        code_6 = str(item.get("codigo_municipio", "")).strip()
        if not code_6:
            continue
        if code_6 in seen:
            repeated.add(code_6)
        seen.add(code_6)

    if repeated:
        raise ValueError(
            f"API pagination returned repeated municipality codes ({len(repeated)}): {sorted(repeated)}"
        )

    crosswalk = dict(zip(municipalities["municipality_code_6"].to_list(), municipalities["municipality_code"].to_list()))

    rows = []
    discarded = []
    for item in items:
        code_6 = str(item.get("codigo_municipio", "")).strip()
        code_7 = crosswalk.get(code_6)
        if code_7 is None:
            discarded.append(item)
            continue

        rows.append({
            "municipality_code": code_7,
            "health_region_code": str(item.get("codigo_regiao_saude", "")).strip(),
            "health_region_name": str(item.get("regiao_saude", "")).strip(),
            "health_macroregion_code": str(item.get("codigo_macrorregiao_saude", "")).strip(),
            "health_macroregion_name": str(item.get("macrorregiao_saude", "")).strip(),
        })

    if not rows:
        df = pl.DataFrame(
            schema={
                "municipality_code": pl.String,
                "health_region_code": pl.String,
                "health_region_name": pl.String,
                "health_macroregion_code": pl.String,
                "health_macroregion_name": pl.String,
            }
        )
    else:
        df = pl.DataFrame(rows, schema_overrides={
            "municipality_code": pl.String,
            "health_region_code": pl.String,
            "health_region_name": pl.String,
            "health_macroregion_code": pl.String,
            "health_macroregion_name": pl.String,
        }).sort("municipality_code")

    return df, discarded


def harmonize(folder: Path, municipalities: pl.DataFrame) -> pl.DataFrame:
    """Reads files downloaded in `folder`, extracts all records, and harmonizes against `municipalities`."""
    folder = Path(folder)
    manifest = core.read_manifest(folder)

    files: list[str] = []
    if manifest:
        for key in sorted(manifest.keys()):
            files.append(manifest[key]["file"])
    else:
        files = sorted(p.name for p in folder.glob("health_regions_offset*.json.gz"))

    all_items: list[dict[str, Any]] = []
    for file in files:
        content = core.read_raw(folder, file)
        data = json.loads(content)
        all_items.extend(data.get(RESPONSE_KEY, []))

    df, discarded = process_items(all_items, municipalities)
    if discarded:
        print(f"Warning: {len(discarded)} API records without a match in the DTB were discarded")
    return df
