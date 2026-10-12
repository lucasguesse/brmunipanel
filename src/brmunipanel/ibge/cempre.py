"""Cadastro Central de Empresas (CEMPRE), local units concept, totals by municipality.

Table 1685 in 2006–2021 and Table 9509 in 2022–2023. The panel maintains five harmonized variables.
Three variables remain only in the raw data: active enterprises, average monthly salary in minimum wages, and
average monthly salary in reais (calculated as salarios_mil_reais * 1000 / pessoal_assalariado_medio / 13).
The source table for each period is 1685 until 2021, and 9509 in 2022 and 2023. IBGE reports a series
break in 2022 (Nota técnica 01/2024), which the dataset does not treat or mark in a column. A null value means
a municipality that did not yet exist or a value omitted by IBGE due to confidentiality.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import sidra

ANOS_POR_TABELA = {1685: tuple(range(2006, 2022)), 9509: (2022, 2023)}
VARIAVEIS_DOWNLOAD = [706, 367, 707, 708, 5944, 662, 1606, 10143]
COLUNAS = {
    706: ("unidades_locais", pl.Int64),
    707: ("pessoal_ocupado_total", pl.Int64),
    708: ("pessoal_ocupado_assalariado", pl.Int64),
    5944: ("pessoal_assalariado_medio", pl.Float64),
    662: ("salarios_mil_reais", pl.Float64),
}


def baixar(pasta_sidra: Path, **opcoes) -> list[dict]:
    registros = []
    for tabela, anos in ANOS_POR_TABELA.items():
        registros += sidra.baixar_tabela(tabela, anos, VARIAVEIS_DOWNLOAD, pasta_sidra, **opcoes)
    return registros


def harmonizar(pasta_sidra: Path) -> pl.DataFrame:
    """Panel sorted by cod_municipio and ano, with the five selected variables."""
    paineis = []
    for tabela, anos in ANOS_POR_TABELA.items():
        painel, _ = sidra.para_painel(sidra.ler_tabela(pasta_sidra, tabela, anos), COLUNAS)
        paineis.append(painel)
    return pl.concat(paineis).sort("cod_municipio", "ano")
