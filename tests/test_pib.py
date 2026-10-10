"""Testes do módulo do Produto Interno Bruto (br_municipios_panel.ibge.pib)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from br_municipios_panel.ibge import pib
from br_municipios_panel.ibge import sidra


@pytest.fixture
def amostra_5938_2022_bytes() -> bytes:
    caminho = Path(__file__).resolve().parent / "dados" / "sidra_t5938_2022_amostra.json"
    return caminho.read_bytes()


def test_harmonizar(tmp_path: Path, amostra_5938_2022_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    pasta_tabela = tmp_path / "t5938"
    pasta_tabela.mkdir(parents=True, exist_ok=True)
    (pasta_tabela / "t5938_2022.json.gz").write_bytes(gzip.compress(amostra_5938_2022_bytes, mtime=0))
    monkeypatch.setattr(pib, "ANOS", [2022])

    painel = pib.harmonizar(tmp_path)

    assert isinstance(painel, pl.DataFrame)
    assert painel.columns == ["cod_municipio", "ano", "pib"]
    assert painel.schema == {
        "cod_municipio": pl.String,
        "ano": pl.Int16,
        "pib": pl.Float64,
    }
    # PIB na amostra de 2022 não deve ser nulo
    assert painel["pib"].null_count() == 0


def test_harmonizar_com_marcador_nulo(tmp_path: Path, amostra_5938_2022_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    pasta_tabela = tmp_path / "t5938"
    pasta_tabela.mkdir(parents=True, exist_ok=True)
    
    (pasta_tabela / "t5938_2022.json.gz").write_bytes(gzip.compress(amostra_5938_2022_bytes, mtime=0))
    monkeypatch.setattr(pib, "ANOS", [2022])
    len_normal = len(pib.harmonizar(tmp_path))
    
    dados = json.loads(amostra_5938_2022_bytes)
    cod_municipio_alterado = None
    # Procurar a variavel 37 e setar "..." na serie 2022
    for variavel_obj in dados:
        if variavel_obj["id"] == "37":
            serie = variavel_obj["resultados"][0]["series"][0]
            serie["serie"]["2022"] = "..."
            cod_municipio_alterado = serie["localidade"]["id"]
    
    (pasta_tabela / "t5938_2022.json.gz").write_bytes(gzip.compress(json.dumps(dados).encode("utf-8"), mtime=0))

    painel = pib.harmonizar(tmp_path)
    
    assert len(painel) == len_normal
    assert painel.filter(pl.col("cod_municipio") == cod_municipio_alterado)["pib"].item() is None


def test_variaveis_download() -> None:
    # A requisição deve conter exatamente a string de variáveis esperada para não quebrar 
    # o manifesto e baixar tudo de novo.
    req = sidra.requisicao_ano(pib.TABELA, 2022, pib.VARIAVEIS_DOWNLOAD)
    assert req.url.endswith("variaveis/37|543|498|513|517|6575|525?localidades=N6[all]")

