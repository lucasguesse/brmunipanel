"""Regiões e macrorregiões de saúde por município (API de Dados Abertos do Ministério da Saúde).

Endpoint: https://apidadosabertos.saude.gov.br/macrorregiao-e-regiao-de-saude/municipio
Os códigos de município chegam com 6 dígitos e são convertidos para os 7 dígitos da DTB.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import polars as pl
import requests

from .. import nucleo
from ..nucleo import Requisicao, RespostaInvalida

URL_BASE = "https://apidadosabertos.saude.gov.br/macrorregiao-e-regiao-de-saude/municipio"
CHAVE_RESPOSTA = "macrorregiao_regiao_saude_municipios"
LIMITE_PAGINA = 1000


def validar(conteudo: bytes) -> None:
    """Valida se o conteúdo é um JSON com o formato esperado da API de regiões de saúde."""
    try:
        dados = json.loads(conteudo)
        if not isinstance(dados, dict):
            raise RespostaInvalida("Resposta não é um objeto JSON")
        itens = dados.get(CHAVE_RESPOSTA)
        if not isinstance(itens, list):
            raise RespostaInvalida(f"Chave '{CHAVE_RESPOSTA}' ausente ou não é uma lista")
    except (json.JSONDecodeError, RespostaInvalida) as erro:
        raise RespostaInvalida(f"Conteúdo inválido da API de regiões de saúde: {erro}") from erro


def baixar(pasta: Path, **opcoes) -> list[dict]:
    """Baixa todas as páginas da API de regiões de saúde avançando o offset pelo total de itens recebidos."""
    pasta = Path(pasta)
    offset = 0
    registros = []
    sessao = opcoes.pop("sessao", None) or requests.Session()
    intervalo = opcoes.pop("intervalo", 1.0)

    while True:
        chave = f"offset{offset:04d}"
        arquivo = f"regioes_saude_offset{offset:04d}.json.gz"
        url = f"{URL_BASE}?limit={LIMITE_PAGINA}&offset={offset}"
        req = Requisicao(chave=chave, url=url, arquivo=arquivo, compactar=True)

        registro, baixou = nucleo.baixar(req, pasta, sessao=sessao, validar=validar, **opcoes)
        registros.append(registro)
        if baixou and intervalo:
            time.sleep(intervalo)

        conteudo = nucleo.ler_bruto(pasta, req.arquivo)
        dados = json.loads(conteudo)
        itens = dados.get(CHAVE_RESPOSTA, [])
        if not itens:
            break
        offset += len(itens)

    return registros


def processar_itens(
    itens: list[dict[str, Any]],
    municipios: pl.DataFrame,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Converte os itens da API para tabela harmonizada usando `cod_municipio_6` de `municipios`.

    Retorna o DataFrame harmonizado e a lista de itens descartados por falta de correspondência na DTB.
    Levanta ValueError se houver código de município repetido entre os itens recebidos.
    """
    vistos: set[str] = set()
    repetidos: set[str] = set()
    for item in itens:
        cod_6 = str(item.get("codigo_municipio", "")).strip()
        if not cod_6:
            continue
        if cod_6 in vistos:
            repetidos.add(cod_6)
        vistos.add(cod_6)

    if repetidos:
        raise ValueError(
            f"Códigos de município repetidos encontrados na paginação da API ({len(repetidos)}): {sorted(repetidos)}"
        )

    crosswalk = dict(zip(municipios["cod_municipio_6"].to_list(), municipios["cod_municipio"].to_list()))

    linhas = []
    descartados = []
    for item in itens:
        cod_6 = str(item.get("codigo_municipio", "")).strip()
        cod_7 = crosswalk.get(cod_6)
        if cod_7 is None:
            descartados.append(item)
            continue

        linhas.append({
            "cod_municipio": cod_7,
            "cod_regiao_saude": str(item.get("codigo_regiao_saude", "")).strip(),
            "nome_regiao_saude": str(item.get("regiao_saude", "")).strip(),
            "cod_macrorregiao_saude": str(item.get("codigo_macrorregiao_saude", "")).strip(),
            "nome_macrorregiao_saude": str(item.get("macrorregiao_saude", "")).strip(),
        })

    if not linhas:
        df = pl.DataFrame(
            schema={
                "cod_municipio": pl.String,
                "cod_regiao_saude": pl.String,
                "nome_regiao_saude": pl.String,
                "cod_macrorregiao_saude": pl.String,
                "nome_macrorregiao_saude": pl.String,
            }
        )
    else:
        df = pl.DataFrame(linhas, schema_overrides={
            "cod_municipio": pl.String,
            "cod_regiao_saude": pl.String,
            "nome_regiao_saude": pl.String,
            "cod_macrorregiao_saude": pl.String,
            "nome_macrorregiao_saude": pl.String,
        }).sort("cod_municipio")

    return df, descartados


def harmonizar(pasta: Path, municipios: pl.DataFrame) -> pl.DataFrame:
    """Lê os arquivos baixados em `pasta`, extrai todos os registros e harmoniza contra `municipios`."""
    pasta = Path(pasta)
    manifesto = nucleo.ler_manifesto(pasta)

    arquivos: list[str] = []
    if manifesto:
        for chave in sorted(manifesto.keys()):
            arquivos.append(manifesto[chave]["arquivo"])
    else:
        arquivos = sorted(p.name for p in pasta.glob("regioes_saude_offset*.json.gz"))

    todos_itens: list[dict[str, Any]] = []
    for arquivo in arquivos:
        conteudo = nucleo.ler_bruto(pasta, arquivo)
        dados = json.loads(conteudo)
        todos_itens.extend(dados.get(CHAVE_RESPOSTA, []))

    df, descartados = processar_itens(todos_itens, municipios)
    if descartados:
        print(f"Aviso: {len(descartados)} registros da API sem correspondência na DTB descartados.")
    return df
