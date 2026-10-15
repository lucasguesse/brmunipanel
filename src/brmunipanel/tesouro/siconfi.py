"""Municipal committed expenditure by budget function in 2013–2023 (SICONFI, Tesouro Nacional).

The output contains only the 28 functions of the functional classification.
Declared total and intra-budgetary expenditure are used only in internal checks.

Source: "Contas Anuais" query from the SICONFI portal, table "Despesas por Função (Anexo I-E)", scope "Municípios",
with one file per fiscal year and all municipalities in each file. The portal blocks script downloads with a
captcha, so files are downloaded manually and placed in the source raw data folder. `download` does not access
the network: it checks the header of each `.zip` and records it in the manifest. To redo the download, open `PORTAL_URL`,
choose the fiscal year, scope, and table above, leave the approval period blank, and save the `.zip` in the
folder, under any name, because the year comes from inside the file. The 2024 file is recorded and not harmonized.

Harmonization uses only "Despesas Empenhadas" rows. A function with its own row uses the row value; without its own
row, it receives the sum of its subfunctions; with neither, it is zero. `exp_total_functions` is the total row
without intra-budgetary expenditures and remains null when the declaration does not include it. `exp_intra_budgetary` is the total
intra-budgetary row, or zero when it does not exist, and `declares_intra_budgetary` is true when it is greater than
zero. The "Demais Subfunções" account without function code, which only appears in 2017, is ignored. Municipalities without committed
expenditure in the year do not generate a row, and Distrito Federal is excluded. Output follows `expenditure_by_function.SCHEMA`.

The same declarations can be collected from the Tesouro API with `download_api`, which answers one municipality and
one year per request. The requests run at a fixed rate with overlapping calls, through `core.download_at_rate`, and
each year is stored as one gzip JSON Lines file with one line per municipality. `harmonize(..., source="api")`
reads those files with `read_api_year` and applies the same rules.
"""
import csv
import gzip
import json
import re
import zipfile
from pathlib import Path
from typing import Sequence
from urllib.parse import urlencode

import polars as pl

from brmunipanel import core
from brmunipanel.tesouro.expenditure_by_function import PUBLISHED_COLUMNS, SCHEMA, FUNCTIONS

YEARS = tuple(range(2013, 2024))
PORTAL_URL = "https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf"
SCOPE = "Municípios"
TABLE = "Despesas por Função (Anexo I-E)"
HEADER = "Instituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor"


API_URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca"


def api_annex(year: int) -> str:
    """Returns the annex name the API expects: without the "DCA-" prefix in 2013, with it from 2014 on."""
    return "Anexo I-E" if year == 2013 else "DCA-Anexo I-E"


def api_file(year: int) -> str:
    """Returns the gzip JSON Lines filename used to store API responses for `year`."""
    return f"dca_annex_i_e_{year}.jsonl.gz"


def api_requests(year: int, municipalities: Sequence[str]) -> list[core.Request]:
    """Builds a list of `Request` objects for all municipalities in `year` from the SICONFI API."""
    return [
        core.Request(
            key=f"{year}/{code}",
            url=f"{API_URL}?{urlencode({'an_exercicio': year, 'id_ente': code, 'no_anexo': api_annex(year)})}",
            file=api_file(year),
        )
        for code in sorted(municipalities)
    ]


def validate_api_response(content: bytes) -> None:
    """Validates that API response `content` is valid JSON containing a single-page items list."""
    try:
        data = json.loads(content)
    except ValueError as error:
        raise core.InvalidResponse("The response is not JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise core.InvalidResponse("The response has no 'items' list")
    if data.get("hasMore"):
        raise core.InvalidResponse("The response has more than one page")


def download_api(folder: Path, municipalities: Sequence[str], years: Sequence[int] = YEARS, *, rate: float = 4.0, **options) -> list[dict]:
    """Downloads the declarations from the Tesouro API, one request per municipality and year, into one file per year.

    Distrito Federal is not requested, because it reports as a state. A year already in the manifest is skipped.
    """
    folder = Path(folder)
    codes = sorted({str(c) for c in municipalities if not str(c).startswith("53")})
    manifest = core.read_manifest(folder)
    records = []
    for year in years:
        key, file = f"dca_{year}", api_file(year)
        if key in manifest and (folder / file).exists():
            records.append(manifest[key])
            continue
        with core.ipv4_only():
            core.download_at_rate(api_requests(year, codes), folder / file, rate=rate, validate=validate_api_response, **options)
        records.append(
            core.record_file(
                folder,
                key,
                file,
                url=API_URL,
                method="GET",
                parameters={"an_exercicio": str(year), "no_anexo": api_annex(year), "municipalities": str(len(codes)), "rate": str(rate)},
            )
        )
    return records


def read_api_year(folder: Path, file: str) -> pl.DataFrame:
    """Reads one year collected from the API into the same columns that `read_file` returns."""
    data = []
    for row in gzip.decompress((Path(folder) / file).read_bytes()).decode("utf-8").splitlines():
        if not row.strip():
            continue
        for item in json.loads(json.loads(row)["body"])["items"]:
            value = item.get("valor")
            data.append((str(item["cod_ibge"]).zfill(7), item["coluna"], str(item["conta"]).strip(), None if value is None else float(value)))
    return pl.DataFrame(
        data,
        schema={"municipality_code": pl.String, "coluna": pl.String, "conta": pl.String, "valor": pl.Float64},
        orient="row",
    )


def read_header(zip_path: Path) -> dict:
    """Reads and validates the 4-line header from a portal ZIP file, returning metadata."""
    with zipfile.ZipFile(zip_path) as zf:
        members_csv = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(members_csv) != 1:
            raise ValueError(f"{zip_path.name}: expected 1 CSV file, found {len(members_csv)}")
            
        with zf.open(members_csv[0]) as f:
            rows = []
            for _ in range(4):
                try:
                    row = f.readline().decode("latin-1").strip()
                    rows.append(row)
                except Exception:
                    raise ValueError(f"{zip_path.name}: could not read the first 4 lines")
                    
            if len(rows) < 4:
                raise ValueError(f"{zip_path.name}: short file, fewer than 4 lines")
                
            l1, l2, l3, l4 = rows
            
            if not l1.startswith("Exercício: "):
                raise ValueError(f"{zip_path.name}: invalid line 1: {l1}")
            fiscal_year = int(l1.split(": ")[1])
            
            if not l2.startswith("Escopo: "):
                raise ValueError(f"{zip_path.name}: invalid line 2: {l2}")
            scope = l2.split(": ")[1]
            if scope != SCOPE:
                raise ValueError(f"{zip_path.name}: invalid scope: {scope}")
                
            if not l3.startswith("Tabela: "):
                raise ValueError(f"{zip_path.name}: invalid line 3: {l3}")
            table = l3.split(": ")[1]
            if table != TABLE:
                raise ValueError(f"{zip_path.name}: invalid table: {table}")
                
            if l4 != HEADER:
                raise ValueError(f"{zip_path.name}: invalid header: {l4}")
                
            return {
                "fiscal_year": fiscal_year,
                "scope": scope,
                "table": table
            }


def download(folder: Path, **options) -> list[dict]:
    """Validates and registers manually downloaded portal annual ZIP files in the manifest."""
    folder = Path(folder)
    if not folder.exists():
        folder.mkdir(parents=True)
    
    zips = sorted(folder.glob("*.zip"), key=lambda p: p.name)
    found_years = {}
    records = []
    
    for z in zips:
        hdr = read_header(z)
        year = hdr["fiscal_year"]
        
        if year in found_years:
            raise ValueError(f"Two files with the same fiscal year {year}: {found_years[year]} and {z.name}")
        found_years[year] = z.name
        
        record, _ = core.record_manual(
            folder, 
            key=f"annual_accounts_{year}", 
            file=z.name, 
            url=PORTAL_URL, 
            parameters={"fiscal_year": str(year), "scope": SCOPE, "table": TABLE}
        )
        records.append(record)
        
    missing_years = [year for year in YEARS if year not in found_years]
    if missing_years:
        raise FileNotFoundError(
            f"Missing years: {missing_years}. "
            f"Download them manually from {PORTAL_URL}, with the matching fiscal year, scope '{SCOPE}', "
            f"table '{TABLE}' and blank approval status, and save them in folder {folder}"
        )
        
    return records


def read_file(folder: Path, file: str) -> pl.DataFrame:
    """Reads raw portal CSV statements from `file` into a DataFrame of accounts and values."""
    path = Path(folder) / file
    
    with zipfile.ZipFile(path) as zf:
        members_csv = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        with zf.open(members_csv[0]) as f:
            rows = f.read().decode("latin-1").splitlines()
            
    rows = rows[3:]
    
    reader = csv.reader(rows, delimiter=";")
    headers = next(reader)
    
    idx_code = headers.index("Cod.IBGE")
    idx_column = headers.index("Coluna")
    idx_account = headers.index("Conta")
    idx_value = headers.index("Valor")
    
    data = []
    for i, row in enumerate(reader):
        if not row:
            continue
        if len(row) != len(headers):
            raise ValueError(f"{file}: line {i + 5} has a different number of fields than the header")
        muni_code = row[idx_code].replace(" ", "")
        column = row[idx_column]
        account = row[idx_account].strip()
        
        v_str = row[idx_value].strip()
        if not v_str:
            value = None
        else:
            value = float(v_str.replace(",", "."))
            
        data.append((muni_code, column, account, value))
        
    df = pl.DataFrame(
        data, 
        schema={"municipality_code": pl.String, "coluna": pl.String, "conta": pl.String, "valor": pl.Float64},
        orient="row"
    )
    return df


def process_statement(items: list[dict]) -> tuple[dict | None, list[str]]:
    """Extracts the 28 functional expenditures and totals from committed expenditure account items."""
    committed = [i for i in items if i["coluna"] == "Despesas Empenhadas"]
    if not committed:
        return None, []
        
    warnings = []
    
    rows_function = {}
    rows_subfunction = {}
    total_function = None
    intra = []
    
    for item in committed:
        account = item["conta"].strip()
        value = item["valor"]
        
        if value is None:
            value = 0.0
            warnings.append(f"null_value:{account}")
            
        if re.match(r"^(\d{2}) - ", account):
            code = account[:2]
            if not (1 <= int(code) <= 28):
                warnings.append(f"function_outside_classification:{code}")
                continue
            if code in rows_function:
                raise ValueError(f"Two function rows with the same code {code}")
            rows_function[code] = value
            
        elif re.match(r"^(?:(\d{2})\.\d{3}|FU(\d{2})) - ", account):
            m = re.match(r"^(?:(\d{2})\.\d{3}|FU(\d{2})) - ", account)
            code = m.group(1) or m.group(2)
            if not (1 <= int(code) <= 28):
                warnings.append(f"function_outside_classification:{code}")
                continue
            rows_subfunction.setdefault(code, []).append(value)
            
        elif account == "Demais Subfunções":
            if "residue_without_code" not in warnings:
                warnings.append("residue_without_code")
            
        elif "exceto" in account.lower() and "intra" in account.lower():
            if total_function is not None:
                raise ValueError("Two total rows per function")
            total_function = value
            
        elif "intra" in account.lower() and "exceto" not in account.lower():
            intra.append(value)
            
        else:
            warnings.append(f"unknown_account:{account}")
            
    ret = {}
    for code, _, c_out in FUNCTIONS:
        if code in rows_function:
            ret[c_out] = rows_function[code]
        elif code in rows_subfunction:
            ret[c_out] = sum(rows_subfunction[code])
            warnings.append(f"function_by_subfunctions:{code}")
        else:
            ret[c_out] = 0.0
            
    if total_function is not None:
        ret["exp_total_functions"] = total_function
    else:
        ret["exp_total_functions"] = None
        warnings.append("sem_total")
        
    if not intra:
        ret["exp_intra_budgetary"] = 0.0
    else:
        ret["exp_intra_budgetary"] = sum(intra)
        if len(intra) > 1:
            warnings.append("intra_in_more_than_one_row")
            
    ret["declares_intra_budgetary"] = ret["exp_intra_budgetary"] > 0
    
    return ret, warnings


def harmonize(folder: Path, municipalities: pl.DataFrame, report: list[dict] | None = None, source: str = "portal") -> pl.DataFrame:
    """Harmonizes SICONFI municipal expenditures by function for 2013–2023 from portal or API sources."""
    if source not in ("portal", "api"):
        raise ValueError(f"Unknown source: {source}")
    folder = Path(folder)
    manifest = core.read_manifest(folder)
    
    rows = []
    valid_codes = set(municipalities.select("municipality_code").to_series().to_list())
    
    for year in YEARS:
        key = f"dca_{year}" if source == "api" else f"annual_accounts_{year}"
        if key not in manifest:
            raise FileNotFoundError(f"Key {key} not found in the manifest. Run the download first")
            
        file = manifest[key]["file"]
        df = read_api_year(folder, file) if source == "api" else read_file(folder, file)
        muni_all = df.select("municipality_code").unique().to_series().to_list()
        
        df_committed = df.filter(pl.col("coluna") == "Despesas Empenhadas")
        df_dict = df_committed.partition_by("municipality_code", as_dict=True)
        
        n_harmonized = 0
        for muni_code in muni_all:
            if len(muni_code) != 7:
                if report is not None:
                    report.append({"municipality_code": muni_code, "year": year, "type": "invalid_code"})
                continue
            if muni_code.startswith("53"):
                if report is not None:
                    report.append({"municipality_code": muni_code, "year": year, "type": "distrito_federal"})
                continue
            if muni_code not in valid_codes:
                if report is not None:
                    report.append({"municipality_code": muni_code, "year": year, "type": "outside_dtb"})
                continue
                
            if (muni_code,) not in df_dict:
                if report is not None:
                    report.append({"municipality_code": muni_code, "year": year, "type": "no_committed_expenditure"})
                continue
                
            items = df_dict[(muni_code,)].to_dicts()
            ret, warnings = process_statement(items)
            
            if ret is None:
                if report is not None:
                    report.append({"municipality_code": muni_code, "year": year, "type": "no_committed_expenditure"})
                continue
                
            if report is not None:
                for warning in warnings:
                    report.append({"municipality_code": muni_code, "year": year, "type": warning})
                    
            ret["municipality_code"] = muni_code
            ret["year"] = year
            ret["source"] = "siconfi"
            rows.append(ret)
            n_harmonized += 1
            
        print(f"SICONFI {year}: {n_harmonized} municipalities harmonized")
        
    df_out = pl.DataFrame(rows, schema=SCHEMA).select(PUBLISHED_COLUMNS)
    df_out = df_out.sort(["municipality_code", "year"])
    return df_out
