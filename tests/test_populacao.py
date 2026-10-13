"""Tests for the IBGE/SIDRA population module (brmunipanel.ibge.populacao)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ibge import populacao

PASTA_DADOS = Path(__file__).resolve().parent / "dados"


def test_interpolar_manual() -> None:
    """Validate exact geometric interpolation calculation and discarding municipalities without neighbors."""
    estimativas = pl.DataFrame(
        [
            # Municipality A ("1100015"): has 2006 (100) and 2008 (121) -> 2007 must be 110
            #                             has 2021 (1000) and 2024 (1331) -> 2022=1100, 2023=1210
            ("1100015", 2006, 100),
            ("1100015", 2008, 121),
            ("1100015", 2009, 500),
            ("1100015", 2011, 500),
            ("1100015", 2021, 1000),
            ("1100015", 2024, 1331),
            # Municipality B ("1200328"): has 2006, but does NOT have 2008 -> must not receive 2007
            #                             has 2021, but does NOT have 2024 -> must not receive 2022 nor 2023
            ("1200328", 2006, 100),
            ("1200328", 2009, 500),
            ("1200328", 2011, 500),
            ("1200328", 2021, 1000),
            # Municipality C ("3550308"): does NOT have 2006, has 2008 -> must not receive 2007
            ("3550308", 2008, 121),
            ("3550308", 2009, 500),
            ("3550308", 2011, 500),
            ("3550308", 2024, 1331),
        ],
        schema={"cod_municipio": pl.String, "ano": pl.Int16, "populacao": pl.Int64},
        orient="row",
    )

    interpolados = populacao.interpolar(estimativas)

    # 1. Municipality A has 2007, 2010, 2022, and 2023
    res_a = interpolados.filter(pl.col("cod_municipio") == "1100015").sort("ano")
    assert res_a.filter(pl.col("ano") == 2007)["populacao"].item() == 110
    assert res_a.filter(pl.col("ano") == 2022)["populacao"].item() == 1100
    assert res_a.filter(pl.col("ano") == 2023)["populacao"].item() == 1210

    # 2. Municipalities B and C must not receive years missing a neighbor
    assert interpolados.filter((pl.col("cod_municipio") == "1200328") & (pl.col("ano") == 2007)).height == 0
    assert interpolados.filter((pl.col("cod_municipio") == "1200328") & (pl.col("ano") == 2022)).height == 0
    assert interpolados.filter((pl.col("cod_municipio") == "1200328") & (pl.col("ano") == 2023)).height == 0
    assert interpolados.filter((pl.col("cod_municipio") == "3550308") & (pl.col("ano") == 2007)).height == 0
    assert interpolados.filter((pl.col("cod_municipio") == "3550308") & (pl.col("ano") == 2022)).height == 0


@pytest.fixture
def pasta_sidra_populacao(tmp_path: Path) -> Path:
    pasta_tabela = tmp_path / "t6579"
    pasta_tabela.mkdir(parents=True, exist_ok=True)
    caminho_amostra = PASTA_DADOS / "sidra_t6579_amostra.json"
    amostras_por_ano = json.loads(caminho_amostra.read_text(encoding="utf-8"))
    for ano, blocos in amostras_por_ano.items():
        conteudo = json.dumps(blocos).encode("utf-8")
        (pasta_tabela / f"t6579_{ano}.json.gz").write_bytes(gzip.compress(conteudo, mtime=0))
    return tmp_path


def test_harmonizar_amostra(pasta_sidra_populacao: Path) -> None:
    df = populacao.harmonizar(pasta_sidra_populacao)

    # 1. Schema
    assert df.schema == {
        "cod_municipio": pl.String,
        "ano": pl.Int16,
        "populacao": pl.Int64,
        "pop_origem": pl.String,
    }

    # 2. Window strictly 2006–2023 (without 2024)
    assert df["ano"].min() == 2006
    assert df["ano"].max() == 2023
    assert 2024 not in df["ano"].unique().to_list()

    # 3. pop_origem is exactly 'interpolado' in 2007, 2010, 2022, and 2023, and 'estimativa' in the others
    anos_interpolados = {2007, 2010, 2022, 2023}
    for ano in range(2006, 2024):
        sub = df.filter(pl.col("ano") == ano)
        origens = sub["pop_origem"].unique().to_list()
        if ano in anos_interpolados:
            assert origens == ["interpolado"], f"Esperado apenas 'interpolado' para {ano}, obtido {origens}"
        else:
            assert origens == ["estimativa"], f"Esperado apenas 'estimativa' para {ano}, obtido {origens}"

    # 4. No key duplication
    dups = df.group_by(["cod_municipio", "ano"]).agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    assert dups.height == 0
