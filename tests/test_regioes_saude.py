"""Testes do módulo br_municipios_panel.datasus.regioes_saude."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from br_municipios_panel import nucleo
from br_municipios_panel.datasus import regioes_saude
from br_municipios_panel.nucleo import RespostaInvalida

PASTA_DADOS = Path(__file__).resolve().parent / "dados"


class RespostaFalsa:
    def __init__(self, dados: dict):
        self.status_code = 200
        self.content = json.dumps(dados).encode("utf-8")

    def raise_for_status(self) -> None:
        pass


class SessaoFalsa:
    def __init__(self, paginas: list[list[dict[str, Any]]]):
        self.paginas = paginas
        self.chamadas = 0

    def get(self, url: str, headers: dict | None = None, timeout: float | None = None) -> RespostaFalsa:
        if self.chamadas >= len(self.paginas):
            raise RuntimeError(f"Chamada inesperada além do total de páginas ({self.chamadas})")
        dados = {"macrorregiao_regiao_saude_municipios": self.paginas[self.chamadas]}
        self.chamadas += 1
        return RespostaFalsa(dados)


def test_validar() -> None:
    # Válido
    conteudo_valido = json.dumps({"macrorregiao_regiao_saude_municipios": []}).encode("utf-8")
    regioes_saude.validar(conteudo_valido)

    # Inválido: não é JSON
    with pytest.raises(RespostaInvalida, match="não é um objeto JSON|Conteúdo inválido"):
        regioes_saude.validar(b"<html>404 Not Found</html>")

    # Inválido: chave ausente
    with pytest.raises(RespostaInvalida, match="não é uma lista"):
        regioes_saude.validar(json.dumps({"dados": []}).encode("utf-8"))


def test_processar_itens() -> None:
    caminho_amostra = PASTA_DADOS / "regioes_saude_amostra.json"
    dados = json.loads(caminho_amostra.read_text(encoding="utf-8"))
    itens = dados["macrorregiao_regiao_saude_municipios"]

    # Adicionar um item fictício com código sem correspondência na DTB (ex: 999999)
    itens_com_invalido = list(itens) + [
        {
            "codigo_municipio": "999999",
            "codigo_regiao_saude": "99999",
            "regiao_saude": "REGIAO INEXISTENTE",
            "codigo_macrorregiao_saude": "9901",
            "macrorregiao_saude": "MACRO INEXISTENTE",
        }
    ]

    # Municípios DTB simulados contendo apenas os 5 municípios válidos da amostra
    municipios = pl.DataFrame({
        "cod_municipio": ["1200013", "1200054", "1200104", "1200138", "1200179"],
        "cod_municipio_6": ["120001", "120005", "120010", "120013", "120017"],
    })

    df, descartados = regioes_saude.processar_itens(itens_com_invalido, municipios)

    # 1. Esquema e tipos
    assert df.schema == {
        "cod_municipio": pl.String,
        "cod_regiao_saude": pl.String,
        "nome_regiao_saude": pl.String,
        "cod_macrorregiao_saude": pl.String,
        "nome_macrorregiao_saude": pl.String,
    }

    # 2. Conversão de 6 para 7 dígitos e total de válidos
    assert df.height == 5
    assert set(df["cod_municipio"]) == {"1200013", "1200054", "1200104", "1200138", "1200179"}

    # 3. Código sem correspondência é descartado
    assert len(descartados) == 1
    assert descartados[0]["codigo_municipio"] == "999999"

    # 4. Ausência de chave primária duplicada
    assert df["cod_municipio"].n_unique() == df.height


def test_codigo_repetido_levanta_erro() -> None:
    itens_com_duplicata = [
        {"codigo_municipio": "120001", "codigo_regiao_saude": "12001", "regiao_saude": "R1", "codigo_macrorregiao_saude": "1201", "macrorregiao_saude": "M1"},
        {"codigo_municipio": "120001", "codigo_regiao_saude": "12002", "regiao_saude": "R2", "codigo_macrorregiao_saude": "1201", "macrorregiao_saude": "M1"},
    ]
    municipios = pl.DataFrame({"cod_municipio": ["1200013"], "cod_municipio_6": ["120001"]})
    with pytest.raises(ValueError, match="repetidos"):
        regioes_saude.processar_itens(itens_com_duplicata, municipios)


def test_paginacao_sessao_falsa(tmp_path: Path) -> None:
    p1 = [{"codigo_municipio": f"11000{i}"} for i in range(1, 4)]
    p2 = [{"codigo_municipio": f"11000{i}"} for i in range(4, 7)]
    p3 = [{"codigo_municipio": f"11000{i}"} for i in range(7, 9)]
    p4 = []

    sessao = SessaoFalsa([p1, p2, p3, p4])

    registros = regioes_saude.baixar(tmp_path, sessao=sessao, intervalo=0.0)

    # 4 requisições feitas na primeira execução
    assert sessao.chamadas == 4
    assert [r["arquivo"] for r in registros] == [
        "regioes_saude_offset0000.json.gz",
        "regioes_saude_offset0003.json.gz",
        "regioes_saude_offset0006.json.gz",
        "regioes_saude_offset0008.json.gz",
    ]

    manifesto = nucleo.ler_manifesto(tmp_path)
    assert sorted(manifesto.keys()) == ["offset0000", "offset0003", "offset0006", "offset0008"]

    # Segunda chamada sobre a mesma pasta não faz nenhuma requisição
    registros2 = regioes_saude.baixar(tmp_path, sessao=sessao, intervalo=0.0)
    assert sessao.chamadas == 4
    assert len(registros2) == 4
