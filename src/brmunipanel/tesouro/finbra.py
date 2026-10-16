"""Municipal committed expenditure by budget function and budget revenue in 2006–2012 (FINBRA, Tesouro Nacional).

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

The same databases bring budget revenue in table `Receita`, one column per revenue nature and one row per
municipality, keyed by `CD_UF` and `CD_MUN`. `harmonize_revenue` reads from it the eight columns of
`revenue.SCHEMA`, named in `REVENUE_SOURCE_COLUMNS`: realized revenue in current reais, gross for the revenue items,
and the current revenue deductions with the sign declared in the source. A null cell stays null.
"""

import io
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import polars as pl
from access_parser import AccessParser

from brmunipanel.core import Request, InvalidResponse, download_batch, read_raw
from brmunipanel.tesouro import revenue
from brmunipanel.tesouro.expenditure_by_function import PUBLISHED_COLUMNS, SCHEMA, FUNCTIONS


def convert_currency(value) -> float | None:
    """Converts an integer Access currency value (scaled by 10,000) to float by dividing by 10,000."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"Invalid type for currency: {type(value).__name__} (value: {value})")
    if isinstance(value, int):
        return value / 10000.0
    raise TypeError(f"Invalid type for currency: {type(value).__name__} (value: {value})")


def code_6(state, muni_code) -> str | None:
    """Formats 2-digit state and 4-digit municipality codes into a 6-digit string."""
    if state is None or muni_code is None:
        return None
    return f"{int(float(str(state).strip())):02d}{int(float(str(muni_code).strip())):04d}"


def validate_zip(content: bytes) -> None:
    """Validates that `content` is a ZIP file containing exactly one Access database (.mdb) file."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            mdb_members = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
            if len(mdb_members) != 1:
                raise InvalidResponse(f"ZIP must contain exactly 1 .mdb file, found: {len(mdb_members)}")
    except zipfile.BadZipFile:
        raise InvalidResponse("The content is not a valid ZIP file")


def download(folder: Path, **options) -> list[dict]:
    """Downloads FINBRA annual database ZIP archives (2006–2012) into `folder`."""
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


def read_access_table(folder: Path, year: int, name: str) -> dict[str, list]:
    """Reads table `name` from the annual Access database, returning column lists."""
    content = read_raw(folder, f"finbra_{year}.zip")
    with zipfile.ZipFile(io.BytesIO(content)) as zf, tempfile.TemporaryDirectory() as tmp:
        (member,) = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
        path = Path(zf.extract(member, tmp))
        database = AccessParser(str(path))
        database.extra_props = {}  # without the Format property, the currency field arrives as an integer (value × 10,000)
        table = database.parse_table(name)
        
    if not table:
        raise ValueError(f"{name} table empty or not found in year {year}")
        
    return {str(name).strip(): list(values) for name, values in table.items()}


def read_dsubfuncao(folder: Path, year: int) -> dict[str, list]:
    """Reads table `DSubFuncao` from the annual Access database, returning column lists."""
    return read_access_table(folder, year, "DSubFuncao")


def process_table(table: dict[str, list], year: int, municipalities: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    """Processes raw `DSubFuncao` columns into a harmonized DataFrame, mapping 6-digit to 7-digit codes."""
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
    """Harmonizes FINBRA municipal expenditure by function for 2006–2012, sorted by municipality and year."""
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


REVENUE_SOURCE_COLUMNS = {
    "rev_current_gross": "Rec Correntes",
    "rev_current_deductions": "Deduções Rec Corrente",
    "rev_iptu": "IPTU",
    "rev_iss": "ISSQN",
    "rev_itbi": "ITBI",
    "rev_fees": "Taxas",
    "rev_fpm": "Cota FPM",
    "rev_icms_share": "Cota ICMS",
}


def process_revenue_table(table: dict[str, list], year: int, municipalities: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    """Processes raw `Receita` columns into the revenue schema, mapping 6-digit to 7-digit codes."""
    used_columns = ["CD_UF", "CD_MUN"] + list(REVENUE_SOURCE_COLUMNS.values())
    missing = [c for c in used_columns if c not in table]
    if missing:
        raise ValueError(f"Missing columns in the table: {missing}")

    sizes = {c: len(table[c]) for c in used_columns}
    if len(set(sizes.values())) > 1:
        raise ValueError(f"Inconsistent column sizes: {sizes}")

    municipalities_dict = dict(zip(municipalities["municipality_code_6"].to_list(), municipalities["municipality_code"].to_list()))
    discarded = []
    valid_rows = []
    seen_keys = []
    for i in range(next(iter(sizes.values()))):
        state = table["CD_UF"][i]
        code = table["CD_MUN"][i]
        key = code_6(state, code)
        if key is None:
            discarded.append({"year": year, "state": state, "muni_code": code, "reason": "null key"})
            continue
        seen_keys.append(key)
        if key not in municipalities_dict:
            discarded.append({"year": year, "state": state, "muni_code": code, "reason": "outside DTB"})
            continue
        row = {"municipality_code": municipalities_dict[key], "year": year}
        for column, source_column in REVENUE_SOURCE_COLUMNS.items():
            row[column] = convert_currency(table[source_column][i])
        valid_rows.append(row)

    repeated = [k for k, v in Counter(seen_keys).items() if v > 1]
    if repeated:
        raise ValueError(f"Repeated keys: {repeated}")
    if not valid_rows:
        return pl.DataFrame(schema=revenue.SCHEMA), discarded
    return pl.DataFrame(valid_rows, schema=revenue.SCHEMA).sort("municipality_code"), discarded


def harmonize_revenue(folder: Path, municipalities: pl.DataFrame) -> pl.DataFrame:
    """Harmonizes FINBRA municipal budget revenue for 2006–2012, sorted by municipality and year."""
    dfs = []
    for year in range(2006, 2013):
        df_year, discarded = process_revenue_table(read_access_table(folder, year, "Receita"), year, municipalities)
        dfs.append(df_year)
        if discarded:
            reasons = Counter(d["reason"] for d in discarded)
            print(f"{year}: {sum(reasons.values())} discarded ({', '.join(f'{k}: {v}' for k, v in reasons.items())})")
    return pl.concat(dfs).sort(["municipality_code", "year"])
