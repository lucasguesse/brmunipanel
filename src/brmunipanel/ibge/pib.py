"""Produto Interno Bruto dos Municípios (SIDRA, Tabela 5938, referência 2010), em mil reais correntes.

Apenas o PIB é harmonizado, porque a fonte não divulga o valor adicionado bruto nem os impostos de 2022 e 2023. A tabela não gera marcadores.
O município tem pib nulo nos anos anteriores à sua instalação. O bruto continua trazendo
as sete variáveis da tabela.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import sidra

TABELA = 5938
ANOS = tuple(range(2006, 2024))
VARIAVEIS_DOWNLOAD = [37, 543, 498, 513, 517, 6575, 525]
COLUNAS = {
    37: ("pib", pl.Float64),
}


def baixar(pasta_sidra: Path, **opcoes) -> list[dict]:
    return sidra.baixar_tabela(TABELA, ANOS, VARIAVEIS_DOWNLOAD, pasta_sidra, **opcoes)


def harmonizar(pasta_sidra: Path) -> pl.DataFrame:
    """Painel 2006–2023 (uma linha por município e ano)."""
    painel, _ = sidra.para_painel(sidra.ler_tabela(pasta_sidra, TABELA, ANOS), COLUNAS)
    return painel
