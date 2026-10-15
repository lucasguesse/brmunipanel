"""TabNet (DATASUS) client for extracting municipal health tabulations via POST.

Endpoint: http://tabnet.datasus.gov.br/cgi/tabcgi.exe?<definicao>.def
Queries generate files in PRN format (semicolon-separated CSV inside <PRE> tags).
"""

from __future__ import annotations

import csv
import html
import io
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from .. import core
from ..core import Request, InvalidResponse


@dataclass(frozen=True)
class Tabulation:
    """Configuration for a TabNet tabulation."""

    name: str
    definition: str
    column: str
    increments: tuple[str, ...]
    prefix: str
    periods: tuple[str, ...]
    filters: dict[str, str] = field(default_factory=dict)


TABULATIONS: tuple[Tabulation, ...] = (
    Tabulation(
        name="cnes_inpatient_beds",
        definition="cnes/cnv/leiintbr",
        column="--Não-Ativa--",
        increments=("Quantidade_existente", "Quantidade_SUS"),
        prefix="ltbr",
        periods=tuple(f"{year:04d}07" for year in range(2006, 2024)),
    ),
    Tabulation(
        name="cnes_complementary_beds",
        definition="cnes/cnv/leiutibr",
        column="Leitos_complementares",
        increments=("Quantidade_existente",),
        prefix="lubr",
        periods=tuple(f"{year:04d}07" for year in range(2006, 2024)),
    ),
    Tabulation(
        name="cnes_facilities",
        definition="cnes/cnv/estabbr",
        column="Tipo_de_Estabelecimento",
        increments=("Quantidade",),
        prefix="stbr",
        periods=tuple(f"{year:04d}07" for year in range(2006, 2024)),
    ),
    Tabulation(
        name="cnes_equipment_group",
        definition="cnes/cnv/equipobr",
        column="Grupo_de_Equipamentos",
        increments=("Equipamentos_Existentes",),
        prefix="eqbr",
        periods=tuple(f"{year:04d}07" for year in range(2006, 2024)),
    ),
    Tabulation(
        name="cnes_physicians_cbo1994",
        definition="cnes/cnv/profidbr",
        column="Médicos",
        increments=("Quantidade",),
        prefix="pfbr",
        periods=("200607", "200707"),
    ),
    Tabulation(
        name="cnes_physicians_cbo2002",
        definition="cnes/cnv/prid02br",
        column="Médicos",
        increments=("Quantidade",),
        prefix="pfbr",
        periods=("200708",) + tuple(f"{year:04d}07" for year in range(2008, 2024)),
    ),
    Tabulation(
        name="sim_assault_deaths",
        definition="sim/cnv/obt10br",
        column="--Não-Ativa--",
        increments=("Óbitos_p/Residênc",),
        prefix="obtbr",
        periods=tuple(str(year) for year in range(2006, 2024)),
        filters={"SGrupo_CID-10": "246"},
    ),
    Tabulation(
        name="sim_infant_deaths",
        definition="sim/cnv/inf10br",
        column="--Não-Ativa--",
        increments=("Óbitos_p/Residênc",),
        prefix="infbr",
        periods=tuple(str(year) for year in range(2006, 2024)),
    ),
    Tabulation(
        name="sinasc_live_births",
        definition="sinasc/cnv/nvbr",
        column="--Não-Ativa--",
        increments=("Nascim_p/resid.mãe",),
        prefix="nvbr",
        periods=tuple(str(year) for year in range(2006, 2024)),
    ),
)


def _encode(text: str) -> str:
    """Encodes URL parameter in Latin-1 for compatibility with the TabNet server."""
    return urllib.parse.quote(str(text), safe="", encoding="latin-1")


def dbf_name(tabulation: Tabulation, period: str | int) -> str:
    """Returns the name of the .dbf file on the server for the tabulation and period."""
    p = str(period).strip()
    if len(p) == 4 and tabulation.definition.startswith("cnes/"):
        p = f"{p}07"
    if len(p) == 6:
        # YYYYMM format (e.g. 200607 -> 0607, 200708 -> 0708)
        return f"{tabulation.prefix}{p[2:4]}{p[4:6]}.dbf"
    # YYYY format (e.g. 2006 -> 06, 2023 -> 23)
    return f"{tabulation.prefix}{p[2:4]}.dbf"


def build_body(tabulation: Tabulation, period: str | int) -> str:
    """Builds the Latin-1 encoded POST form string in the order required by TabNet."""
    parts = [
        f"{_encode('Linha')}={_encode('Município')}",
        f"{_encode('Coluna')}={_encode(tabulation.column)}",
    ]
    for inc in tabulation.increments:
        parts.append(f"{_encode('Incremento')}={_encode(inc)}")

    parts.append(f"{_encode('Arquivos')}={_encode(dbf_name(tabulation, period))}")

    for key, value in tabulation.filters.items():
        parts.append(f"{_encode(key)}={_encode(value)}")

    parts.append(f"{_encode('formato')}={_encode('prn')}")
    parts.append(f"{_encode('mostre')}={_encode('Mostra')}")

    return "&".join(parts)


def request(tabulation: Tabulation, period: str | int) -> Request:
    """Creates the Request object for the tabulation and period."""
    period_str = str(period).strip()
    key = f"{tabulation.name}/{period_str}"
    url = f"http://tabnet.datasus.gov.br/cgi/tabcgi.exe?{tabulation.definition}.def"
    file = f"{tabulation.name}/{tabulation.name}_{period_str}.html.gz"
    body = build_body(tabulation, period_str)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return Request(
        key=key,
        url=url,
        file=file,
        method="POST",
        body=body,
        headers=headers,
        compress=True,
    )


def extract_table(content: bytes) -> tuple[list[str], list[list[str]]]:
    """Extracts header and rows from the HTML table generated by TabNet within <PRE>...</PRE>."""
    text = content.decode("latin-1", errors="replace")
    m = re.search(r"<pre[^>]*>([\s\S]*?)</pre>", text, re.IGNORECASE)
    if not m:
        raise InvalidResponse("<PRE> tag not found in the TabNet response")

    block_pre = m.group(1).strip()
    reader = csv.reader(io.StringIO(block_pre), delimiter=";")
    raw_rows = [row for row in reader if any(c.strip() for c in row)]

    if not raw_rows:
        raise InvalidResponse("Empty <PRE> block in the TabNet response")

    header = [html.unescape(c.strip().strip('"')) for c in raw_rows[0]]
    rows = [[html.unescape(c.strip().strip('"')) for c in row] for row in raw_rows[1:]]

    # Filter any footer rows with divergent number of columns after 'Total'
    valid_rows = []
    reached_total = False
    for row in rows:
        if reached_total:
            break
        if len(row) != len(header):
            label = row[0].strip() if row else ""
            raise InvalidResponse(
                f"Malformed row before Total: label '{label}' with {len(row)} columns (expected {len(header)})"
            )
        valid_rows.append(row)
        if row and row[0].strip().lower() == "total":
            reached_total = True

    return header, valid_rows


def validate(content: bytes, *, min_rows: int = 1000) -> None:
    """Validates whether the TabNet response contains valid tabular data with total and uniform columns."""
    text = content.decode("latin-1", errors="replace")
    if "Nenhum registro selecionado" in text:
        raise InvalidResponse("TabNet returned 'Nenhum registro selecionado'")

    header, rows = extract_table(content)
    if not header:
        raise InvalidResponse("Empty header in the TabNet table")

    rows_municipality = [r for r in rows if r and re.match(r"^\d{6}", r[0].strip())]
    if len(rows_municipality) < min_rows:
        raise InvalidResponse(
            f"TabNet table has too few municipality rows ({len(rows_municipality)} < {min_rows})"
        )

    row_total = [r for r in rows if r and r[0].strip().lower() == "total"]
    if not row_total:
        raise InvalidResponse("'Total' row not found in the TabNet table")

    for i, row in enumerate(rows):
        if len(row) != len(header):
            raise InvalidResponse(
                f"Row {i} has a number of columns ({len(row)}) different from the header ({len(header)})"
            )


def download(folder: Path, **options) -> list[dict]:
    """Downloads all registered tabulations and periods to the raw data folder."""
    folder = Path(folder)
    reqs = [request(tab, p) for tab in TABULATIONS for p in tab.periods]
    interval = options.pop("interval", 1.0)
    return core.download_batch(reqs, folder, validate=validate, interval=interval, **options)
