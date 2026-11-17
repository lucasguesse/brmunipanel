"""School performance rates (pass, failure, and dropout) from INEP.

Source: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (INEP)
Source unit: municipality
Key: municipality_code, year, location, network

Caveats:
- Rates are published as-is, with null where the file displays '--'.
- The spreadsheets do not separate integrated vocational education from regular secondary education.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable, Sequence
import zipfile

import openpyxl
import polars as pl
import xlrd

from brmunipanel.core import InvalidResponse, Request, download_batch
from brmunipanel.inep.connection import create_session

YEARS: tuple[int, ...] = tuple(range(2007, 2026))

URLS: dict[int, str] = {
    2007: "https://download.inep.gov.br/informacoes_estatisticas/2011/indicadores_educacionais/taxa_rendimento/2007/tx_rendimento_municipios_2007.zip",
    2008: "https://download.inep.gov.br/informacoes_estatisticas/2011/indicadores_educacionais/taxa_rendimento/2008/tx_rendimento_municipios_2008.zip",
    2009: "https://download.inep.gov.br/informacoes_estatisticas/2011/indicadores_educacionais/taxa_rendimento/2009/tx_rendimento_municipios_2009.zip",
    2010: "https://download.inep.gov.br/informacoes_estatisticas/2011/indicadores_educacionais/taxa_rendimento/2010/tx_rendimento_municipios_2010.zip",
    2011: "https://download.inep.gov.br/informacoes_estatisticas/2011/indicadores_educacionais/taxa_rendimento/2011/tx_rendimento_municipios_2011_2.zip",
    2012: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2012/taxas_rendimento/tx_rendimento_municipios_2012.zip",
    2013: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2013/taxa_rendimento/tx_rendimento_municipios_2013.zip",
    2014: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2014/taxa_rendimento/tx_rendimento_municipios_2014.zip",
    2015: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2015/taxa_rendimento/tx_rendimento_municipios_2015.zip",
    2016: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2016/TAXA_REND_2016_MUNICIPIOS.zip",
    2017: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2017/TAXA_REND_2017_MUNICIPIOS.zip",
    2018: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2018/TX_REND_MUNICIPIOS_2018.zip",
    2019: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2019/tx_rend_municipios_2019.zip",
    2020: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2020/tx_rend_municipios_2020.zip",
    2021: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2021/tx_rend_municipios_2021.zip",
    2022: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2022/tx_rend_municipios_2022.zip",
    2023: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2023/tx_rend_municipios_2023.zip",
    2024: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2024/tx_rend_municipios_2024.zip",
    2025: "https://download.inep.gov.br/informacoes_estatisticas/indicadores_educacionais/2025/tx_rend_municipios_2025.zip",
}


def validate_zip(content: bytes) -> None:
    """Raises InvalidResponse if content does not start with standard ZIP magic bytes."""
    if not content.startswith(b"PK\x03\x04"):
        raise InvalidResponse("The content is not a valid ZIP file")


def download(folder: Path | str, **options) -> None:
    """Downloads pass rate zip packages from INEP for all configured years."""
    folder = Path(folder)
    reqs = [
        Request(
            key=f"pass-rates/{year}",
            url=URLS[year],
            file=f"pass-rates_{year}.zip",
            method="GET",
            compress=False,
        )
        for year in YEARS
    ]
    session = options.pop("session", None) or create_session()
    download_batch(reqs, folder, session=session, validate=validate_zip, interval=1.0, **options)


def parse_rate(value: object) -> float | None:
    """Parses a performance rate percentage value."""
    if isinstance(value, bool):
        raise ValueError(f"Invalid rate value (boolean): {value}")
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned in ("", "-", "--"):
            return None
        cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError as err:
            raise ValueError(f"Invalid rate string: {value}") from err
    raise ValueError(f"Invalid rate type: {value}")


def column_positions(year: int) -> dict[str, int]:
    """Returns zero-based column positions for rate metrics for a given year."""
    if year not in YEARS:
        raise ValueError(f"Year {year} is outside configured YEARS ({YEARS[0]}-{YEARS[-1]})")
    if 2007 <= year <= 2010:
        return {
            "pass_rate_final_years": 17,
            "failure_rate_final_years": 35,
            "dropout_rate_final_years": 53,
            "pass_rate_secondary": 24,
            "failure_rate_secondary": 42,
            "dropout_rate_secondary": 60,
        }
    return {
        "pass_rate_final_years": 9,
        "failure_rate_final_years": 27,
        "dropout_rate_final_years": 45,
        "pass_rate_secondary": 19,
        "failure_rate_secondary": 37,
        "dropout_rate_secondary": 55,
    }


def normalize_network(name: str) -> str:
    """Normalizes the administrative school network name."""
    cleaned = name.strip()
    if cleaned == "Total":
        return "total"
    if cleaned == "Estadual":
        return "state"
    if cleaned == "Federal":
        return "federal"
    if cleaned == "Municipal":
        return "municipal"
    if cleaned in ("Particular", "Privada"):
        return "private"
    if cleaned in ("Publico", "Público", "Publica", "Pública"):
        return "public"
    raise ValueError(f"Unknown school network: {name}")


def normalize_location(name: str) -> str:
    """Normalizes the school location category."""
    cleaned = name.strip()
    if cleaned == "Total":
        return "total"
    if cleaned == "Urbana":
        return "urban"
    if cleaned == "Rural":
        return "rural"
    raise ValueError(f"Unknown location: {name}")


def parse_code(value: object) -> str | None:
    """Parses a 7-digit IBGE municipality code, returning None for non-code cells."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        if 1000000 <= value <= 9999999:
            return str(value)
        return None
    if isinstance(value, float):
        if value.is_integer() and 1000000 <= int(value) <= 9999999:
            return str(int(value))
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.isdigit() and len(cleaned) == 7 and 1000000 <= int(cleaned) <= 9999999:
            return cleaned
        try:
            f = float(cleaned)
            if f.is_integer() and 1000000 <= int(f) <= 9999999:
                return str(int(f))
        except ValueError:
            pass
        return None
    return None


def parse_rows(rows: Iterable[Sequence[object]], year: int) -> list[dict[str, object]]:
    """Parses spreadsheet rows into structured record dictionaries."""
    pos = column_positions(year)
    max_pos = max(pos.values())

    records: list[dict[str, object]] = []
    for row in rows:
        if len(row) <= 6:
            continue
        code = parse_code(row[3])
        if code is None:
            continue
        if len(row) < max_pos + 1:
            raise ValueError(
                f"Row for municipality {code} in year {year} has {len(row)} cells, "
                f"expected at least {max_pos + 1}"
            )
        location = normalize_location(str(row[5]))
        network = normalize_network(str(row[6]))
        record: dict[str, object] = {
            "municipality_code": code,
            "year": year,
            "location": location,
            "network": network,
        }
        for col_name, idx in pos.items():
            record[col_name] = parse_rate(row[idx])
        records.append(record)
    return records


def read_year(folder: Path | str, year: int, valid_municipalities: set[str]) -> pl.DataFrame:
    """Reads pass rates for a single year from the downloaded ZIP archive."""
    zip_path = Path(folder) / f"pass-rates_{year}.zip"
    with zipfile.ZipFile(zip_path) as z:
        candidates = [
            m for m in z.namelist()
            if (m.lower().endswith(".xls") or m.lower().endswith(".xlsx"))
            and not Path(m).name.startswith("~")
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"Expected exactly 1 spreadsheet in {zip_path.name}, found {len(candidates)}: {candidates}"
            )
        target_member = candidates[0]
        content = z.read(target_member)

    rows: list[Sequence[object]] = []
    if target_member.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    rows.append(row)
        finally:
            wb.close()
    else:
        book = xlrd.open_workbook(file_contents=content)
        for sheet in book.sheets():
            for r in range(sheet.nrows):
                rows.append(sheet.row_values(r))

    records = parse_rows(rows, year)
    if not records:
        raise ValueError(f"No data rows found in {zip_path.name}")

    invalid_codes = sorted({r["municipality_code"] for r in records if r["municipality_code"] not in valid_municipalities})
    if invalid_codes:
        examples = ", ".join(invalid_codes[:3])
        raise ValueError(
            f"Found {len(invalid_codes)} invalid municipality codes in {zip_path.name} (e.g., {examples})"
        )

    schema = {
        "municipality_code": pl.String,
        "year": pl.Int16,
        "location": pl.String,
        "network": pl.String,
        "pass_rate_final_years": pl.Float64,
        "failure_rate_final_years": pl.Float64,
        "dropout_rate_final_years": pl.Float64,
        "pass_rate_secondary": pl.Float64,
        "failure_rate_secondary": pl.Float64,
        "dropout_rate_secondary": pl.Float64,
    }
    return pl.DataFrame(records, schema=schema)


def harmonize(folder: Path | str, municipalities: pl.DataFrame) -> pl.DataFrame:
    """Harmonizes pass, failure, and dropout rates across all configured years."""
    folder = Path(folder)
    valid_municipalities = set(municipalities["municipality_code"].to_list())

    dfs = [read_year(folder, y, valid_municipalities) for y in YEARS]
    if not dfs:
        raise ValueError("No data found for any year")

    df_all = pl.concat(dfs)

    duplicates = (
        df_all.group_by(["municipality_code", "year", "location", "network"])
        .len()
        .filter(pl.col("len") > 1)
    )
    if duplicates.height > 0:
        raise ValueError(
            f"Duplicate keys found in pass rates panel: {duplicates.height} duplicates"
        )

    columns = [
        "municipality_code",
        "year",
        "location",
        "network",
        "pass_rate_final_years",
        "failure_rate_final_years",
        "dropout_rate_final_years",
        "pass_rate_secondary",
        "failure_rate_secondary",
        "dropout_rate_secondary",
    ]
    return df_all.select(columns).sort(["municipality_code", "year", "location", "network"])
