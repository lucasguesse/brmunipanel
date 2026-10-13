"""Tests for the IBGE/SIDRA CEMPRE module (brmunipanel.ibge.cempre)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ibge import cempre, sidra

PASTA_DADOS = Path(__file__).resolve().parent / "dados"


@pytest.fixture
def pasta_sidra_cempre(tmp_path: Path) -> Path:
    caminho_amostra = PASTA_DADOS / "sidra_cempre_amostra.json"
    amostras = json.loads(caminho_amostra.read_text(encoding="utf-8"))
    for chave, blocos in amostras.items():
        tabela, ano = chave.split("_")
        pasta_tab = tmp_path / f"t{tabela}"
        pasta_tab.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(blocos).encode("utf-8")
        (pasta_tab / f"t{tabela}_{ano}.json.gz").write_bytes(gzip.compress(conteudo, mtime=0))
    return tmp_path


def test_harmonizar_cempre_esquema(pasta_sidra_cempre: Path) -> None:
    painel = cempre.harmonizar(pasta_sidra_cempre)

    # 1. Expected schema: cod_municipio, ano, and the 5 harmonized columns
    esquema_esperado = {
        "cod_municipio": pl.String,
        "ano": pl.Int16,
        "unidades_locais": pl.Int64,
        "pessoal_ocupado_total": pl.Int64,
        "pessoal_ocupado_assalariado": pl.Int64,
        "pessoal_assalariado_medio": pl.Float64,
        "salarios_mil_reais": pl.Float64,
    }
    assert painel.schema == esquema_esperado

    # 2. Window strictly 2006–2023
    assert painel["ano"].min() == 2006
    assert painel["ano"].max() == 2023

    # 3. There are rows for years from both source tables (e.g. 2021 and 2022)
    assert 2021 in painel["ano"].unique().to_list()
    assert 2022 in painel["ano"].unique().to_list()

    # 4. Unique key and sorting
    dups = painel.group_by(["cod_municipio", "ano"]).agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    assert dups.height == 0
    assert painel.equals(painel.sort(["cod_municipio", "ano"]))


def test_requisicao_baixar_cempre() -> None:
    req_2021 = sidra.requisicao_ano(1685, 2021, cempre.VARIAVEIS_DOWNLOAD)
    assert req_2021.url.endswith("1685/periodos/2021/variaveis/706|367|707|708|5944|662|1606|10143?localidades=N6[all]")
    
    req_2022 = sidra.requisicao_ano(9509, 2022, cempre.VARIAVEIS_DOWNLOAD)
    assert req_2022.url.endswith("9509/periodos/2022/variaveis/706|367|707|708|5944|662|1606|10143?localidades=N6[all]")

