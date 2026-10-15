"""Tests for harmonization of health tabulations from TabNet (DATASUS)."""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.datasus import saude


def _criar_html(cabecalho: list[str], linhas: list[list[str]]) -> bytes:
    """Builds TabNet HTML inside <PRE> with semicolon separator in latin-1 compressed in gzip."""
    texto_linhas = [";".join(f'"{c}"' for c in cabecalho)]
    for r in linhas:
        texto_linhas.append(";".join(f'"{c}"' for c in r))
    html = f"<PRE>\n{chr(10).join(texto_linhas)}\n</PRE>"
    return gzip.compress(html.encode("latin-1"))


def _gravar_html(pasta: Path, subpasta: str, nome_arquivo: str, cabecalho: list[str], linhas: list[list[str]]) -> None:
    destino = pasta / subpasta / nome_arquivo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_criar_html(cabecalho, linhas))


def _montar_estrutura_padrao(pasta: Path, ano: int) -> None:
    """Create a minimal and valid structure for all tabulations of the year."""
    p_cnes = f"{ano:04d}07"
    p_sim = str(ano)

    # 1. Inpatient beds
    _gravar_html(
        pasta,
        "cnes_leitos_internacao",
        f"cnes_leitos_internacao_{p_cnes}.html.gz",
        ["Município", "Quantidade existente"],
        [
            ["110001 ALTA FLORESTA", "70"],
            ["Total", "70"],
        ],
    )

    # 2. Complementary beds (ICU)
    _gravar_html(
        pasta,
        "cnes_leitos_complementares",
        f"cnes_leitos_complementares_{p_cnes}.html.gz",
        ["Município", "UTI adulto II", "UTI neonatal", "Unidade intermediária", "UTI adulto II COVID-19", "Total"],
        [
            ["110001 ALTA FLORESTA", "10", "5", "8", "4", "27"],
            ["Total", "10", "5", "8", "4", "27"],
        ],
    )

    # 3. Physicians (CBO 1994 for <=2007, CBO 2002 for >=2008)
    tab_med = "cnes_medicos_cbo1994" if ano <= 2007 else "cnes_medicos_cbo2002"
    _gravar_html(
        pasta,
        tab_med,
        f"{tab_med}_{p_cnes}.html.gz",
        ["Município", "Clinico", "Pediatra", "Total"],
        [
            ["110001 ALTA FLORESTA", "10", "6", "16"],
            ["Total", "10", "6", "16"],
        ],
    )

    # 4. Establishments
    _gravar_html(
        pasta,
        "cnes_estabelecimentos",
        f"cnes_estabelecimentos_{p_cnes}.html.gz",
        ["Município", "CENTRO DE SAUDE/UNIDADE BASICA", "POSTO DE SAUDE", "Total"],
        [
            ["110001 ALTA FLORESTA", "3", "2", "5"],
            ["Total", "3", "2", "5"],
        ],
    )

    # 4.5 Equipment (Testing different column order)
    _gravar_html(
        pasta,
        "cnes_equipamentos_grupo",
        f"cnes_equipamentos_grupo_{p_cnes}.html.gz",
        ["Município", "Equipamentos de Infra-Estrutura", "Equipamentos de Diagnostico por Imagem", "Outros Equipamentos", "Total"],
        [
            ["110001 ALTA FLORESTA", "1", "10", "4", "15"],
            ["Total", "1", "10", "4", "15"],
        ],
    )

    # 5. Deaths from assault
    _gravar_html(
        pasta,
        "sim_obitos_agressao",
        f"sim_obitos_agressao_{p_sim}.html.gz",
        ["Município", "Óbitos p/Residênc"],
        [
            ["110001 ALTA FLORESTA", "6"],
            ["Total", "6"],
        ],
    )

    # 6. Infant deaths
    _gravar_html(
        pasta,
        "sim_obitos_infantis",
        f"sim_obitos_infantis_{p_sim}.html.gz",
        ["Município", "Óbitos p/Residênc"],
        [
            ["110001 ALTA FLORESTA", "8"],
            ["Total", "8"],
        ],
    )

    # 7. Live births
    _gravar_html(
        pasta,
        "sinasc_nascidos_vivos",
        f"sinasc_nascidos_vivos_{p_sim}.html.gz",
        ["Município", "Nascim p/resid.mãe"],
        [
            ["110001 ALTA FLORESTA", "476"],
            ["Total", "476"],
        ],
    )


@pytest.fixture
def df_municipios() -> pl.DataFrame:
    """Minimal table of DTB municipalities."""
    return pl.DataFrame({
        "cod_municipio": ["1100015", "1100023", "5300108"],
        "cod_municipio_6": ["110001", "110002", "530010"],
    })


@pytest.fixture
def df_populacao() -> pl.DataFrame:
    """Population table with mock Nazária/absent."""
    return pl.DataFrame({
        "cod_municipio": ["1100015", "1100015", "1100023", "5300108", "5300108"],
        "ano": [2007, 2008, 2007, 2007, 2008],
        "populacao": [25000, 24000, 80000, 2500000, 2600000],
    }, schema_overrides={"ano": pl.Int16, "populacao": pl.Int64})


def test_regras_harmonizacao_saude(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Test: ignored municipality discarded, '-' becomes 0, ICU aggregates and excludes COVID/intermed,

    53xxxx summed into Brasília, absent receives 0, without population becomes null, and correct CBO version.
    """
    ano = 2007
    p_cnes = f"{ano:04d}07"

    _montar_estrutura_padrao(tmp_path, ano)

    # Overwrite complementares to test:
    # - ICU sum includes UTI adulto II and UTI neonatal
    # - excludes Unidade intermediária
    # - separates UTI adulto II COVID-19
    # - dash '-' becomes zero
    # - ignored municipality row is discarded
    # - 53xxxx codes summed into Brasília (530010)
    _gravar_html(
        tmp_path,
        "cnes_leitos_complementares",
        f"cnes_leitos_complementares_{p_cnes}.html.gz",
        ["Município", "UTI adulto II", "UTI neonatal", "Unidade intermediária", "UTI adulto II COVID-19", "Total"],
        [
            ["110001 ALTA FLORESTA", "2", "3", "5", "4", "14"],
            ["530010 BRASILIA", "10", "-", "2", "-", "12"],
            ["539999 REGIAO ADM DF", "5", "2", "1", "1", "9"],  # Another 53 code
            ["MUNICIPIO IGNORADO - RO", "99", "99", "99", "99", "396"],  # Ignored
            ["Total", "116", "104", "107", "104", "431"],
        ],
    )

    painel = saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2007,))

    assert painel.shape == (3, 11)
    assert painel.columns == list(saude.COLUNAS_PAINEL)

    # 1. Municipality 1100015 (Alta Floresta):
    m11 = painel.filter(pl.col("cod_municipio") == "1100015").to_dicts()[0]
    assert m11["leitos_uti"] == 5  # 2 + 3 (excluded 5 intermediate and 4 COVID)
    assert m11["leitos_internacao"] == 70
    assert m11["equipamentos_imagem"] == 10

    # 2. Municipality 5300108 (Brasília):
    # Sum of 530010 (10 + 0 ICU) with 539999 (5 + 2 ICU)
    m53 = painel.filter(pl.col("cod_municipio") == "5300108").to_dicts()[0]
    assert m53["leitos_uti"] == 17  # 10 + 0 + 5 + 2
    # In tabulations where Brasília did not appear in the response, received 0
    assert m53["leitos_internacao"] == 0
    assert m53["obitos_agressao"] == 0

    # 3. Municipality 1100023 in 2007 has population, but did not appear in any tabulation -> receives 0
    m1102 = painel.filter(pl.col("cod_municipio") == "1100023").to_dicts()[0]
    assert m1102["leitos_internacao"] == 0
    assert m1102["leitos_uti"] == 0
    assert m1102["equipamentos_imagem"] == 0
    assert m1102["medicos"] == 0
    
    # 4. Assertion of removed columns
    assert "leitos_internacao_sus" not in painel.columns
    assert "leitos_uti_covid19" not in painel.columns
    assert "medicos_cbo" not in painel.columns


def test_municipio_sem_populacao_fica_nulo(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Municipality and year without population record has all columns null."""
    ano = 2008
    _montar_estrutura_padrao(tmp_path, ano)

    painel = saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2008,))

    # Municipality 1100023 does NOT have population in 2008 in df_populacao
    m1102 = painel.filter(pl.col("cod_municipio") == "1100023").to_dicts()[0]
    assert m1102["ano"] == 2008
    assert m1102["leitos_internacao"] is None
    assert m1102["leitos_uti"] is None
    assert m1102["equipamentos_imagem"] is None
    assert m1102["medicos"] is None
    assert m1102["unidades_basicas"] is None
    assert m1102["postos_saude"] is None
    assert m1102["obitos_agressao"] is None
    assert m1102["obitos_infantis"] is None
    assert m1102["nascidos_vivos"] is None


def test_medicos_tabulacoes_diferentes_por_ano(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Test that medicos uses cbo1994 tabulation in 2007 and cbo2002 in 2008."""
    _montar_estrutura_padrao(tmp_path, 2007)
    _montar_estrutura_padrao(tmp_path, 2008)

    # Overwrite medicos in 2008 with a different value
    _gravar_html(
        tmp_path,
        "cnes_medicos_cbo2002",
        "cnes_medicos_cbo2002_200807.html.gz",
        ["Município", "Clinico", "Pediatra", "Total"],
        [
            ["110001 ALTA FLORESTA", "10", "6", "25"],
            ["Total", "10", "6", "25"],
        ],
    )

    painel = saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2007, 2008))

    p2007 = painel.filter((pl.col("cod_municipio") == "1100015") & (pl.col("ano") == 2007)).to_dicts()[0]
    p2008 = painel.filter((pl.col("cod_municipio") == "1100015") & (pl.col("ano") == 2008)).to_dicts()[0]

    assert p2007["medicos"] == 16
    assert p2008["medicos"] == 25


def test_coluna_obrigatoria_ausente_levanta_erro(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Absence of required column ('Quantidade existente', 'POSTO DE SAUDE', etc.) raises ValueError."""
    _montar_estrutura_padrao(tmp_path, 2007)

    # Corrupt cnes_leitos_internacao removing 'Quantidade existente'
    _gravar_html(
        tmp_path,
        "cnes_leitos_internacao",
        "cnes_leitos_internacao_200707.html.gz",
        ["Município", "Outra coluna"],
        [["110001 ALTA FLORESTA", "70"]],
    )

    with pytest.raises(ValueError, match="Coluna obrigatória 'Quantidade existente' ausente"):
        saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2007,))


def test_coluna_obrigatoria_equipamentos_ausente_levanta_erro(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Absence of required equipment column raises ValueError."""
    _montar_estrutura_padrao(tmp_path, 2007)

    # Corrupt cnes_equipamentos_grupo removing required column
    _gravar_html(
        tmp_path,
        "cnes_equipamentos_grupo",
        "cnes_equipamentos_grupo_200707.html.gz",
        ["Município", "Equipamentos de Infra-Estrutura"],
        [["110001 ALTA FLORESTA", "1"]],
    )

    with pytest.raises(ValueError, match="Coluna obrigatória 'Equipamentos de Diagnostico por Imagem' ausente"):
        saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2007,))
