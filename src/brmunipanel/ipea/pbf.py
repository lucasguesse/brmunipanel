"""Programa Bolsa Família (IPEA Data, API OData4, séries FAM_PBF e VAL_PBF).

Baixa as séries anuais de dezembro em nível municipal e consolida o painel 2006–2023:
- FAM_PBF: número de benefícios em dezembro (Int64)
- VAL_PBF: valor total dos benefícios em dezembro em R$ mil (Float64)

Em 2013 e em 2016 o valor municipal da fonte é anômalo em parte dos municípios. Ele fica como veio, sem marca em coluna.
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
    """Recusa respostas que não sejam JSON com a chave 'value' contendo mais de 100 mil itens."""
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
    """Recusa respostas de metadados que não contenham exatamente 1 item na chave 'value'."""
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
    """Baixa as séries FAM_PBF e VAL_PBF e seus metadados para pasta."""
    pasta = Path(pasta)
    reqs_meta = [requisicao_metadados(s) for s in SERIES]
    reqs_valores = [requisicao_serie(s) for s in SERIES]
    registros_meta = baixar_lote(reqs_meta, pasta, validar=validar_metadados, **opcoes)
    registros_valores = baixar_lote(reqs_valores, pasta, validar=validar_valores, **opcoes)
    return registros_meta + registros_valores


def _ler_serie_bruta(pasta: Path, serie: str) -> tuple[pl.DataFrame, list[str]]:
    """Lê a série bruta da pasta, filtrando apenas nível 'Municípios' e extraindo cod_municipio, ano e valor."""
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
    """Verifica e retorna a unidade de medida declarada nos metadados de VAL_PBF."""
    caminho = Path(pasta) / "VAL_PBF_metadados.json.gz"
    if not caminho.exists():
        return ""
    meta = json.loads(ler_bruto(pasta, "VAL_PBF_metadados.json.gz"))
    itens = meta.get("value", [])
    if itens and isinstance(itens, list):
        return itens[0].get("UNINOME", "")
    return ""


def harmonizar(pasta: Path) -> pl.DataFrame:
    """Harmoniza as séries FAM_PBF e VAL_PBF para o painel 2006–2023.

    Devolve um pl.DataFrame ordenado por cod_municipio e ano, com as colunas:
    - cod_municipio (String, 7 dígitos)
    - ano (Int16)
    - pbf_beneficios (Int64, quantidade de benefícios em dezembro)
    - pbf_valor_mil_reais (Float64, valor total em R$ mil em dezembro)
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
