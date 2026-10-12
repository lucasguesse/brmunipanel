"""Harmonization of health tabulations from TabNet (DATASUS) at the municipal level.

Generates the municipal health panel (2006–2023) by consolidating nine indicators:
- CNES: inpatient beds, ICU beds, diagnostic imaging
  equipment (entire group), physicians, primary care units, and health posts;
- SIM: deaths from assault (CID-10 X85–Y09) and infant deaths;
- Sinasc: live births.

SUS beds (general hospitalization subset), COVID-19
ICU beds (2020-2022 only), and the CBO version returned alongside physicians
(which repeats the year) are not included in the panel. COVID-19 beds are not added to
ICU beds. Physician counts switch classification between 2007 (CBO 1994)
and 2008 (CBO 2002).
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from .. import nucleo
from . import tabnet

ANOS_PAINEL: tuple[int, ...] = tuple(range(2006, 2024))

COLUNAS_PAINEL: tuple[str, ...] = (
    "cod_municipio",
    "ano",
    "leitos_internacao",
    "leitos_uti",
    "equipamentos_imagem",
    "medicos",
    "unidades_basicas",
    "postos_saude",
    "obitos_agressao",
    "obitos_infantis",
    "nascidos_vivos",
)


def _converter_valor(valor: str) -> int:
    """Converts TabNet value string to integer (dash '-' becomes 0)."""
    v = valor.strip()
    if not v or v == "-":
        return 0
    return int(v)


def _processar_linhas_tabulacao(
    linhas: list[list[str]],
    indices_colunas: dict[str, list[int]],
    mapa_6_para_7: dict[str, str],
) -> dict[str, dict[str, int]]:
    """Extracts and aggregates values by 7-digit municipality from the rows of a tabulation."""
    valores_por_mun: dict[str, dict[str, int]] = {}

    for row in linhas:
        rotulo = row[0].strip()
        if rotulo.lower() == "total":
            continue

        m = re.match(r"^(\d{6})(?:\s+(.*))?$", rotulo)
        if not m:
            # Discard row without a 6-digit code at the beginning (e.g. 'MUNICIPIO IGNORADO - RJ')
            continue

        cod6 = m.group(1)
        # Any code starting with 53 is summed into 530010 (Brasília / DF)
        if cod6.startswith("53"):
            cod6 = "530010"

        cod7 = mapa_6_para_7.get(cod6)
        if not cod7:
            # TabNet code without a match in DTB is discarded
            continue

        if cod7 not in valores_por_mun:
            valores_por_mun[cod7] = {campo: 0 for campo in indices_colunas}

        for campo, idxs in indices_colunas.items():
            soma_campo = sum(_converter_valor(row[idx]) for idx in idxs)
            valores_por_mun[cod7][campo] += soma_campo

    return valores_por_mun


def _extrair_leitos_internacao(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"cnes_leitos_internacao/cnes_leitos_internacao_{ano:04d}07.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    for obrigatoria in ("Quantidade existente",):
        if obrigatoria not in cabecalho:
            raise ValueError(f"Coluna obrigatória '{obrigatoria}' ausente em cnes_leitos_internacao/{ano:04d}07")

    indices = {
        "leitos_internacao": [cabecalho.index("Quantidade existente")],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_leitos_complementares(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"cnes_leitos_complementares/cnes_leitos_complementares_{ano:04d}07.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    idxs_uti = [i for i, c in enumerate(cabecalho) if c.startswith("UTI") and "COVID" not in c]

    indices = {
        "leitos_uti": idxs_uti,
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_equipamentos(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"cnes_equipamentos_grupo/cnes_equipamentos_grupo_{ano:04d}07.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    obrigatoria = "Equipamentos de Diagnostico por Imagem"
    if obrigatoria not in cabecalho:
        raise ValueError(f"Coluna obrigatória '{obrigatoria}' ausente em cnes_equipamentos_grupo/{ano:04d}07")

    indices = {
        "equipamentos_imagem": [cabecalho.index(obrigatoria)],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_medicos(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    if ano in (2006, 2007):
        tab_nome = "cnes_medicos_cbo1994"
    else:
        tab_nome = "cnes_medicos_cbo2002"

    arquivo = f"{tab_nome}/{tab_nome}_{ano:04d}07.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    if "Total" not in cabecalho:
        raise ValueError(f"Coluna obrigatória 'Total' ausente em {tab_nome}/{ano:04d}07")

    indices = {
        "medicos": [cabecalho.index("Total")],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_estabelecimentos(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"cnes_estabelecimentos/cnes_estabelecimentos_{ano:04d}07.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    for obrigatoria in ("CENTRO DE SAUDE/UNIDADE BASICA", "POSTO DE SAUDE"):
        if obrigatoria not in cabecalho:
            raise ValueError(f"Coluna obrigatória '{obrigatoria}' ausente em cnes_estabelecimentos/{ano:04d}07")

    indices = {
        "unidades_basicas": [cabecalho.index("CENTRO DE SAUDE/UNIDADE BASICA")],
        "postos_saude": [cabecalho.index("POSTO DE SAUDE")],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_obitos_agressao(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"sim_obitos_agressao/sim_obitos_agressao_{ano:04d}.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    if "Óbitos p/Residênc" not in cabecalho:
        raise ValueError(f"Coluna obrigatória 'Óbitos p/Residênc' ausente em sim_obitos_agressao/{ano:04d}")

    indices = {
        "obitos_agressao": [cabecalho.index("Óbitos p/Residênc")],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_obitos_infantis(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"sim_obitos_infantis/sim_obitos_infantis_{ano:04d}.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    if "Óbitos p/Residênc" not in cabecalho:
        raise ValueError(f"Coluna obrigatória 'Óbitos p/Residênc' ausente em sim_obitos_infantis/{ano:04d}")

    indices = {
        "obitos_infantis": [cabecalho.index("Óbitos p/Residênc")],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def _extrair_nascidos_vivos(pasta_tabnet: Path, ano: int, mapa_6_para_7: dict[str, str]) -> dict[str, dict[str, int]]:
    arquivo = f"sinasc_nascidos_vivos/sinasc_nascidos_vivos_{ano:04d}.html.gz"
    conteudo = nucleo.ler_bruto(pasta_tabnet, arquivo)
    cabecalho, linhas = tabnet.extrair_tabela(conteudo)

    if "Nascim p/resid.mãe" not in cabecalho:
        raise ValueError(f"Coluna obrigatória 'Nascim p/resid.mãe' ausente em sinasc_nascidos_vivos/{ano:04d}")

    indices = {
        "nascidos_vivos": [cabecalho.index("Nascim p/resid.mãe")],
    }
    return _processar_linhas_tabulacao(linhas, indices, mapa_6_para_7)


def harmonizar(
    pasta_tabnet: Path,
    municipios: pl.DataFrame,
    populacao: pl.DataFrame,
    *,
    anos: tuple[int, ...] = ANOS_PAINEL,
) -> pl.DataFrame:
    """Harmonizes TabNet tabulations for the municipal panel.

    Args:
        pasta_tabnet: Directory containing raw files downloaded from TabNet.
        municipios: DTB municipalities DataFrame with `cod_municipio` and `cod_municipio_6`.
        populacao: Population DataFrame with `cod_municipio`, `ano`, and `populacao`.
        anos: Tuple of years to process (default: 2006 to 2023).

    Returns:
        Polars DataFrame with 1 row per municipality and year, sorted by `cod_municipio` and `ano`.
    """
    pasta_tabnet = Path(pasta_tabnet)
    mapa_6_para_7 = dict(zip(municipios["cod_municipio_6"].to_list(), municipios["cod_municipio"].to_list()))
    todos_municipios = sorted(municipios["cod_municipio"].unique().to_list())

    # Pairs (cod_municipio, ano) that have a valid population record
    pares_com_populacao = set(
        zip(
            populacao.filter(pl.col("populacao").is_not_null())["cod_municipio"].to_list(),
            populacao.filter(pl.col("populacao").is_not_null())["ano"].to_list(),
        )
    )

    linhas_painel: list[dict] = []

    for ano in sorted(anos):
        dados_leitos = _extrair_leitos_internacao(pasta_tabnet, ano, mapa_6_para_7)
        dados_complementares = _extrair_leitos_complementares(pasta_tabnet, ano, mapa_6_para_7)
        dados_equipamentos = _extrair_equipamentos(pasta_tabnet, ano, mapa_6_para_7)
        dados_medicos = _extrair_medicos(pasta_tabnet, ano, mapa_6_para_7)
        dados_estabelecimentos = _extrair_estabelecimentos(pasta_tabnet, ano, mapa_6_para_7)
        dados_agressao = _extrair_obitos_agressao(pasta_tabnet, ano, mapa_6_para_7)
        dados_infantis = _extrair_obitos_infantis(pasta_tabnet, ano, mapa_6_para_7)
        dados_nascidos = _extrair_nascidos_vivos(pasta_tabnet, ano, mapa_6_para_7)

        for cod7 in todos_municipios:
            tem_populacao = (cod7, ano) in pares_com_populacao

            if not tem_populacao:
                # Years in which the municipality has no population remain null in all columns
                linhas_painel.append({
                    "cod_municipio": cod7,
                    "ano": ano,
                    "leitos_internacao": None,
                    "leitos_uti": None,
                    "equipamentos_imagem": None,
                    "medicos": None,
                    "unidades_basicas": None,
                    "postos_saude": None,
                    "obitos_agressao": None,
                    "obitos_infantis": None,
                    "nascidos_vivos": None,
                })
            else:
                # Municipality absent from the response receives zero
                m_lei = dados_leitos.get(cod7, {})
                m_comp = dados_complementares.get(cod7, {})
                m_equ = dados_equipamentos.get(cod7, {})
                m_med = dados_medicos.get(cod7, {})
                m_est = dados_estabelecimentos.get(cod7, {})
                m_agr = dados_agressao.get(cod7, {})
                m_inf = dados_infantis.get(cod7, {})
                m_nv = dados_nascidos.get(cod7, {})

                linhas_painel.append({
                    "cod_municipio": cod7,
                    "ano": ano,
                    "leitos_internacao": m_lei.get("leitos_internacao", 0),
                    "leitos_uti": m_comp.get("leitos_uti", 0),
                    "equipamentos_imagem": m_equ.get("equipamentos_imagem", 0),
                    "medicos": m_med.get("medicos", 0),
                    "unidades_basicas": m_est.get("unidades_basicas", 0),
                    "postos_saude": m_est.get("postos_saude", 0),
                    "obitos_agressao": m_agr.get("obitos_agressao", 0),
                    "obitos_infantis": m_inf.get("obitos_infantis", 0),
                    "nascidos_vivos": m_nv.get("nascidos_vivos", 0),
                })

    return pl.DataFrame(
        linhas_painel,
        schema_overrides={
            "cod_municipio": pl.String,
            "ano": pl.Int16,
            "leitos_internacao": pl.Int64,
            "leitos_uti": pl.Int64,
            "equipamentos_imagem": pl.Int64,
            "medicos": pl.Int64,
            "unidades_basicas": pl.Int64,
            "postos_saude": pl.Int64,
            "obitos_agressao": pl.Int64,
            "obitos_infantis": pl.Int64,
            "nascidos_vivos": pl.Int64,
        },
    ).sort("cod_municipio", "ano")
