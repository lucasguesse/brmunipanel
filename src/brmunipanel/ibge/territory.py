"""IBGE territorial tables: Divisão Territorial Brasileira (DTB 2025 and DTB 2011), Municípios Limítrofes (2024), Áreas Territoriais (2025), and Localidades do Brasil (2022).

DTB 2025: canonical list of municipalities (5,571 municipalities plus DF) and regionalization
(Intermediate and Immediate Geographic Regions).
DTB 2011: geographic mesoregions and microregions of the 1990 regional division, for the
5,565 municipalities that existed in 2011.
Municípios Limítrofes 2024: pairs of municipalities that share a physical border and
indicators of international border and Atlantic coast.
Áreas Territoriais 2025: territorial area of each municipality in km².
Localidades do Brasil 2022: latitude and longitude of the municipal seat.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd
import polars as pl
import requests

from .. import core
from ..core import Request, InvalidResponse

DTB_KEY = "dtb_2025"
DTB_URL = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/2025/DTB_2025.zip"
DTB_FILE = "DTB_2025.zip"
DTB_XLS_NAME = "RELATORIO_DTB_BRASIL_2025_MUNICIPIOS.xls"

DTB_2011_KEY = "dtb_2011"
DTB_2011_URL = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/2011/dtb_2011.zip"
DTB_2011_FILE = "dtb_2011.zip"
DTB_2011_XLS_NAME = "dtb_2011.xls"
DTB_2011_SHEET = "DTB_2011"
DTB_2011_COLUMNS = ["UF", "Nome_UF", "Mesorregião", "Nome_Meso", "Microrregião", "Nome_Micro", "Munic", "Nome_Munic"]
DTB_2011_COUNTS = {"rows": 5565, "states": 27, "mesoregions": 137, "microregions": 558}
REGIONS_2011_COLUMNS = ["mesoregion_2011_code", "mesoregion_2011_name", "microregion_2011_code", "microregion_2011_name"]

NEIGHBORING_KEY = "neighboring_2024"
NEIGHBORING_URL = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/municipios_limitrofes/2024/BR_Municipios_2024_LIMITROFES.xls"
NEIGHBORING_FILE = "BR_Municipios_2024_LIMITROFES.xls"

AREAS_KEY = "areas_2025"
AREAS_URL = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/areas_territoriais/2025/AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls"
AREAS_FILE = "AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls"

LOCALITIES_KEY = "localities_2022"
LOCALITIES_URL = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/Localidades_do_Brasil/2022/Localidades_Brasil_gpkg.zip"
LOCALITIES_FILE = "Localidades_Brasil_gpkg.zip"
LOCALITIES_GPKG_NAME = "BR_localidades_2022.gpkg"

STATE: dict[str, str] = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}


def validate_dtb(content: bytes) -> None:
    """Checks if the content is an intact zip containing the DTB municipalities report."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if DTB_XLS_NAME not in zf.namelist():
                raise InvalidResponse(f"{DTB_XLS_NAME} not found inside the zip")
    except (zipfile.BadZipFile, InvalidResponse) as error:
        raise InvalidResponse(f"Invalid DTB zip file: {error}") from error


def validate_dtb_2011(content: bytes) -> None:
    """Checks if the content is an intact zip containing the DTB 2011 spreadsheet."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if DTB_2011_XLS_NAME not in zf.namelist():
                raise InvalidResponse(f"{DTB_2011_XLS_NAME} not found inside the zip")
    except (zipfile.BadZipFile, InvalidResponse) as error:
        raise InvalidResponse(f"Invalid DTB 2011 zip file: {error}") from error


def validate_localities(content: bytes) -> None:
    """Checks if the content is an intact zip containing the localities geopackage."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if LOCALITIES_GPKG_NAME not in zf.namelist():
                raise InvalidResponse(f"{LOCALITIES_GPKG_NAME} not found inside the zip")
    except (zipfile.BadZipFile, InvalidResponse) as error:
        raise InvalidResponse(f"Invalid localities zip file: {error}") from error


def validate_neighboring(content: bytes) -> None:
    """Checks if the file starts with the OLE signature (D0 CF 11 E0) of legacy .xls spreadsheets."""
    if not content.startswith(b"\xd0\xcf\x11\xe0"):
        raise InvalidResponse("OLE signature (D0 CF 11 E0) not found at the start of the .xls file")


def download(folder: Path, **options) -> list[dict]:
    """Downloads the DTB 2025 and DTB 2011 zips, the 2024 neighboring municipalities spreadsheet, the 2025 areas spreadsheet, and 2022 localities."""
    folder = Path(folder)
    req_dtb = Request(
        key=DTB_KEY,
        url=DTB_URL,
        file=DTB_FILE,
        compress=False,
    )
    req_lim = Request(
        key=NEIGHBORING_KEY,
        url=NEIGHBORING_URL,
        file=NEIGHBORING_FILE,
        compress=False,
    )
    req_areas = Request(
        key=AREAS_KEY,
        url=AREAS_URL,
        file=AREAS_FILE,
        compress=False,
    )
    req_loc = Request(
        key=LOCALITIES_KEY,
        url=LOCALITIES_URL,
        file=LOCALITIES_FILE,
        compress=False,
    )
    req_dtb_2011 = Request(
        key=DTB_2011_KEY,
        url=DTB_2011_URL,
        file=DTB_2011_FILE,
        compress=False,
    )

    session = options.pop("session", None) or requests.Session()
    interval = options.pop("interval", 0.0)

    reg_dtb, downloaded_dtb = core.download(req_dtb, folder, session=session, validate=validate_dtb, **options)
    if downloaded_dtb and interval:
        time.sleep(interval)
        
    reg_lim, downloaded_lim = core.download(req_lim, folder, session=session, validate=validate_neighboring, **options)
    if downloaded_lim and interval:
        time.sleep(interval)
        
    reg_areas, downloaded_areas = core.download(req_areas, folder, session=session, validate=validate_neighboring, **options)
    if downloaded_areas and interval:
        time.sleep(interval)
        
    reg_loc, downloaded_loc = core.download(req_loc, folder, session=session, validate=validate_localities, **options)
    if downloaded_loc and interval:
        time.sleep(interval)
    reg_dtb_2011, _ = core.download(req_dtb_2011, folder, session=session, validate=validate_dtb_2011, **options)
    
    return [reg_dtb, reg_lim, reg_areas, reg_loc, reg_dtb_2011]


def read_border_and_coastal(folder: Path) -> tuple[set[str], set[str]]:
    """Extracts sets of municipality codes with international borders and coastal borders."""
    content = core.read_raw(folder, NEIGHBORING_FILE)
    df_int = pd.read_excel(io.BytesIO(content), sheet_name="Limítrofes com Limite Internacional", header=0, dtype=str)
    df_oa = pd.read_excel(io.BytesIO(content), sheet_name="Limítrofes com Oceano Atlântico", header=0, dtype=str)
    border = set(df_int["CD_MUN"].dropna().astype(str).str.strip())
    coastal = set(df_oa["CD_MUN"].dropna().astype(str).str.strip())
    return border, coastal


def process_areas_df(df: pd.DataFrame) -> dict[str, float]:
    """Processes the areas spreadsheet and returns a dictionary from municipality_code to area in km²."""
    df_filtered = df[df["CD_MUN"].astype(str).str.strip().str.fullmatch(r"\d{7}")].copy()
    codes = df_filtered["CD_MUN"].astype(str).str.strip()
    
    if codes.duplicated().any():
        duplicate = codes[codes.duplicated()].tolist()
        raise ValueError(f"Repeated codes found: {duplicate}")
    
    dict_areas = {}
    for cd, ar in zip(codes, df_filtered["AR_MUN_2025"]):
        if pd.isna(ar) or str(ar).strip() == "":
            raise ValueError(f"Empty or null area for code {cd}: {ar}")
        try:
            val = float(ar)
        except ValueError as e:
            raise ValueError(f"Non-numeric area for code {cd}: {ar}") from e
            
        if pd.isna(val):
            raise ValueError(f"Null (NaN) area for code {cd}")
            
        dict_areas[cd] = val
        
    return dict_areas


def read_areas(folder: Path) -> dict[str, float]:
    """Reads the areas spreadsheet and returns dictionary."""
    content = core.read_raw(folder, AREAS_FILE)
    df = pd.read_excel(io.BytesIO(content), sheet_name="AR_BR_MUN_2025", header=0, dtype=str)
    return process_areas_df(df)


def process_geoloc_df(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Processes the localities table and returns a dictionary from municipality_code to seat (latitude, longitude)."""
    df_filtered = df[df["CT_LOCALIDADE"].isin(["Cidade", "Distrito Estadual de Fernando de Noronha"])].copy()
    
    dict_geoloc = {}
    
    for _, row in df_filtered.iterrows():
        cd = str(row["CD_MUN"]).strip()
        if len(cd) != 7 or not cd.isdigit():
            raise ValueError(f"Invalid municipality code (not 7 digits): {cd}")
            
        lat_val = row["LAT_LOCALIDADE"]
        lon_val = row["LONG_LOCALIDADE"]
        
        if pd.isna(lat_val) or str(lat_val).strip() == "":
            raise ValueError(f"Null or empty latitude for code {cd}")
        if pd.isna(lon_val) or str(lon_val).strip() == "":
            raise ValueError(f"Null or empty longitude for code {cd}")
            
        try:
            lat = float(lat_val)
        except ValueError as e:
            raise ValueError(f"Non-numeric latitude for code {cd}: {lat_val}") from e
            
        try:
            lon = float(lon_val)
        except ValueError as e:
            raise ValueError(f"Non-numeric longitude for code {cd}: {lon_val}") from e
            
        if pd.isna(lat) or pd.isna(lon):
            raise ValueError(f"Null (NaN) coordinate for code {cd}")
            
        lat_r = round(lat, 4)
        lon_r = round(lon, 4)
        
        if not (-34.0 <= lat_r <= 5.5):
            raise ValueError(f"Latitude out of range for code {cd}: {lat_r}")
        if not (-74.5 <= lon_r <= -32.0):
            raise ValueError(f"Longitude out of range for code {cd}: {lon_r}")
            
        if cd in dict_geoloc:
            if dict_geoloc[cd] != (lat_r, lon_r):
                raise ValueError(f"Different coordinates for seat rows with the same code {cd}")
        else:
            dict_geoloc[cd] = (lat_r, lon_r)
            
    return dict_geoloc


def read_geoloc(folder: Path) -> dict[str, tuple[float, float]]:
    """Reads the localities geopackage and returns dictionary."""
    content = core.read_raw(folder, LOCALITIES_FILE)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        database = zf.read(LOCALITIES_GPKG_NAME)
    if hasattr(sqlite3.Connection, "deserialize"):
        con = sqlite3.connect(":memory:")
        try:
            con.deserialize(database)
            rows = con.execute(
                'SELECT CD_MUN, CT_LOCALIDADE, LAT_LOCALIDADE, LONG_LOCALIDADE FROM "BR_localidades_2022"'
            ).fetchall()
        finally:
            con.close()
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "localities.gpkg"
            tmp_path.write_bytes(database)
            con = sqlite3.connect(tmp_path)
            try:
                rows = con.execute(
                    'SELECT CD_MUN, CT_LOCALIDADE, LAT_LOCALIDADE, LONG_LOCALIDADE FROM "BR_localidades_2022"'
                ).fetchall()
            finally:
                con.close()
    df = pd.DataFrame(rows, columns=["CD_MUN", "CT_LOCALIDADE", "LAT_LOCALIDADE", "LONG_LOCALIDADE"])
    return process_geoloc_df(df)


def process_dtb_2011_df(df: pd.DataFrame, expected_counts: dict[str, int] | None = None) -> pl.DataFrame:
    """Transforms the DTB 2011 sheet into one row per municipality with its 1990 mesoregion and microregion."""
    counts = DTB_2011_COUNTS if expected_counts is None else expected_counts
    if list(df.columns) != DTB_2011_COLUMNS:
        raise ValueError(f"Unexpected DTB 2011 columns: {list(df.columns)}")
    cells = df.astype(str).apply(lambda column: column.str.strip())
    code = cells["UF"] + cells["Munic"]
    if not code.str.fullmatch(r"\d{7}").all():
        raise ValueError("DTB 2011 municipality codes must have 7 digits")
    if code.duplicated().any():
        raise ValueError(f"DTB 2011 repeated codes: {code[code.duplicated()].tolist()[:3]}")
    observed = {
        "rows": len(cells),
        "states": cells["UF"].nunique(),
        "mesoregions": cells["Mesorregião"].nunique(),
        "microregions": cells["Microrregião"].nunique(),
    }
    if observed != counts:
        raise ValueError(f"DTB 2011 counts {observed} differ from the expected {counts}")
    mesoregions_per_microregion = cells.groupby("Microrregião")["Mesorregião"].nunique()
    if (mesoregions_per_microregion > 1).any():
        examples = mesoregions_per_microregion[mesoregions_per_microregion > 1].index.tolist()[:3]
        raise ValueError(f"DTB 2011 microregions in more than one mesoregion: {examples}")
    table = pl.DataFrame(
        {
            "municipality_code": code.tolist(),
            "mesoregion_2011_code": cells["Mesorregião"].tolist(),
            "mesoregion_2011_name": cells["Nome_Meso"].tolist(),
            "microregion_2011_code": cells["Microrregião"].tolist(),
            "microregion_2011_name": cells["Nome_Micro"].tolist(),
        },
        schema={column: pl.String for column in ["municipality_code", *REGIONS_2011_COLUMNS]},
    )
    return table.sort("municipality_code")


def read_dtb_2011(folder: Path) -> pl.DataFrame:
    """Reads the DTB 2011 spreadsheet, discarding the xlrd warnings about the legacy file structure."""
    content = core.read_raw(folder, DTB_2011_FILE)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xls = zf.read(DTB_2011_XLS_NAME)
    df = pd.read_excel(
        io.BytesIO(xls),
        sheet_name=DTB_2011_SHEET,
        header=0,
        dtype=str,
        engine="xlrd",
        engine_kwargs={"logfile": io.StringIO()},
    )
    return process_dtb_2011_df(df)


def process_dtb_df(
    df: pd.DataFrame,
    border_codes: set[str],
    coastal_codes: set[str],
    areas: dict[str, float] | None = None,
    geoloc: dict[str, tuple[float, float]] | None = None,
    regions_2011: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Transforms the raw DTB DataFrame into the standardized municipalities table; the 2011 region columns are null for municipalities absent from `regions_2011`."""
    code_m = df["Código Município Completo"].astype(str).str.strip()
    code_state = df["UF"].astype(str).str.strip()

    table = pl.DataFrame({
        "municipality_code": code_m,
        "municipality_code_6": code_m.str.slice(0, 6),
        "municipality_name": df["Nome_Município"].astype(str).str.strip(),
        "state_code": code_state,
        "state_abbr": [STATE.get(u, "") for u in code_state],
        "state_name": df["Nome_UF"].astype(str).str.strip(),
        "intermediate_region_code": df["Região Geográfica Intermediária"].astype(str).str.strip(),
        "intermediate_region_name": df["Nome Região Geográfica Intermediária"].astype(str).str.strip(),
        "immediate_region_code": df["Região Geográfica Imediata"].astype(str).str.strip(),
        "immediate_region_name": df["Nome Região Geográfica Imediata"].astype(str).str.strip(),
        "international_border": [c in border_codes for c in code_m],
        "coastal": [c in coastal_codes for c in code_m],
        "area_km2": pl.Series([areas.get(c, None) if areas is not None else None for c in code_m], dtype=pl.Float64),
        "latitude": pl.Series([geoloc.get(c, (None, None))[0] if geoloc is not None else None for c in code_m], dtype=pl.Float64),
        "longitude": pl.Series([geoloc.get(c, (None, None))[1] if geoloc is not None else None for c in code_m], dtype=pl.Float64),
    })
    if regions_2011 is None:
        regions_2011 = pl.DataFrame(schema={column: pl.String for column in ["municipality_code", *REGIONS_2011_COLUMNS]})
    missing = sorted(set(regions_2011["municipality_code"]) - set(table["municipality_code"]))
    if missing:
        raise ValueError(f"{len(missing)} DTB 2011 codes not in the DTB 2025. Examples: {missing[:3]}")
    table = table.join(regions_2011.select(["municipality_code", *REGIONS_2011_COLUMNS]), on="municipality_code", how="left")
    base = [column for column in table.columns if column not in REGIONS_2011_COLUMNS]
    position = base.index("immediate_region_name") + 1
    order = base[:position] + REGIONS_2011_COLUMNS + base[position:]
    return table.select(order).sort("municipality_code")


def harmonize_municipalities(
    folder: Path,
    border_codes: Iterable[str] | None = None,
    coastal_codes: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Harmonizes the canonical municipalities table from DTB 2025, the border/coastal tabs and the DTB 2011 regions."""
    folder = Path(folder)
    if border_codes is None or coastal_codes is None:
        border, coastal = read_border_and_coastal(folder)
        border_codes = border_codes if border_codes is not None else border
        coastal_codes = coastal_codes if coastal_codes is not None else coastal

    areas = read_areas(folder)
    geoloc = read_geoloc(folder)
    regions_2011 = read_dtb_2011(folder)

    content_zip = core.read_raw(folder, DTB_FILE)
    with zipfile.ZipFile(io.BytesIO(content_zip)) as zf:
        with zf.open(DTB_XLS_NAME) as f_xls:
            df_raw = pd.read_excel(f_xls, header=6, dtype=str)

    return process_dtb_df(df_raw, set(border_codes), set(coastal_codes), areas, geoloc, regions_2011)


def process_neighboring_df(
    df: pd.DataFrame,
    municipality_codes: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Transforms the raw DataFrame from the 'Municípios Limítrofes' tab into the standardized pairs table.

    Applies two exclusion rules:
    1. Discards municipalities without terrestrial neighbors (N_LIM == 0 or CD_LIM null);
    2. Discards pairs where either code does not belong to `municipality_codes` (DTB).
    """
    mask_neighbor = df["CD_LIM"].notna()
    if "N_LIM" in df.columns:
        mask_neighbor = mask_neighbor & (df["N_LIM"].astype(str).str.strip() != "0")
    df_filtered = df[mask_neighbor].copy()

    cd_muni = df_filtered["CD_MUN"].astype(str).str.strip()
    cd_lim = df_filtered["CD_LIM"].astype(str).str.strip()
    comp_km = pd.to_numeric(df_filtered["COMP_KM"], errors="coerce")

    table = pl.DataFrame({
        "municipality_code": cd_muni,
        "neighbor_municipality_code": cd_lim,
        "border_length_km": pl.Series(comp_km, dtype=pl.Float64),
    })

    if municipality_codes is not None:
        codes_set = set(municipality_codes)
        table = table.filter(
            pl.col("municipality_code").is_in(codes_set)
            & pl.col("neighbor_municipality_code").is_in(codes_set)
        )

    return table.sort("municipality_code", "neighbor_municipality_code")


def harmonize_neighboring(
    folder: Path,
    municipality_codes: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Harmonizes the geographic adjacency matrix from the 2024 neighboring municipalities spreadsheet."""
    folder = Path(folder)
    if municipality_codes is None:
        municipalities = harmonize_municipalities(folder)
        municipality_codes = municipalities["municipality_code"].to_list()
    content = core.read_raw(folder, NEIGHBORING_FILE)
    df_raw = pd.read_excel(io.BytesIO(content), sheet_name="Municípios Limítrofes", header=0, dtype=str)
    return process_neighboring_df(df_raw, municipality_codes=municipality_codes)
