"""Cliente da API de agregados do IBGE (SIDRA), compartilhado pelas tabelas municipais.

Uma chamada por tabela e ano, com todos os municípios (`N6[all]`): cada consulta nacional leva cerca de
um minuto, e pedidos acima de cerca de 50 mil valores falham (HTTP 500), então não se junta mais de um ano.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import polars as pl

from ..nucleo import Requisicao, RespostaInvalida, baixar_lote, ler_bruto

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# Marcadores do SIDRA no lugar do valor: zero absoluto, indisponível, não se aplica e sigilo.
ZERO_ABSOLUTO = "-"
MARCADORES_SEM_VALOR = ("...", "..", "X")


def requisicao_ano(tabela: int, ano: int, variaveis: Sequence[int]) -> Requisicao:
    ids = "|".join(str(v) for v in variaveis)
    return Requisicao(
        chave=f"t{tabela}/{ano}",
        url=f"{BASE}/{tabela}/periodos/{ano}/variaveis/{ids}?localidades=N6[all]",
        arquivo=f"t{tabela}/t{tabela}_{ano}.json.gz",
    )


def requisicao_metadados(tabela: int) -> Requisicao:
    return Requisicao(
        chave=f"t{tabela}/metadados",
        url=f"{BASE}/{tabela}/metadados",
        arquivo=f"t{tabela}/t{tabela}_metadados.json.gz",
    )


def validar_valores(conteudo: bytes, minimo_municipios: int = 5000) -> None:
    """Recusa respostas que não tragam a lista de variáveis com séries municipais."""
    try:
        blocos = json.loads(conteudo)
    except ValueError as erro:
        raise RespostaInvalida(f"resposta não é JSON: {conteudo[:80]!r}") from erro
    if not isinstance(blocos, list) or not blocos:
        raise RespostaInvalida(f"resposta sem variáveis: {conteudo[:80]!r}")
    for bloco in blocos:
        series = bloco["resultados"][0]["series"]
        if len(series) < minimo_municipios:
            raise RespostaInvalida(f"variável {bloco['id']} com {len(series)} municípios")


def baixar_tabela(tabela: int, anos: Sequence[int], variaveis: Sequence[int], pasta: Path, **opcoes) -> list[dict]:
    """Baixa os metadados da tabela e uma resposta por ano para dentro de `pasta` (a pasta do SIDRA)."""
    metadados = baixar_lote([requisicao_metadados(tabela)], pasta, **opcoes)
    requisicoes = [requisicao_ano(tabela, ano, variaveis) for ano in anos]
    return metadados + baixar_lote(requisicoes, pasta, validar=validar_valores, **opcoes)


def ler_tabela(pasta: Path, tabela: int, anos: Sequence[int]) -> pl.DataFrame:
    """Lê os brutos de uma tabela em formato longo: município, ano, variável e o valor como veio (texto)."""
    linhas = []
    for ano in anos:
        blocos = json.loads(ler_bruto(pasta, requisicao_ano(tabela, ano, ()).arquivo))
        for bloco in blocos:
            variavel = int(bloco["id"])
            for serie in bloco["resultados"][0]["series"]:
                municipio = serie["localidade"]["id"]
                for periodo, valor in serie["serie"].items():
                    linhas.append((municipio, int(periodo), variavel, valor))
    return pl.DataFrame(
        linhas,
        schema={"cod_municipio": pl.String, "ano": pl.Int16, "variavel": pl.Int32, "valor_bruto": pl.String},
        orient="row",
    )


def para_painel(longo: pl.DataFrame, colunas: Mapping[int, tuple[str, pl.DataType]]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Converte o formato longo em painel (uma linha por município e ano) e separa os marcadores.

    `colunas` associa o id de cada variável ao nome e ao tipo da coluna. O zero absoluto (`-`) vira 0;
    indisponível (`...`), não se aplica (`..`) e sigilo (`X`) viram nulo no painel e são devolvidos na
    segunda tabela, uma linha por célula, para que a razão do nulo não se perca.
    """
    nomes = pl.DataFrame(
        {"variavel": list(colunas), "coluna": [nome for nome, _ in colunas.values()]},
        schema={"variavel": pl.Int32, "coluna": pl.String},
    )
    longo = longo.join(nomes, on="variavel", how="inner")
    sem_valor = pl.col("valor_bruto").is_in(MARCADORES_SEM_VALOR)
    marcadores = (
        longo.filter(sem_valor)
        .select("cod_municipio", "ano", "coluna", pl.col("valor_bruto").alias("marcador"))
        .sort("cod_municipio", "ano", "coluna")
    )
    numerico = (
        pl.when(sem_valor)
        .then(None)
        .when(pl.col("valor_bruto") == ZERO_ABSOLUTO)
        .then(pl.lit("0"))
        .otherwise(pl.col("valor_bruto"))
        .cast(pl.Float64)
    )
    painel = (
        longo.with_columns(numerico.alias("valor"))
        .pivot(on="coluna", index=["cod_municipio", "ano"], values="valor")
        .select("cod_municipio", "ano", *[pl.col(nome).cast(tipo) for nome, tipo in colunas.values()])
        .sort("cod_municipio", "ano")
    )
    return painel, marcadores
