"""Estimated resident population by municipality (SIDRA, Table 6579, variable 9324).

The table has no values for 2007, 2010, 2022, and 2023. These years are completed by geometric interpolation
(linear in logarithms) between neighboring estimates, and the source of each value is recorded in `pop_origem`.
The 2024 estimate is downloaded only to interpolate 2022 and 2023 and is not included in the panel.
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
    """Interpolates `populacao` for the requested years, between the closest previous and next estimates.

    A municipality receives an interpolated value only when it has estimates in both neighboring years.
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
    """Panel 2006–2023: `cod_municipio`, `ano`, `populacao`, and `pop_origem` (`estimativa` or `interpolado`)."""
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
