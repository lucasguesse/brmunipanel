"""IBGE territorial tables: Divisão Territorial Brasileira (DTB 2025), Municípios Limítrofes (2024), Áreas Territoriais (2025), and Localidades do Brasil (2022).

DTB 2025: canonical list of municipalities (5,571 municipalities plus DF) and regionalization
(Intermediate and Immediate Geographic Regions).
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

from .. import nucleo
from ..nucleo import Requisicao, RespostaInvalida

CHAVE_DTB = "dtb_2025"
URL_DTB = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/2025/DTB_2025.zip"
ARQUIVO_DTB = "DTB_2025.zip"
NOME_XLS_DTB = "RELATORIO_DTB_BRASIL_2025_MUNICIPIOS.xls"

CHAVE_LIMITROFES = "limitrofes_2024"
URL_LIMITROFES = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/municipios_limitrofes/2024/BR_Municipios_2024_LIMITROFES.xls"
ARQUIVO_LIMITROFES = "BR_Municipios_2024_LIMITROFES.xls"

CHAVE_AREAS = "areas_2025"
URL_AREAS = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/areas_territoriais/2025/AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls"
ARQUIVO_AREAS = "AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls"

CHAVE_LOCALIDADES = "localidades_2022"
URL_LOCALIDADES = "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/Localidades_do_Brasil/2022/Localidades_Brasil_gpkg.zip"
ARQUIVO_LOCALIDADES = "Localidades_Brasil_gpkg.zip"
NOME_GPKG_LOCALIDADES = "BR_localidades_2022.gpkg"

UFS: dict[str, str] = {
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


def validar_dtb(conteudo: bytes) -> None:
    """Checks if the content is an intact zip containing the DTB municipalities report."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
            if NOME_XLS_DTB not in zf.namelist():
                raise RespostaInvalida(f"{NOME_XLS_DTB} não encontrado dentro do zip")
    except (zipfile.BadZipFile, RespostaInvalida) as erro:
        raise RespostaInvalida(f"Arquivo zip da DTB inválido: {erro}") from erro


def validar_localidades(conteudo: bytes) -> None:
    """Checks if the content is an intact zip containing the localities geopackage."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
            if NOME_GPKG_LOCALIDADES not in zf.namelist():
                raise RespostaInvalida(f"{NOME_GPKG_LOCALIDADES} não encontrado dentro do zip")
    except (zipfile.BadZipFile, RespostaInvalida) as erro:
        raise RespostaInvalida(f"Arquivo zip de localidades inválido: {erro}") from erro


def validar_limitrofes(conteudo: bytes) -> None:
    """Checks if the file starts with the OLE signature (D0 CF 11 E0) of legacy .xls spreadsheets."""
    if not conteudo.startswith(b"\xd0\xcf\x11\xe0"):
        raise RespostaInvalida("Assinatura OLE (D0 CF 11 E0) não encontrada no início do arquivo .xls")


def baixar(pasta: Path, **opcoes) -> list[dict]:
    """Downloads the DTB 2025 zip, the 2024 neighboring municipalities spreadsheet, the 2025 areas spreadsheet, and 2022 localities."""
    pasta = Path(pasta)
    req_dtb = Requisicao(
        chave=CHAVE_DTB,
        url=URL_DTB,
        arquivo=ARQUIVO_DTB,
        compactar=False,
    )
    req_lim = Requisicao(
        chave=CHAVE_LIMITROFES,
        url=URL_LIMITROFES,
        arquivo=ARQUIVO_LIMITROFES,
        compactar=False,
    )
    req_areas = Requisicao(
        chave=CHAVE_AREAS,
        url=URL_AREAS,
        arquivo=ARQUIVO_AREAS,
        compactar=False,
    )
    req_loc = Requisicao(
        chave=CHAVE_LOCALIDADES,
        url=URL_LOCALIDADES,
        arquivo=ARQUIVO_LOCALIDADES,
        compactar=False,
    )

    sessao = opcoes.pop("sessao", None) or requests.Session()
    intervalo = opcoes.pop("intervalo", 0.0)

    reg_dtb, baixou_dtb = nucleo.baixar(req_dtb, pasta, sessao=sessao, validar=validar_dtb, **opcoes)
    if baixou_dtb and intervalo:
        time.sleep(intervalo)
        
    reg_lim, baixou_lim = nucleo.baixar(req_lim, pasta, sessao=sessao, validar=validar_limitrofes, **opcoes)
    if baixou_lim and intervalo:
        time.sleep(intervalo)
        
    reg_areas, baixou_areas = nucleo.baixar(req_areas, pasta, sessao=sessao, validar=validar_limitrofes, **opcoes)
    if baixou_areas and intervalo:
        time.sleep(intervalo)
        
    reg_loc, _ = nucleo.baixar(req_loc, pasta, sessao=sessao, validar=validar_localidades, **opcoes)
    
    return [reg_dtb, reg_lim, reg_areas, reg_loc]


def ler_fronteira_e_litoral(pasta: Path) -> tuple[set[str], set[str]]:
    """Extracts sets of municipality codes with international borders and coastal borders."""
    conteudo = nucleo.ler_bruto(pasta, ARQUIVO_LIMITROFES)
    df_int = pd.read_excel(io.BytesIO(conteudo), sheet_name="Limítrofes com Limite Internacional", header=0, dtype=str)
    df_oa = pd.read_excel(io.BytesIO(conteudo), sheet_name="Limítrofes com Oceano Atlântico", header=0, dtype=str)
    fronteira = set(df_int["CD_MUN"].dropna().astype(str).str.strip())
    litoral = set(df_oa["CD_MUN"].dropna().astype(str).str.strip())
    return fronteira, litoral


def processar_areas_df(df: pd.DataFrame) -> dict[str, float]:
    """Processes the areas spreadsheet and returns a dictionary from cod_municipio to area in km²."""
    df_filtrado = df[df["CD_MUN"].astype(str).str.strip().str.fullmatch(r"\d{7}")].copy()
    codigos = df_filtrado["CD_MUN"].astype(str).str.strip()
    
    if codigos.duplicated().any():
        duplicados = codigos[codigos.duplicated()].tolist()
        raise ValueError(f"Códigos repetidos encontrados: {duplicados}")
    
    dict_areas = {}
    for cd, ar in zip(codigos, df_filtrado["AR_MUN_2025"]):
        if pd.isna(ar) or str(ar).strip() == "":
            raise ValueError(f"Área vazia ou nula encontrada para o código {cd}: {ar}")
        try:
            val = float(ar)
        except ValueError as e:
            raise ValueError(f"Área não numérica encontrada para o código {cd}: {ar}") from e
            
        if pd.isna(val):
            raise ValueError(f"Área nula (NaN) encontrada para o código {cd}")
            
        dict_areas[cd] = val
        
    return dict_areas


def ler_areas(pasta: Path) -> dict[str, float]:
    """Reads the areas spreadsheet and returns dictionary."""
    conteudo = nucleo.ler_bruto(pasta, ARQUIVO_AREAS)
    df = pd.read_excel(io.BytesIO(conteudo), sheet_name="AR_BR_MUN_2025", header=0, dtype=str)
    return processar_areas_df(df)


def processar_sedes_df(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Processes the localities table and returns a dictionary from cod_municipio to seat (latitude, longitude)."""
    df_filtrado = df[df["CT_LOCALIDADE"].isin(["Cidade", "Distrito Estadual de Fernando de Noronha"])].copy()
    
    dict_sedes = {}
    
    for _, linha in df_filtrado.iterrows():
        cd = str(linha["CD_MUN"]).strip()
        if len(cd) != 7 or not cd.isdigit():
            raise ValueError(f"Código do município inválido (não tem 7 dígitos): {cd}")
            
        lat_val = linha["LAT_LOCALIDADE"]
        lon_val = linha["LONG_LOCALIDADE"]
        
        if pd.isna(lat_val) or str(lat_val).strip() == "":
            raise ValueError(f"Latitude nula ou vazia para o código {cd}")
        if pd.isna(lon_val) or str(lon_val).strip() == "":
            raise ValueError(f"Longitude nula ou vazia para o código {cd}")
            
        try:
            lat = float(lat_val)
        except ValueError as e:
            raise ValueError(f"Latitude não numérica para o código {cd}: {lat_val}") from e
            
        try:
            lon = float(lon_val)
        except ValueError as e:
            raise ValueError(f"Longitude não numérica para o código {cd}: {lon_val}") from e
            
        if pd.isna(lat) or pd.isna(lon):
            raise ValueError(f"Coordenada nula (NaN) para o código {cd}")
            
        lat_r = round(lat, 4)
        lon_r = round(lon, 4)
        
        if not (-34.0 <= lat_r <= 5.5):
            raise ValueError(f"Latitude fora do intervalo para o código {cd}: {lat_r}")
        if not (-74.5 <= lon_r <= -32.0):
            raise ValueError(f"Longitude fora do intervalo para o código {cd}: {lon_r}")
            
        if cd in dict_sedes:
            if dict_sedes[cd] != (lat_r, lon_r):
                raise ValueError(f"Coordenadas diferentes para linhas de sede do mesmo código {cd}")
        else:
            dict_sedes[cd] = (lat_r, lon_r)
            
    return dict_sedes


def ler_sedes(pasta: Path) -> dict[str, tuple[float, float]]:
    """Reads the localities geopackage and returns dictionary."""
    conteudo = nucleo.ler_bruto(pasta, ARQUIVO_LOCALIDADES)
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
        banco = zf.read(NOME_GPKG_LOCALIDADES)
    if hasattr(sqlite3.Connection, "deserialize"):
        con = sqlite3.connect(":memory:")
        try:
            con.deserialize(banco)
            linhas = con.execute(
                'SELECT CD_MUN, CT_LOCALIDADE, LAT_LOCALIDADE, LONG_LOCALIDADE FROM "BR_localidades_2022"'
            ).fetchall()
        finally:
            con.close()
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "localidades.gpkg"
            tmp_path.write_bytes(banco)
            con = sqlite3.connect(tmp_path)
            try:
                linhas = con.execute(
                    'SELECT CD_MUN, CT_LOCALIDADE, LAT_LOCALIDADE, LONG_LOCALIDADE FROM "BR_localidades_2022"'
                ).fetchall()
            finally:
                con.close()
    df = pd.DataFrame(linhas, columns=["CD_MUN", "CT_LOCALIDADE", "LAT_LOCALIDADE", "LONG_LOCALIDADE"])
    return processar_sedes_df(df)


def processar_dtb_df(
    df: pd.DataFrame,
    codigos_fronteira: set[str],
    codigos_litoral: set[str],
    areas: dict[str, float] | None = None,
    sedes: dict[str, tuple[float, float]] | None = None,
) -> pl.DataFrame:
    """Transforms the raw DTB DataFrame into the standardized municipalities table."""
    cod_m = df["Código Município Completo"].astype(str).str.strip()
    cod_uf = df["UF"].astype(str).str.strip()

    tabela = pl.DataFrame({
        "cod_municipio": cod_m,
        "cod_municipio_6": cod_m.str.slice(0, 6),
        "nome_municipio": df["Nome_Município"].astype(str).str.strip(),
        "cod_uf": cod_uf,
        "sigla_uf": [UFS.get(u, "") for u in cod_uf],
        "nome_uf": df["Nome_UF"].astype(str).str.strip(),
        "cod_rg_intermediaria": df["Região Geográfica Intermediária"].astype(str).str.strip(),
        "nome_rg_intermediaria": df["Nome Região Geográfica Intermediária"].astype(str).str.strip(),
        "cod_rg_imediata": df["Região Geográfica Imediata"].astype(str).str.strip(),
        "nome_rg_imediata": df["Nome Região Geográfica Imediata"].astype(str).str.strip(),
        "fronteira_internacional": [c in codigos_fronteira for c in cod_m],
        "litoraneo": [c in codigos_litoral for c in cod_m],
        "area_km2": pl.Series([areas.get(c, None) if areas is not None else None for c in cod_m], dtype=pl.Float64),
        "latitude_sede": pl.Series([sedes.get(c, (None, None))[0] if sedes is not None else None for c in cod_m], dtype=pl.Float64),
        "longitude_sede": pl.Series([sedes.get(c, (None, None))[1] if sedes is not None else None for c in cod_m], dtype=pl.Float64),
    })
    return tabela.sort("cod_municipio")


def harmonizar_municipios(
    pasta: Path,
    codigos_fronteira: Iterable[str] | None = None,
    codigos_litoraneo: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Harmonizes the canonical municipalities table from DTB 2025 and the border/coastal tabs."""
    pasta = Path(pasta)
    if codigos_fronteira is None or codigos_litoraneo is None:
        f, l = ler_fronteira_e_litoral(pasta)
        codigos_fronteira = codigos_fronteira if codigos_fronteira is not None else f
        codigos_litoraneo = codigos_litoraneo if codigos_litoraneo is not None else l

    areas = ler_areas(pasta)
    sedes = ler_sedes(pasta)

    conteudo_zip = nucleo.ler_bruto(pasta, ARQUIVO_DTB)
    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as zf:
        with zf.open(NOME_XLS_DTB) as f_xls:
            df_raw = pd.read_excel(f_xls, header=6, dtype=str)

    return processar_dtb_df(df_raw, set(codigos_fronteira), set(codigos_litoraneo), areas, sedes)


def processar_limitrofes_df(
    df: pd.DataFrame,
    codigos_municipios: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Transforms the raw DataFrame from the 'Municípios Limítrofes' tab into the standardized pairs table.

    Applies two exclusion rules:
    1. Discards municipalities without terrestrial neighbors (N_LIM == 0 or CD_LIM null);
    2. Discards pairs where either code does not belong to `codigos_municipios` (DTB).
    """
    mascara_vizinho = df["CD_LIM"].notna()
    if "N_LIM" in df.columns:
        mascara_vizinho = mascara_vizinho & (df["N_LIM"].astype(str).str.strip() != "0")
    df_filtrado = df[mascara_vizinho].copy()

    cd_mun = df_filtrado["CD_MUN"].astype(str).str.strip()
    cd_lim = df_filtrado["CD_LIM"].astype(str).str.strip()
    comp_km = pd.to_numeric(df_filtrado["COMP_KM"], errors="coerce")

    tabela = pl.DataFrame({
        "cod_municipio": cd_mun,
        "cod_municipio_limitrofe": cd_lim,
        "comprimento_km": pl.Series(comp_km, dtype=pl.Float64),
    })

    if codigos_municipios is not None:
        codigos_set = set(codigos_municipios)
        tabela = tabela.filter(
            pl.col("cod_municipio").is_in(codigos_set)
            & pl.col("cod_municipio_limitrofe").is_in(codigos_set)
        )

    return tabela.sort("cod_municipio", "cod_municipio_limitrofe")


def harmonizar_limitrofes(
    pasta: Path,
    codigos_municipios: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Harmonizes the geographic adjacency matrix from the 2024 neighboring municipalities spreadsheet."""
    pasta = Path(pasta)
    if codigos_municipios is None:
        municipios = harmonizar_municipios(pasta)
        codigos_municipios = municipios["cod_municipio"].to_list()
    conteudo = nucleo.ler_bruto(pasta, ARQUIVO_LIMITROFES)
    df_raw = pd.read_excel(io.BytesIO(conteudo), sheet_name="Municípios Limítrofes", header=0, dtype=str)
    return processar_limitrofes_df(df_raw, codigos_municipios=codigos_municipios)
