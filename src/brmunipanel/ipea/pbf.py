"""Programa Bolsa Família (IPEA Data, OData4 API, series FAM_PBF and VAL_PBF).

Downloads annual December series at the municipal level and consolidates the 2006–2023 panel:
- FAM_PBF: number of benefits in December (Int64)
- VAL_PBF: total value of benefits in December in thousand R$ (Float64)

In 2013 and 2016 the source's municipal value is anomalous in part of the municipalities. It remains as received, without column flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from ..nucleo import Requisicao, RespostaInvalida, baixar_lote, ler_bruto

BASE = "https://www.ipeadata.gov.br/api/odata4"
SERIES = ("FAM_PBF", "VAL_PBF")
ANOS_PAINEL = tuple(range(2006, 2024))
UNIDADE_ESPERADA_VAL = "R$ (mil)"


def requisicao_serie(serie: str) -> Requisicao:
    return Requisicao(
        chave=serie,
        url=f"{BASE}/ValoresSerie(SERCODIGO='{serie}')",
        arquivo=f"{serie}.json.gz",
    )


def requisicao_metadados(serie: str) -> Requisicao:
    return Requisicao(
        chave=f"{serie}/metadados",
        url=f"{BASE}/Metadados('{serie}')",
        arquivo=f"{serie}_metadados.json.gz",
    )


def validar_valores(conteudo: bytes) -> None:
    """Rejects responses that are not JSON with the 'value' key containing more than 100 thousand items."""
    try:
        dados = json.loads(conteudo)
    except ValueError as erro:
        raise RespostaInvalida(f"resposta não é JSON: {conteudo[:80]!r}") from erro
    if not isinstance(dados, dict) or "value" not in dados:
        raise RespostaInvalida(f"resposta sem a chave 'value': {conteudo[:80]!r}")
    itens = dados["value"]
    if not isinstance(itens, list) or len(itens) <= 100_000:
        total = len(itens) if isinstance(itens, list) else type(itens)
        raise RespostaInvalida(f"resposta com {total} itens (esperado > 100.000)")


def validar_metadados(conteudo: bytes) -> None:
    """Rejects metadata responses that do not contain exactly 1 item in the 'value' key."""
    try:
        dados = json.loads(conteudo)
    except ValueError as erro:
        raise RespostaInvalida(f"resposta não é JSON: {conteudo[:80]!r}") from erro
    if not isinstance(dados, dict) or "value" not in dados:
        raise RespostaInvalida(f"resposta sem a chave 'value': {conteudo[:80]!r}")
    itens = dados["value"]
    if not isinstance(itens, list) or len(itens) != 1:
        total = len(itens) if isinstance(itens, list) else type(itens)
        raise RespostaInvalida(f"resposta com {total} itens em metadados (esperado exatamente 1)")


def baixar(pasta: Path, **opcoes) -> list[dict]:
    """Downloads FAM_PBF and VAL_PBF series and their metadata to pasta."""
    pasta = Path(pasta)
    reqs_meta = [requisicao_metadados(s) for s in SERIES]
    reqs_valores = [requisicao_serie(s) for s in SERIES]
    registros_meta = baixar_lote(reqs_meta, pasta, validar=validar_metadados, **opcoes)
    registros_valores = baixar_lote(reqs_valores, pasta, validar=validar_valores, **opcoes)
    return registros_meta + registros_valores


def _ler_serie_bruta(pasta: Path, serie: str) -> tuple[pl.DataFrame, list[str]]:
    """Reads the raw series from the folder, filtering only 'Municípios' level and extracting cod_municipio, ano, and valor."""
    conteudo = ler_bruto(pasta, f"{serie}.json.gz")
    dados = json.loads(conteudo)
    itens = dados.get("value", [])

    linhas: list[tuple[str, int, float | None]] = []
    codigos_invalidos: list[str] = []

    for it in itens:
        if it.get("NIVNOME") == "Municípios":
            tercodigo = str(it.get("TERCODIGO") or "").strip()
            if len(tercodigo) != 7 or not tercodigo.isdigit():
                codigos_invalidos.append(tercodigo)
                continue
            valdata = str(it.get("VALDATA") or "")
            if len(valdata) < 4:
                continue
            ano = int(valdata[:4])
            linhas.append((tercodigo, ano, it.get("VALVALOR")))

    df = pl.DataFrame(
        linhas,
        schema={"cod_municipio": pl.String, "ano": pl.Int16, "valor": pl.Float64},
        orient="row",
    )
    return df, codigos_invalidos


def conferir_unidade(pasta: Path) -> str:
    """Checks and returns the declared unit of measurement in VAL_PBF metadata."""
    caminho = Path(pasta) / "VAL_PBF_metadados.json.gz"
    if not caminho.exists():
        return ""
    meta = json.loads(ler_bruto(pasta, "VAL_PBF_metadados.json.gz"))
    itens = meta.get("value", [])
    if itens and isinstance(itens, list):
        return itens[0].get("UNINOME", "")
    return ""


def harmonizar(pasta: Path) -> pl.DataFrame:
    """Harmonizes FAM_PBF and VAL_PBF series for the 2006–2023 panel.

    Returns a pl.DataFrame sorted by cod_municipio and ano, with columns:
    - cod_municipio (String, 7 digits)
    - ano (Int16)
    - pbf_beneficios (Int64, number of benefits in December)
    - pbf_valor_mil_reais (Float64, total value in thousand R$ in December)
    """
    pasta = Path(pasta)
    unidade = conferir_unidade(pasta)
    if unidade and unidade != UNIDADE_ESPERADA_VAL:
        print(f"AVISO: Unidade de VAL_PBF é {unidade!r} (esperado: {UNIDADE_ESPERADA_VAL!r})")

    df_fam, invalidos_fam = _ler_serie_bruta(pasta, "FAM_PBF")
    df_val, invalidos_val = _ler_serie_bruta(pasta, "VAL_PBF")

    invalidos_total = invalidos_fam + invalidos_val
    if invalidos_total:
        print(f"AVISO: {len(invalidos_total)} códigos municipais não tinham 7 dígitos e foram descartados: {set(invalidos_total)}")

    df_fam = df_fam.select(
        "cod_municipio",
        "ano",
        pl.col("valor").round().cast(pl.Int64).alias("pbf_beneficios"),
    )
    df_val = df_val.select(
        "cod_municipio",
        "ano",
        pl.col("valor").cast(pl.Float64).alias("pbf_valor_mil_reais"),
    )

    painel = df_fam.join(df_val, on=["cod_municipio", "ano"], how="full", coalesce=True)

    return (
        painel.filter(pl.col("ano").is_in(ANOS_PAINEL))
        .select([
            "cod_municipio", "ano", "pbf_beneficios", "pbf_valor_mil_reais"
        ])
        .sort("cod_municipio", "ano")
    )
