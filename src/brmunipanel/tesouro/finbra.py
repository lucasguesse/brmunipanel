"""Despesa municipal empenhada por função em 2006–2012 (FINBRA, Tesouro Nacional).

Por decisão do usuário de 2026-10-07, a saída publicada tem só as 28 funções.
O total declarado e a despesa intraorçamentária são usados só nas conferências internas.

Baixa os sete bancos de dados do FINBRA (Finanças do Brasil), um `.zip` por ano com um banco Access (`.mdb`),
de `thot-arquivos.tesouro.gov.br`, e lê a tabela `DSubFuncao`, que tem uma linha por município e uma coluna
para cada uma das 28 funções da classificação funcional. Os valores são despesa empenhada, em reais correntes.

O campo monetário do Access é um inteiro que vale o valor multiplicado por 10.000. Com a propriedade `Format`
da coluna, o `access-parser` devolve esse campo como texto formatado e erra os valores abaixo de 10 centavos
(lê 0,08 como 0,80). Por isso `ler_dsubfuncao` esvazia `extra_props` na instância do leitor, recebe o inteiro,
e `converter_moeda` faz a divisão por 10.000. A versão do `access-parser` é fixada por causa disso.

De 2006 a 2009 a fonte não separa as despesas intraorçamentárias (pagamentos entre órgãos do mesmo município):
elas estão dentro das funções, e `desp_intraorcamentaria` e `declara_intraorcamentaria` ficam nulas. De 2010
em diante elas saem das funções e vão para uma coluna própria da fonte: `desp_intraorcamentaria` traz esse
total, e `declara_intraorcamentaria` é verdadeira quando ele é maior que zero.

Nada é imputado nem corrigido. `desp_total_funcoes` é o total declarado na fonte (`Despesas por Função`), sem
recálculo: em 8 municípios de 2010 ele difere da soma das 28 funções. Em 4 linhas de 2011 e 2012, o total e
todas as funções valem zero, e a despesa inteira está na coluna intraorçamentária.
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
        banco.extra_props = {}  # sem a propriedade Format, o campo monetário chega como inteiro (valor × 10.000)
        tabela = banco.parse_table("DSubFuncao")
        
    if not tabela:
        raise ValueError(f"Tabela DSubFuncao vazia ou não encontrada no ano {ano}")
        
    return {str(nome).strip(): list(valores) for nome, valores in tabela.items()}


def processar_tabela(tabela: dict[str, list], ano: int, municipios: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    colunas = [nome.strip() for nome in tabela.keys()]
    
    # 1. Conferir que as colunas existem
    faltantes = [f for _, f, _ in FUNCOES if f not in colunas]
    if "UF" not in colunas:
        faltantes.append("UF")
    if "Cod Mun" not in colunas:
        faltantes.append("Cod Mun")
    if "Despesas por Função" not in colunas:
        faltantes.append("Despesas por Função")
        
    if faltantes:
        raise ValueError(f"Colunas faltando na tabela: {faltantes}")
        
    # 2. Coluna intraorçamentária
    col_intra = [c for c in colunas if "intra" in c.lower()]
    if len(col_intra) > 1:
        raise ValueError(f"Múltiplas colunas intraorçamentárias encontradas: {col_intra}")
    nome_intra = col_intra[0] if col_intra else None
    
    # 3. Conferir que as colunas têm o mesmo tamanho
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
        
        # 4. Montar a chave
        chave = codigo_6(uf, cod)
        if chave is None:
            descartes.append({"ano": ano, "uf": uf, "cod_mun": cod, "motivo": "chave nula"})
            continue
            
        chaves_vistas.append(chave)
        
        # 6. Converter para 7 dígitos
        if chave not in municipios_dict:
            descartes.append({"ano": ano, "uf": uf, "cod_mun": cod, "motivo": "fora da DTB"})
            continue
            
        cod_7 = municipios_dict[chave]
        
        linha = {
            "cod_municipio": cod_7,
            "ano": ano,
            "fonte": "finbra",
        }
        
        # 7. Converter as colunas monetárias
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
        
    # 5. Chave repetida no ano
    contagem_chaves = Counter(chaves_vistas)
    repetidas = [k for k, v in contagem_chaves.items() if v > 1]
    if repetidas:
        raise ValueError(f"Chaves repetidas: {repetidas}")
        
    # 8. Montar esquema e ordenar
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
