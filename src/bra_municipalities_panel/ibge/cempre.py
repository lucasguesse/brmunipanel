"""Cadastro Central de Empresas (CEMPRE), conceito de unidades locais, totais por município.

Tabela 1685 em 2006–2021 e Tabela 9509 em 2022–2023. O painel mantém cinco variáveis harmonizadas.
Três variáveis ficam apenas no bruto: empresas atuantes, salário médio mensal em salários mínimos e
salário médio mensal em reais (calculado como salarios_mil_reais * 1000 / pessoal_assalariado_medio / 13).
A tabela de origem de cada período é a 1685 até 2021, e a 9509 em 2022 e 2023. O IBGE declara quebra de
série em 2022 (Nota técnica 01/2024), que a base não trata nem marca em coluna. O valor nulo significa
município que ainda não existia ou valor omitido pelo IBGE por sigilo.
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
    """Painel ordenado por cod_municipio e ano, com as cinco variáveis selecionadas."""
    paineis = []
    for tabela, anos in ANOS_POR_TABELA.items():
        painel, _ = sidra.para_painel(sidra.ler_tabela(pasta_sidra, tabela, anos), COLUNAS)
        paineis.append(painel)
    return pl.concat(paineis).sort("cod_municipio", "ano")
