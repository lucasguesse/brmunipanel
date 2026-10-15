import pandas as pd
import polars as pl
from pathlib import Path
import re
import tempfile
import zipfile
from typing import Union

from brmunipanel.inep.connection import create_session
from brmunipanel.core import Request, InvalidResponse, download_batch

EDITION = 2025
STAGES = {"anos_iniciais": "early_years", "anos_finais": "final_years", "ensino_medio": "secondary"}
BASE_URL = "https://download.inep.gov.br/ideb/resultados"


def package_name(stage: str) -> str:
    """Returns the file name of the package of one stage in the release in use."""
    return f"divulgacao_{stage}_municipios_{EDITION}.zip"


def validate_zip(content: bytes):
    """Raises `InvalidResponse` if `content` does not start with standard ZIP magic bytes."""
    if not content.startswith(b"PK\x03\x04"):
        raise InvalidResponse("The content is not a valid ZIP file")


def download(folder: Union[Path, str], **options):
    """Downloads the three packages of the release, one per stage. Each package carries the whole series of its stage."""
    folder = Path(folder)
    reqs = [
        Request(
            key=f"{STAGES[stage]}/{EDITION}",
            url=f"{BASE_URL}/{package_name(stage)}",
            file=package_name(stage),
            method="GET",
            compress=False,
        )
        for stage in STAGES
    ]
    session = options.pop("session", None) or create_session()
    download_batch(reqs, folder, session=session, validate=validate_zip, interval=1.0, **options)

def _find_header_row(path: Path) -> int:
    """Finds the header row scanning the first 20 rows."""
    df_head = pd.read_excel(path, nrows=20, header=None)
    for i, row in df_head.iterrows():
        if "SG_UF" in row.values:
            return i
    raise ValueError(f"Header not found in {path}")

def _read_spreadsheet(path: Path, stage_suffix: str, valid_municipalities: set) -> pl.DataFrame:
    row_hdr = _find_header_row(path)
    # Read with the correct header, dtype=str prevents mixed inference and improper conversions
    df_pd = pd.read_excel(path, header=row_hdr, dtype=str)
    df = pl.from_pandas(df_pd)
    
    required_columns = ["CO_MUNICIPIO", "REDE"]
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Column {col} missing in {path}")
            
    df = df.filter(pl.col("REDE").is_not_null() & pl.col("CO_MUNICIPIO").is_not_null())
    df = df.with_columns(pl.col("REDE").cast(pl.Utf8).str.strip_chars())
    df = df.filter(pl.col("REDE") == "Pública")
    if df.height == 0:
        raise ValueError(f"Network 'Pública' not found in {path}")
        
    df = df.with_columns(pl.col("CO_MUNICIPIO").str.strip_chars())
        
    invalid_codes = df.filter(~pl.col("CO_MUNICIPIO").is_in(valid_municipalities))
    if invalid_codes.height > 0:
        raise ValueError(f"There are codes outside the municipal registry in {path}")
        
    columns_obs = [c for c in df.columns if re.match(r"^VL_OBSERVADO_\d{4}$", c)]
    if not columns_obs:
        raise ValueError(f"No VL_OBSERVADO_AAAA column found in {path}")
        
    df_sel = df.select(["CO_MUNICIPIO"] + columns_obs)
    
    df_long = df_sel.unpivot(
        index="CO_MUNICIPIO",
        on=columns_obs,
        variable_name="year_column",
        value_name=f"ideb_{stage_suffix}_public"
    )
    
    df_long = df_long.with_columns(
        pl.col("year_column").str.replace("VL_OBSERVADO_", "").cast(pl.Int16).alias("year")
    ).drop("year_column")
    
    val_col = f"ideb_{stage_suffix}_public"
    # Original values '-' and 'ND' will fail cast(strict=False) and return null, which is the desired behavior.
    # Replace comma with dot to prevent scores from being read as invalid strings.
    df_long = df_long.with_columns(
        pl.col(val_col).str.strip_chars().str.replace(",", ".").cast(pl.Float64, strict=False)
    )
        
    df_long = df_long.rename({"CO_MUNICIPIO": "municipality_code"})
    
    duplicates = df_long.group_by(["municipality_code", "year"]).len().filter(pl.col("len") > 1)
    if duplicates.height > 0:
        raise ValueError(f"Duplicate municipality_code-year key in {path}")
    
    return df_long

def _read_package(package: Path, stage_suffix: str, valid_municipalities: set) -> pl.DataFrame:
    """Reads the spreadsheet of one stage from inside the package, extracting it to a temporary folder."""
    with zipfile.ZipFile(package) as z:
        spreadsheets = [m for m in z.namelist() if m.lower().endswith(".xlsx")]
        if len(spreadsheets) != 1:
            raise ValueError(f"Package {package} should have one spreadsheet (.xlsx) and has {len(spreadsheets)}")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(z.extract(spreadsheets[0], temp))
            return _read_spreadsheet(path, stage_suffix, valid_municipalities)


def harmonize(folder: Union[Path, str], municipalities: pl.DataFrame) -> pl.DataFrame:
    """Harmonizes IDEB observed scores for public schools across education stages.

    Reads results for early years, final years, and secondary education, returning a DataFrame
    sorted by `municipality_code` and `year`.
    """
    folder = Path(folder)
    valid_municipalities = set(municipalities["municipality_code"].to_list())
    
    stages = STAGES
    
    dfs = []
    for folder_stage, suffix in stages.items():
        package = folder / package_name(folder_stage)
        if package.exists():
            dfs.append(_read_package(package, suffix, valid_municipalities))
            continue

        path_dir = folder / folder_stage
        if not path_dir.exists():
            raise FileNotFoundError(f"Stage folder not found: {path_dir}")
            
        files_xlsx = list(path_dir.rglob("*.xlsx"))
        if not files_xlsx:
            raise FileNotFoundError(f"No .xlsx found for stage {folder_stage}")
        if len(files_xlsx) > 1:
            raise ValueError(f"More than one .xlsx file found for stage {folder_stage}: {files_xlsx}")
            
        path_xlsx = files_xlsx[0]
        df_stage = _read_spreadsheet(path_xlsx, suffix, valid_municipalities)
        dfs.append(df_stage)
        
    df_final = dfs[0]
    for df_next in dfs[1:]:
        df_final = df_final.join(df_next, on=["municipality_code", "year"], how="full", coalesce=True)
        
    df_final = df_final.sort(["municipality_code", "year"])
    
    df_final = df_final.select([
        "municipality_code",
        "year",
        "ideb_early_years_public",
        "ideb_final_years_public",
        "ideb_secondary_public"
    ])
    
    final_duplicates = df_final.group_by(["municipality_code", "year"]).len().filter(pl.col("len") > 1)
    if final_duplicates.height > 0:
        raise ValueError("Duplicate municipality_code-year key in the harmonized final panel")
    
    return df_final
