"""Municipal committed expenditure by budget function in 2006–2012 (FINBRA, Tesouro Nacional).

The output contains only the 28 functions of the functional classification.
Declared total and intra-budgetary expenditure are used only in internal checks.

Downloads the seven FINBRA (Finanças do Brasil) databases, one `.zip` per year with an Access database (`.mdb`),
from `thot-arquivos.tesouro.gov.br`, and reads table `DSubFuncao`, which has one row per municipality and one column
for each of the 28 functions of the functional classification. Values are committed expenditure, in current reais.

The Access currency field is an integer representing the value multiplied by 10,000. With the column's `Format`
property, `access-parser` returns this field as formatted text and errs on values below 10 cents
(reads 0.08 as 0.80). Therefore `ler_dsubfuncao` empties `extra_props` on the parser instance, receives the integer,
and `converter_moeda` performs the division by 10,000. The `access-parser` version is pinned because of this.

From 2006 to 2009 the source does not separate intra-budgetary expenditures (payments between agencies of the same municipality):
they are inside the functions, and `desp_intraorcamentaria` and `declara_intraorcamentaria` remain null. From 2010
onward they leave the functions and go to a dedicated source column: `desp_intraorcamentaria` brings that
total, and `declara_intraorcamentaria` is true when it is greater than zero.

Nothing is imputed or corrected. `desp_total_funcoes` is the total declared in the source (`Despesas por Função`), without
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

from brmunipanel.nucleo import Requisicao, RespostaInvalida, baixar_lote, ler_bruto
from brmunipanel.tesouro.despesa_funcao import COLUNAS_PUBLICADAS, ESQUEMA, FUNCOES


def converter_moeda(valor) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise TypeError(f"Tipo inválido para moeda: {type(valor).__name__} (valor: {valor})")
    if isinstance(valor, int):
        return valor / 10000.0
    raise TypeError(f"Tipo inválido para moeda: {type(valor).__name__} (valor: {valor})")


def codigo_6(uf, cod_mun) -> str | None:
    if uf is None or cod_mun is None:
        return None
    return f"{int(float(str(uf).strip())):02d}{int(float(str(cod_mun).strip())):04d}"


def validar_zip(conteudo: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
            mdb_members = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
            if len(mdb_members) != 1:
                raise RespostaInvalida(f"ZIP deve conter exatamente 1 arquivo .mdb, encontrados: {len(mdb_members)}")
    except zipfile.BadZipFile:
        raise RespostaInvalida("Conteúdo não é um ZIP válido")


def baixar(pasta: Path, **opcoes) -> list[dict]:
    urls = {
        2006: "https://thot-arquivos.tesouro.gov.br/publicacao/26268",
        2007: "https://thot-arquivos.tesouro.gov.br/publicacao/26267",
        2008: "https://thot-arquivos.tesouro.gov.br/publicacao/26265",
        2009: "https://thot-arquivos.tesouro.gov.br/publicacao/26262",
        2010: "https://thot-arquivos.tesouro.gov.br/publicacao/26259",
        2011: "https://thot-arquivos.tesouro.gov.br/publicacao/26256",
        2012: "https://thot-arquivos.tesouro.gov.br/publicacao/26244",
    }
    requisicoes = [
        Requisicao(
            chave=f"finbra_{ano}",
            url=url,
            arquivo=f"finbra_{ano}.zip",
            metodo="GET",
            cabecalhos={"User-Agent": "Mozilla/5.0"},
            compactar=False
        ) for ano, url in urls.items()
    ]
    return baixar_lote(requisicoes, pasta, validar=validar_zip, intervalo=2.0, **opcoes)


def ler_dsubfuncao(pasta: Path, ano: int) -> dict[str, list]:
    conteudo = ler_bruto(pasta, f"finbra_{ano}.zip")
    with zipfile.ZipFile(io.BytesIO(conteudo)) as zf, tempfile.TemporaryDirectory() as tmp:
        (membro,) = [n for n in zf.namelist() if n.lower().endswith(".mdb")]
        caminho = Path(zf.extract(membro, tmp))
        banco = AccessParser(str(caminho))
        banco.extra_props = {}  # without the Format property, the currency field arrives as an integer (value × 10,000)
        tabela = banco.parse_table("DSubFuncao")
        
    if not tabela:
        raise ValueError(f"Tabela DSubFuncao vazia ou não encontrada no ano {ano}")
        
    return {str(nome).strip(): list(valores) for nome, valores in tabela.items()}


def processar_tabela(tabela: dict[str, list], ano: int, municipios: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    colunas = [nome.strip() for nome in tabela.keys()]
    
    # Check that columns exist
    faltantes = [f for _, f, _ in FUNCOES if f not in colunas]
    if "UF" not in colunas:
        faltantes.append("UF")
    if "Cod Mun" not in colunas:
        faltantes.append("Cod Mun")
    if "Despesas por Função" not in colunas:
        faltantes.append("Despesas por Função")
        
    if faltantes:
        raise ValueError(f"Colunas faltando na tabela: {faltantes}")
        
    # Intra-budgetary column
    col_intra = [c for c in colunas if "intra" in c.lower()]
    if len(col_intra) > 1:
        raise ValueError(f"Múltiplas colunas intraorçamentárias encontradas: {col_intra}")
    nome_intra = col_intra[0] if col_intra else None
    
    # Check that columns have the same size
    colunas_usadas = ["UF", "Cod Mun", "Despesas por Função"] + [f for _, f, _ in FUNCOES]
    if nome_intra:
        colunas_usadas.append(nome_intra)
        
    tamanhos = {c: len(tabela[c]) for c in colunas_usadas}
    if len(set(tamanhos.values())) > 1:
        raise ValueError(f"Tamanhos de colunas inconsistentes: {tamanhos}")
        
    n_linhas = next(iter(tamanhos.values()))
    
    descartes = []
    linhas_validas = []
    
    municipios_dict = dict(zip(municipios["cod_municipio_6"].to_list(), municipios["cod_municipio"].to_list()))
    chaves_vistas = []
    
    for i in range(n_linhas):
        uf = tabela["UF"][i]
        cod = tabela["Cod Mun"][i]
        
        # Assemble key
        chave = codigo_6(uf, cod)
        if chave is None:
            descartes.append({"ano": ano, "uf": uf, "cod_mun": cod, "motivo": "chave nula"})
            continue
            
        chaves_vistas.append(chave)
        
        # Convert to 7 digits
        if chave not in municipios_dict:
            descartes.append({"ano": ano, "uf": uf, "cod_mun": cod, "motivo": "fora da DTB"})
            continue
            
        cod_7 = municipios_dict[chave]
        
        linha = {
            "cod_municipio": cod_7,
            "ano": ano,
            "fonte": "finbra",
        }
        
        # Convert monetary columns
        for _, f, c_out in FUNCOES:
            linha[c_out] = converter_moeda(tabela[f][i])
            
        linha["desp_total_funcoes"] = converter_moeda(tabela["Despesas por Função"][i])
        
        if nome_intra:
            val_intra = converter_moeda(tabela[nome_intra][i])
            linha["desp_intraorcamentaria"] = val_intra
            linha["declara_intraorcamentaria"] = val_intra is not None and val_intra > 0
        else:
            linha["desp_intraorcamentaria"] = None
            linha["declara_intraorcamentaria"] = None
            
        linhas_validas.append(linha)
        
    # Repeated key in year
    contagem_chaves = Counter(chaves_vistas)
    repetidas = [k for k, v in contagem_chaves.items() if v > 1]
    if repetidas:
        raise ValueError(f"Chaves repetidas: {repetidas}")
        
    # Assemble schema and sort
    if not linhas_validas:
        df = pl.DataFrame(schema=ESQUEMA)
    else:
        df = pl.DataFrame(linhas_validas, schema=ESQUEMA).sort("cod_municipio")
        
    return df, descartes


def harmonizar(pasta: Path, municipios: pl.DataFrame) -> pl.DataFrame:
    dfs = []
    for ano in range(2006, 2013):
        tabela = ler_dsubfuncao(pasta, ano)
        df_ano, descartes = processar_tabela(tabela, ano, municipios)
        dfs.append(df_ano)
        
        if descartes:
            motivos = Counter(d["motivo"] for d in descartes)
            print(f"{ano}: {sum(motivos.values())} descartes ({', '.join(f'{k}: {v}' for k, v in motivos.items())})")
            
    df_final = pl.concat(dfs).select(COLUNAS_PUBLICADAS).sort(["cod_municipio", "ano"])
    return df_final
