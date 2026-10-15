"""Municipal committed expenditure by budget function in 2006–2012 (FINBRA, Tesouro Nacional).

The output contains only the 28 functions of the functional classification.
Declared total and intra-budgetary expenditure are used only in internal checks.

Downloads the seven FINBRA (Finanças do Brasil) databases, one `.zip` per year with an Access database (`.mdb`),
from `thot-files.tesouro.gov.br`, and reads table `DSubFuncao`, which has one row per municipality and one column
for each of the 28 functions of the functional classification. Values are committed expenditure, in current reais.

The Access currency field is an integer representing the value multiplied by 10,000. With the column's `Format`
property, `access-parser` returns this field as formatted text and errs on values below 10 cents
(reads 0.08 as 0.80). Therefore `read_dsubfuncao` empties `extra_props` on the parser instance, receives the integer,
and `convert_currency` performs the division by 10,000. The `access-parser` version is pinned because of this.

From 2006 to 2009 the source does not separate intra-budgetary expenditures (payments between agencies of the same municipality):
they are inside the functions, and `exp_intra_budgetary` and `declares_intra_budgetary` remain null. From 2010
onward they leave the functions and go to a dedicated source column: `exp_intra_budgetary` brings that
total, and `declares_intra_budgetary` is true when it is greater than zero.

Nothing is imputed or corrected. `exp_total_functions` is the total declared in the source (`Despesas por Função`), without
recalculation: in 8 municipalities of 2010 it differs from the sum of the 28 functions. In 4 rows of 2011 and 2012, the total and
all functions are zero, and the entire expenditure is in the intra-budgetary column.
"""

import io
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import polars as pl
from access_parser import AccessParser

from brmunipanel.core import Request, InvalidResponse, download_batch, read_raw
from brmunipanel.tesouro.expenditure_by_function import PUBLISHED_COLUMNS, SCHEMA, FUNCTIONS


def convert_currency(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"Invalid type for currency: {type(value).__name__} (value: {value})")
    if isinstance(value, int):
        return value / 10000.0
    raise TypeError(f"Invalid type for currency: {type(value).__name__} (value: {value})")


def code_6(state, muni_code) -> str | None:
    if state is None or muni_code is None:
        return None
    return f"{int(float(str(state).strip())):02d}{int(float(str(muni_code).strip())):04d}"


def validate_zip(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            mdb_members = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
            if len(mdb_members) != 1:
                raise InvalidResponse(f"ZIP must contain exactly 1 .mdb file, found: {len(mdb_members)}")
    except zipfile.BadZipFile:
        raise InvalidResponse("The content is not a valid ZIP file")


def download(folder: Path, **options) -> list[dict]:
    urls = {
        2006: "https://thot-arquivos.tesouro.gov.br/publicacao/26268",
        2007: "https://thot-arquivos.tesouro.gov.br/publicacao/26267",
        2008: "https://thot-arquivos.tesouro.gov.br/publicacao/26265",
        2009: "https://thot-arquivos.tesouro.gov.br/publicacao/26262",
        2010: "https://thot-arquivos.tesouro.gov.br/publicacao/26259",
        2011: "https://thot-arquivos.tesouro.gov.br/publicacao/26256",
        2012: "https://thot-arquivos.tesouro.gov.br/publicacao/26244",
    }
    reqs = [
        Request(
            key=f"finbra_{year}",
            url=url,
            file=f"finbra_{year}.zip",
            method="GET",
            headers={"User-Agent": "Mozilla/5.0"},
            compress=False
        ) for year, url in urls.items()
    ]
    return download_batch(reqs, folder, validate=validate_zip, interval=2.0, **options)


def read_dsubfuncao(folder: Path, year: int) -> dict[str, list]:
    content = read_raw(folder, f"finbra_{year}.zip")
    with zipfile.ZipFile(io.BytesIO(content)) as zf, tempfile.TemporaryDirectory() as tmp:
        (member,) = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
        path = Path(zf.extract(member, tmp))
        database = AccessParser(str(path))
        database.extra_props = {}  # without the Format property, the currency field arrives as an integer (value × 10,000)
        table = database.parse_table("DSubFuncao")
        
    if not table:
        raise ValueError(f"DSubFuncao table empty or not found in year {year}")
        
    return {str(name).strip(): list(values) for name, values in table.items()}


def process_table(table: dict[str, list], year: int, municipalities: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    columns = [name.strip() for name in table.keys()]
    
    # Check that columns exist
    missing = [f for _, f, _ in FUNCTIONS if f not in columns]
    if "UF" not in columns:
        missing.append("UF")
    if "Cod Mun" not in columns:
        missing.append("Cod Mun")
    if "Despesas por Função" not in columns:
        missing.append("Despesas por Função")
        
    if missing:
        raise ValueError(f"Missing columns in the table: {missing}")
        
    # Intra-budgetary column
    col_intra = [c for c in columns if "intra" in c.lower()]
    if len(col_intra) > 1:
        raise ValueError(f"Multiple intra-budgetary columns found: {col_intra}")
    name_intra = col_intra[0] if col_intra else None
    
    # Check that columns have the same size
    used_columns = ["UF", "Cod Mun", "Despesas por Função"] + [f for _, f, _ in FUNCTIONS]
    if name_intra:
        used_columns.append(name_intra)
        
    sizes = {c: len(table[c]) for c in used_columns}
    if len(set(sizes.values())) > 1:
        raise ValueError(f"Inconsistent column sizes: {sizes}")
        
    n_rows = next(iter(sizes.values()))
    
    discarded = []
    valid_rows = []
    
    municipalities_dict = dict(zip(municipalities["municipality_code_6"].to_list(), municipalities["municipality_code"].to_list()))
    seen_keys = []
    
    for i in range(n_rows):
        state = table["UF"][i]
        code = table["Cod Mun"][i]
        
        # Assemble key
        key = code_6(state, code)
        if key is None:
            discarded.append({"year": year, "state": state, "muni_code": code, "reason": "null key"})
            continue
            
        seen_keys.append(key)
        
        # Convert to 7 digits
        if key not in municipalities_dict:
            discarded.append({"year": year, "state": state, "muni_code": code, "reason": "outside DTB"})
            continue
            
        code_7 = municipalities_dict[key]
        
        row = {
            "municipality_code": code_7,
            "year": year,
            "source": "finbra",
        }
        
        # Convert monetary columns
        for _, f, c_out in FUNCTIONS:
            row[c_out] = convert_currency(table[f][i])
            
        row["exp_total_functions"] = convert_currency(table["Despesas por Função"][i])
        
        if name_intra:
            val_intra = convert_currency(table[name_intra][i])
            row["exp_intra_budgetary"] = val_intra
            row["declares_intra_budgetary"] = val_intra is not None and val_intra > 0
        else:
            row["exp_intra_budgetary"] = None
            row["declares_intra_budgetary"] = None
            
        valid_rows.append(row)
        
    # Repeated key in year
    count_keys = Counter(seen_keys)
    repeated = [k for k, v in count_keys.items() if v > 1]
    if repeated:
        raise ValueError(f"Repeated keys: {repeated}")
        
    # Assemble schema and sort
    if not valid_rows:
        df = pl.DataFrame(schema=SCHEMA)
    else:
        df = pl.DataFrame(valid_rows, schema=SCHEMA).sort("municipality_code")
        
    return df, discarded


def harmonize(folder: Path, municipalities: pl.DataFrame) -> pl.DataFrame:
    dfs = []
    for year in range(2006, 2013):
        table = read_dsubfuncao(folder, year)
        df_year, discarded = process_table(table, year, municipalities)
        dfs.append(df_year)
        
        if discarded:
            reasons = Counter(d["reason"] for d in discarded)
            print(f"{year}: {sum(reasons.values())} discarded ({', '.join(f'{k}: {v}' for k, v in reasons.items())})")
            
    df_final = pl.concat(dfs).select(PUBLISHED_COLUMNS).sort(["municipality_code", "year"])
    return df_final
