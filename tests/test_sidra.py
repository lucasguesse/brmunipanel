"""Testes do cliente compartilhado do SIDRA (bra_municipalities_panel.ibge.sidra)."""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from bra_municipalities_panel.ibge import sidra
from bra_municipalities_panel.nucleo import RespostaInvalida

PASTA_DADOS = Path(__file__).resolve().parent / "dados"


@pytest.fixture
def amostra_5938_2022_bytes() -> bytes:
    caminho = PASTA_DADOS / "sidra_t5938_2022_amostra.json"
    return caminho.read_bytes()


@pytest.fixture
def amostra_1685_2012_bytes() -> bytes:
    caminho = PASTA_DADOS / "sidra_t1685_2012_amostra.json"
    return caminho.read_bytes()


def test_validar_valores(amostra_5938_2022_bytes: bytes) -> None:
    # 1. Aceita resposta real válida (com minimo_municipios correspondente à amostra)
    sidra.validar_valores(amostra_5938_2022_bytes, minimo_municipios=4)

    # 2. Recusa JSON inválido
    with pytest.raises(RespostaInvalida, match="resposta não é JSON"):
        sidra.validar_valores(b"<html>Erro no servidor</html>")

    # 3. Recusa lista vazia
    with pytest.raises(RespostaInvalida, match="resposta sem variáveis"):
        sidra.validar_valores(b"[]")

    # 4. Recusa resposta com menos municípios do que o mínimo configurado
    with pytest.raises(RespostaInvalida, match="com 4 municípios"):
        sidra.validar_valores(amostra_5938_2022_bytes, minimo_municipios=100)


def test_ler_tabela(tmp_path: Path, amostra_5938_2022_bytes: bytes) -> None:
    pasta_tabela = tmp_path / "t5938"
    pasta_tabela.mkdir(parents=True, exist_ok=True)
    (pasta_tabela / "t5938_2022.json.gz").write_bytes(gzip.compress(amostra_5938_2022_bytes, mtime=0))

    df_longo = sidra.ler_tabela(tmp_path, 5938, [2022])

    assert df_longo.schema == {
        "cod_municipio": pl.String,
        "ano": pl.Int16,
        "variavel": pl.Int32,
        "valor_bruto": pl.String,
    }
    assert df_longo.height == 7 * 4  # 7 variáveis x 4 municípios
    assert df_longo["ano"].unique().to_list() == [2022]
    assert df_longo["valor_bruto"].dtype == pl.String


def test_para_painel_converte_marcadores_e_traco(
    tmp_path: Path, amostra_1685_2012_bytes: bytes, amostra_5938_2022_bytes: bytes
) -> None:
    # Monta tabelas em tmp_path
    (tmp_path / "t1685").mkdir(parents=True, exist_ok=True)
    (tmp_path / "t1685" / "t1685_2012.json.gz").write_bytes(gzip.compress(amostra_1685_2012_bytes, mtime=0))

    df_longo_cempre = sidra.ler_tabela(tmp_path, 1685, [2012])
    colunas_cempre_teste = {
        706: ("unidades_locais", pl.Int64),
        367: ("empresas_atuantes", pl.Int64),
        707: ("pessoal_ocupado_total", pl.Int64),
        708: ("pessoal_ocupado_assalariado", pl.Int64),
        5944: ("pessoal_assalariado_medio", pl.Float64),
        662: ("salarios_mil_reais", pl.Float64),
        1606: ("salario_medio_mensal_sm", pl.Float64),
        10143: ("salario_medio_mensal_reais", pl.Float64),
    }
    painel_cempre, marcadores_cempre = sidra.para_painel(df_longo_cempre, colunas_cempre_teste)

    # 1. 4220000 tem '-' em pessoal_ocupado_assalariado (var 708) -> deve virar 0
    linha_4220000 = painel_cempre.filter(pl.col("cod_municipio") == "4220000")
    assert linha_4220000["pessoal_ocupado_assalariado"].item() == 0

    # 2. 4220000 tem 'X' em pessoal_assalariado_medio (var 5944) -> deve ser nulo no painel
    assert linha_4220000["pessoal_assalariado_medio"].item() is None

    # 3. Marcadores guardam 'X' na tabela de marcadores
    marcs_4220000 = marcadores_cempre.filter(pl.col("cod_municipio") == "4220000")
    assert "X" in marcs_4220000["marcador"].to_list()
    # '-' NÃO deve estar nos marcadores (porque é zero numérico)
    assert "-" not in marcadores_cempre["marcador"].to_list()

    # 4. Na tabela 5938 de 2022, impostos_liquidos e VAB são '...'
    (tmp_path / "t5938").mkdir(parents=True, exist_ok=True)
    (tmp_path / "t5938" / "t5938_2022.json.gz").write_bytes(gzip.compress(amostra_5938_2022_bytes, mtime=0))
    df_longo_pib = sidra.ler_tabela(tmp_path, 5938, [2022])
    colunas_pib_teste = {
        37: ("pib", pl.Float64),
        543: ("impostos_liquidos", pl.Float64),
        498: ("vab_total", pl.Float64),
        513: ("vab_agropecuaria", pl.Float64),
        517: ("vab_industria", pl.Float64),
        6575: ("vab_servicos", pl.Float64),
        525: ("vab_adm_publica", pl.Float64),
    }
    painel_pib, marcadores_pib = sidra.para_painel(df_longo_pib, colunas_pib_teste)

    # PIB tem valor numérico
    assert painel_pib["pib"].null_count() == 0
    # Impostos e VAB são nulos
    assert painel_pib["impostos_liquidos"].null_count() == 4
    assert painel_pib["vab_total"].null_count() == 4
    # Marcador '...' presente nos marcadores do PIB
    assert all(m == "..." for m in marcadores_pib["marcador"].to_list())
    assert marcadores_pib.height == 6 * 4  # 6 colunas sem valor x 4 municípios

    # 5. Teste sintético explícito de '..'
    df_dois_pontos = pl.DataFrame(
        {
            "cod_municipio": ["1100015"],
            "ano": [2020],
            "variavel": [37],
            "valor_bruto": [".."],
        },
        schema={"cod_municipio": pl.String, "ano": pl.Int16, "variavel": pl.Int32, "valor_bruto": pl.String},
    )
    p_dp, m_dp = sidra.para_painel(df_dois_pontos, {37: ("pib", pl.Float64)})
    assert p_dp["pib"].item() is None
    assert m_dp["marcador"].to_list() == [".."]
