import pandas as pd
import polars as pl
from pathlib import Path
import re
import tempfile
import zipfile
from typing import Union

from brmunipanel.inep.conexao import criar_sessao
from brmunipanel.nucleo import Requisicao, RespostaInvalida, baixar_lote

EDICAO = 2025
ETAPAS = ["anos_iniciais", "anos_finais", "ensino_medio"]
URL_BASE = "https://download.inep.gov.br/ideb/resultados"


def nome_pacote(etapa: str) -> str:
    """Returns the file name of the package of one stage in the release in use."""
    return f"divulgacao_{etapa}_municipios_{EDICAO}.zip"


def validar_zip(conteudo: bytes):
    if not conteudo.startswith(b"PK\x03\x04"):
        raise RespostaInvalida("O conteúdo não é um arquivo ZIP válido.")


def baixar(pasta: Union[Path, str], **opcoes):
    """Downloads the three packages of the release, one per stage. Each package carries the whole series of its stage."""
    pasta = Path(pasta)
    reqs = [
        Requisicao(
            chave=f"{etapa}/{EDICAO}",
            url=f"{URL_BASE}/{nome_pacote(etapa)}",
            arquivo=nome_pacote(etapa),
            metodo="GET",
            compactar=False,
        )
        for etapa in ETAPAS
    ]
    sessao = opcoes.pop("sessao", None) or criar_sessao()
    baixar_lote(reqs, pasta, sessao=sessao, validar=validar_zip, intervalo=1.0, **opcoes)

def _encontrar_linha_cabecalho(caminho: Path) -> int:
    """Finds the header row scanning the first 20 rows."""
    df_head = pd.read_excel(caminho, nrows=20, header=None)
    for i, row in df_head.iterrows():
        if "SG_UF" in row.values:
            return i
    raise ValueError(f"Cabeçalho não encontrado em {caminho}")

def _ler_planilha(caminho: Path, etapa_sufixo: str, valid_municipios: set) -> pl.DataFrame:
    linha_cab = _encontrar_linha_cabecalho(caminho)
    # Read with the correct header, dtype=str prevents mixed inference and improper conversions
    df_pd = pd.read_excel(caminho, header=linha_cab, dtype=str)
    df = pl.from_pandas(df_pd)
    
    colunas_obrigatorias = ["CO_MUNICIPIO", "REDE"]
    for col in colunas_obrigatorias:
        if col not in df.columns:
            raise ValueError(f"Coluna {col} ausente em {caminho}")
            
    df = df.filter(pl.col("REDE").is_not_null() & pl.col("CO_MUNICIPIO").is_not_null())
    df = df.with_columns(pl.col("REDE").cast(pl.Utf8).str.strip_chars())
    df = df.filter(pl.col("REDE") == "Pública")
    if df.height == 0:
        raise ValueError(f"Rede 'Pública' não encontrada em {caminho}")
        
    df = df.with_columns(pl.col("CO_MUNICIPIO").str.strip_chars())
        
    codigos_invalidos = df.filter(~pl.col("CO_MUNICIPIO").is_in(valid_municipios))
    if codigos_invalidos.height > 0:
        raise ValueError(f"Existem códigos fora do cadastro municipal em {caminho}")
        
    colunas_obs = [c for c in df.columns if re.match(r"^VL_OBSERVADO_\d{4}$", c)]
    if not colunas_obs:
        raise ValueError(f"Nenhuma coluna VL_OBSERVADO_AAAA encontrada em {caminho}")
        
    df_sel = df.select(["CO_MUNICIPIO"] + colunas_obs)
    
    df_long = df_sel.unpivot(
        index="CO_MUNICIPIO",
        on=colunas_obs,
        variable_name="coluna_ano",
        value_name=f"ideb_{etapa_sufixo}_publica"
    )
    
    df_long = df_long.with_columns(
        pl.col("coluna_ano").str.replace("VL_OBSERVADO_", "").cast(pl.Int16).alias("ano")
    ).drop("coluna_ano")
    
    val_col = f"ideb_{etapa_sufixo}_publica"
    # Original values '-' and 'ND' will fail cast(strict=False) and return null, which is the desired behavior.
    # Replace comma with dot to prevent scores from being read as invalid strings.
    df_long = df_long.with_columns(
        pl.col(val_col).str.strip_chars().str.replace(",", ".").cast(pl.Float64, strict=False)
    )
        
    df_long = df_long.rename({"CO_MUNICIPIO": "cod_municipio"})
    
    duplicatas = df_long.group_by(["cod_municipio", "ano"]).len().filter(pl.col("len") > 1)
    if duplicatas.height > 0:
        raise ValueError(f"Chave cod_municipio-ano duplicada encontrada em {caminho}")
    
    return df_long

def _ler_pacote(pacote: Path, etapa_sufixo: str, valid_municipios: set) -> pl.DataFrame:
    """Reads the spreadsheet of one stage from inside the package, extracting it to a temporary folder."""
    with zipfile.ZipFile(pacote) as z:
        planilhas = [m for m in z.namelist() if m.lower().endswith(".xlsx")]
        if len(planilhas) != 1:
            raise ValueError(f"O pacote {pacote} deveria ter uma planilha .xlsx e tem {len(planilhas)}")
        with tempfile.TemporaryDirectory() as temporaria:
            caminho = Path(z.extract(planilhas[0], temporaria))
            return _ler_planilha(caminho, etapa_sufixo, valid_municipios)


def harmonizar(pasta: Union[Path, str], municipios: pl.DataFrame) -> pl.DataFrame:
    pasta = Path(pasta)
    valid_municipios = set(municipios["cod_municipio"].to_list())
    
    etapas = {
        "anos_iniciais": "anos_iniciais",
        "anos_finais": "anos_finais",
        "ensino_medio": "ensino_medio"
    }
    
    dfs = []
    for pasta_etapa, sufixo in etapas.items():
        pacote = pasta / nome_pacote(pasta_etapa)
        if pacote.exists():
            dfs.append(_ler_pacote(pacote, sufixo, valid_municipios))
            continue

        caminho_dir = pasta / pasta_etapa
        if not caminho_dir.exists():
            raise FileNotFoundError(f"Pasta da etapa não encontrada: {caminho_dir}")
            
        arquivos_xlsx = list(caminho_dir.rglob("*.xlsx"))
        if not arquivos_xlsx:
            raise FileNotFoundError(f"Nenhum .xlsx encontrado para etapa {pasta_etapa}")
        if len(arquivos_xlsx) > 1:
            raise ValueError(f"Mais de um arquivo .xlsx encontrado para etapa {pasta_etapa}: {arquivos_xlsx}")
            
        caminho_xlsx = arquivos_xlsx[0]
        df_etapa = _ler_planilha(caminho_xlsx, sufixo, valid_municipios)
        dfs.append(df_etapa)
        
    df_final = dfs[0]
    for df_next in dfs[1:]:
        df_final = df_final.join(df_next, on=["cod_municipio", "ano"], how="full", coalesce=True)
        
    df_final = df_final.sort(["cod_municipio", "ano"])
    
    df_final = df_final.select([
        "cod_municipio",
        "ano",
        "ideb_anos_iniciais_publica",
        "ideb_anos_finais_publica",
        "ideb_ensino_medio_publica"
    ])
    
    duplicatas_finais = df_final.group_by(["cod_municipio", "ano"]).len().filter(pl.col("len") > 1)
    if duplicatas_finais.height > 0:
        raise ValueError("Chave cod_municipio-ano duplicada encontrada no painel final harmonizado")
    
    return df_final
