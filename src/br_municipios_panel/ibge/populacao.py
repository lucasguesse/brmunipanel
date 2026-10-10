"""População residente estimada por município (SIDRA, Tabela 6579, variável 9324).

A tabela não tem valor em 2007, 2010, 2022 e 2023. Esses anos são completados por interpolação geométrica
(linear no logaritmo) entre as estimativas vizinhas, e a origem de cada valor fica em `pop_origem`.
A estimativa de 2024 é baixada só para interpolar 2022 e 2023 e não entra no painel.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import sidra

TABELA = 6579
VARIAVEL = 9324
ANOS_PAINEL = tuple(range(2006, 2024))
ANOS_SEM_ESTIMATIVA = (2007, 2010, 2022, 2023)
ANOS_DOWNLOAD = tuple(ano for ano in range(2006, 2025) if ano not in ANOS_SEM_ESTIMATIVA)


def baixar(pasta_sidra: Path, **opcoes) -> list[dict]:
    return sidra.baixar_tabela(TABELA, ANOS_DOWNLOAD, [VARIAVEL], pasta_sidra, **opcoes)


def interpolar(estimativas: pl.DataFrame, anos: tuple[int, ...] = ANOS_SEM_ESTIMATIVA) -> pl.DataFrame:
    """Interpola `populacao` nos anos pedidos, entre a estimativa anterior e a seguinte mais próximas.

    Um município só recebe valor interpolado quando tem estimativa nos dois anos vizinhos.
    """
    com_estimativa = sorted(estimativas["ano"].unique().to_list())
    partes = []
    for ano in anos:
        antes = max(a for a in com_estimativa if a < ano)
        depois = min(a for a in com_estimativa if a > ano)
        peso = (ano - antes) / (depois - antes)
        inicio = estimativas.filter(pl.col("ano") == antes).select("cod_municipio", pl.col("populacao").alias("p0"))
        fim = estimativas.filter(pl.col("ano") == depois).select("cod_municipio", pl.col("populacao").alias("p1"))
        log_pop = pl.col("p0").log() + peso * (pl.col("p1").log() - pl.col("p0").log())
        partes.append(
            inicio.join(fim, on="cod_municipio", how="inner")
            .filter((pl.col("p0") > 0) & (pl.col("p1") > 0))
            .select(
                "cod_municipio",
                pl.lit(ano, dtype=pl.Int16).alias("ano"),
                log_pop.exp().round().cast(pl.Int64).alias("populacao"),
            )
        )
    return pl.concat(partes)


def harmonizar(pasta_sidra: Path) -> pl.DataFrame:
    """Painel 2006–2023: `cod_municipio`, `ano`, `populacao` e `pop_origem` (`estimativa` ou `interpolado`)."""
    longo = sidra.ler_tabela(pasta_sidra, TABELA, ANOS_DOWNLOAD)
    estimativas, _ = sidra.para_painel(longo, {VARIAVEL: ("populacao", pl.Int64)})
    estimativas = estimativas.drop_nulls("populacao")
    painel = pl.concat(
        [
            estimativas.with_columns(pl.lit("estimativa").alias("pop_origem")),
            interpolar(estimativas).with_columns(pl.lit("interpolado").alias("pop_origem")),
        ]
    )
    return painel.filter(pl.col("ano").is_in(ANOS_PAINEL)).sort("cod_municipio", "ano")
