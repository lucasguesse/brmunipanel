"""Tests for the brmunipanel.ipea.pbf module."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ipea import pbf
from brmunipanel.nucleo import RespostaInvalida

PASTA_DADOS = Path(__file__).resolve().parent / "dados"


@pytest.fixture
def pasta_bruto_amostra(tmp_path: Path) -> Path:
    """Prepare a mock raw data folder with real samples compressed in gzip."""
    amostra_fam = PASTA_DADOS / "ipea_FAM_PBF_amostra.json"
    amostra_val = PASTA_DADOS / "ipea_VAL_PBF_amostra.json"

    conteudo_fam = amostra_fam.read_bytes()
    conteudo_val = amostra_val.read_bytes()

    (tmp_path / "FAM_PBF.json.gz").write_bytes(gzip.compress(conteudo_fam, mtime=0))
    (tmp_path / "VAL_PBF.json.gz").write_bytes(gzip.compress(conteudo_val, mtime=0))

    meta_val = json.dumps({"value": [{"SERCODIGO": "VAL_PBF", "UNINOME": "R$ (mil)"}]}).encode("utf-8")
    (tmp_path / "VAL_PBF_metadados.json.gz").write_bytes(gzip.compress(meta_val, mtime=0))

    return tmp_path


def test_harmonizar_amostra(pasta_bruto_amostra: Path) -> None:
    df = pbf.harmonizar(pasta_bruto_amostra)

    # 1. Expected schema and types
    assert df.schema == {
        "cod_municipio": pl.String,
        "ano": pl.Int16,
        "pbf_beneficios": pl.Int64,
        "pbf_valor_mil_reais": pl.Float64,
    }

    # 2. Window strictly 2006–2023
    assert df["ano"].min() >= 2006
    assert df["ano"].max() <= 2023

    # 3. Municipal rows only (7 digits, no state or Brazil code)
    codigos = df["cod_municipio"].unique().to_list()
    assert all(len(c) == 7 and c.isdigit() for c in codigos)
    assert "0" not in codigos
    assert "35" not in codigos
    assert "12" not in codigos

    # 4. Key (cod_municipio, ano) does not repeat
    duplicadas = df.group_by(["cod_municipio", "ano"]).agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    assert duplicadas.height == 0

    # 5. Municipality present only in FAM_PBF (1100015)
    linhas_1100015 = df.filter(pl.col("cod_municipio") == "1100015")
    assert linhas_1100015.height > 0
    assert linhas_1100015["pbf_beneficios"].is_not_null().all()
    assert linhas_1100015["pbf_valor_mil_reais"].is_null().all()

    # 6. Municipality created in 2013 (4212650) only enters the series from 2014 onwards
    linhas_4212650 = df.filter(pl.col("cod_municipio") == "4212650")
    assert linhas_4212650["ano"].min() == 2014
    assert linhas_4212650["ano"].max() == 2023

    # 7. No output column has 'razao' in its name
    assert not any("razao" in col for col in df.columns)


def test_validar_valores() -> None:
    # Valid: more than 100 thousand items
    conteudo_valido = json.dumps({"value": [1] * 100_001}).encode("utf-8")
    pbf.validar_valores(conteudo_valido)

    # Invalid: not JSON
    with pytest.raises(RespostaInvalida, match="não é JSON"):
        pbf.validar_valores(b"<html>erro</html>")

    # Invalid: without 'value'
    with pytest.raises(RespostaInvalida, match="sem a chave 'value'"):
        pbf.validar_valores(json.dumps({"dados": []}).encode("utf-8"))

    # Invalid: 100 thousand items or fewer
    with pytest.raises(RespostaInvalida, match="esperado > 100.000"):
        pbf.validar_valores(json.dumps({"value": [1] * 100_000}).encode("utf-8"))


def test_validar_metadados() -> None:
    # Valid: exactly 1 item
    conteudo_valido = json.dumps({"value": [{"SERCODIGO": "FAM_PBF"}]}).encode("utf-8")
    pbf.validar_metadados(conteudo_valido)

    # Invalid: empty
    with pytest.raises(RespostaInvalida, match="esperado exatamente 1"):
        pbf.validar_metadados(json.dumps({"value": []}).encode("utf-8"))

    # Invalid: more than 1 item
    with pytest.raises(RespostaInvalida, match="esperado exatamente 1"):
        pbf.validar_metadados(json.dumps({"value": [1, 2]}).encode("utf-8"))


def test_descarte_codigos_invalidos(tmp_path: Path) -> None:
    """Codes with invalid format (e.g. 6 digits or alphanumeric) must be discarded."""
    dados_fam = {
        "value": [
            {"NIVNOME": "Municípios", "TERCODIGO": "123456", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 10},
            {"NIVNOME": "Municípios", "TERCODIGO": "ABCDEFG", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 20},
            {"NIVNOME": "Municípios", "TERCODIGO": "3550308", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 30},
        ]
    }
    dados_val = {
        "value": [
            {"NIVNOME": "Municípios", "TERCODIGO": "3550308", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 150.0},
        ]
    }
    (tmp_path / "FAM_PBF.json.gz").write_bytes(gzip.compress(json.dumps(dados_fam).encode("utf-8"), mtime=0))
    (tmp_path / "VAL_PBF.json.gz").write_bytes(gzip.compress(json.dumps(dados_val).encode("utf-8"), mtime=0))

    df = pbf.harmonizar(tmp_path)
    assert df.height == 1
    assert df["cod_municipio"].to_list() == ["3550308"]
    assert df["pbf_beneficios"][0] == 30
    assert df["pbf_valor_mil_reais"][0] == 150.0


def test_conferir_unidade(tmp_path: Path) -> None:
    # File does not exist
    assert pbf.conferir_unidade(tmp_path) == ""

    # File exists
    meta = json.dumps({"value": [{"SERCODIGO": "VAL_PBF", "UNINOME": "R$ (mil)"}]}).encode("utf-8")
    (tmp_path / "VAL_PBF_metadados.json.gz").write_bytes(gzip.compress(meta, mtime=0))
    assert pbf.conferir_unidade(tmp_path) == "R$ (mil)"


def test_requisicoes() -> None:
    req_fam = pbf.requisicao_serie("FAM_PBF")
    assert req_fam.chave == "FAM_PBF"
    assert req_fam.arquivo == "FAM_PBF.json.gz"
    assert "FAM_PBF" in req_fam.url

    req_meta = pbf.requisicao_metadados("VAL_PBF")
    assert req_meta.chave == "VAL_PBF/metadados"
    assert req_meta.arquivo == "VAL_PBF_metadados.json.gz"
    assert "Metadados('VAL_PBF')" in req_meta.url
