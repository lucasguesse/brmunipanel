"""Produto Interno Bruto dos Municípios (SIDRA, Table 5938, 2010 reference), in current thousand reais.

Only PIB is harmonized, because the source does not publish gross value added or taxes for 2022 and 2023. The table does not generate markers.
The municipality has null pib in the years prior to its installation. The raw data continues to bring
the seven variables of the table.
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
    """Panel 2006–2023 (one row per municipality and year)."""
    painel, _ = sidra.para_painel(sidra.ler_tabela(pasta_sidra, TABELA, ANOS), COLUNAS)
    return painel
