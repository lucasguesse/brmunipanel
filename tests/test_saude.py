"""Testes da harmonização das tabulações de saúde do TabNet (DATASUS)."""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.datasus import saude


def _criar_html(cabecalho: list[str], linhas: list[list[str]]) -> bytes:
    """Monta HTML do TabNet dentro de <PRE> com separador ponto-e-vírgula em latin-1 comprimido em gzip."""
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
    """Cria uma estrutura mínima e válida para todas as tabulações do ano."""
    p_cnes = f"{ano:04d}07"
    p_sim = str(ano)

    # 1. Leitos internação
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

    # 2. Leitos complementares (UTI)
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

    # 3. Médicos (CBO 1994 para <=2007, CBO 2002 para >=2008)
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

    # 4. Estabelecimentos
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

    # 4.5 Equipamentos (Testando ordem diferente de colunas)
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

    # 5. Óbitos por agressão
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

    # 6. Óbitos infantis
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

    # 7. Nascidos vivos
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
    """Tabela mínima de municípios da DTB."""
    return pl.DataFrame({
        "cod_municipio": ["1100015", "1100023", "5300108"],
        "cod_municipio_6": ["110001", "110002", "530010"],
    })


@pytest.fixture
def df_populacao() -> pl.DataFrame:
    """Tabela de população com Nazária/ausente simulado."""
    return pl.DataFrame({
        "cod_municipio": ["1100015", "1100015", "1100023", "5300108", "5300108"],
        "ano": [2007, 2008, 2007, 2007, 2008],
        "populacao": [25000, 24000, 80000, 2500000, 2600000],
    }, schema_overrides={"ano": pl.Int16, "populacao": pl.Int64})


def test_regras_harmonizacao_saude(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Testa: município ignorado descartado, '-' vira 0, UTI agrega e exclui COVID/intermed,

    53xxxx somado em Brasília, ausente recebe 0, sem população fica nulo, e versão CBO correta.
    """
    ano = 2007
    p_cnes = f"{ano:04d}07"
    p_sim = str(ano)

    _montar_estrutura_padrao(tmp_path, ano)

    # Sobrescrever complementares para testar:
    # - soma de UTI inclui UTI adulto II e UTI neonatal
    # - exclui Unidade intermediária
    # - separa UTI adulto II COVID-19
    # - traço '-' vira zero
    # - linha de município ignorado é descartada
    # - códigos 53xxxx somados em Brasília (530010)
    _gravar_html(
        tmp_path,
        "cnes_leitos_complementares",
        f"cnes_leitos_complementares_{p_cnes}.html.gz",
        ["Município", "UTI adulto II", "UTI neonatal", "Unidade intermediária", "UTI adulto II COVID-19", "Total"],
        [
            ["110001 ALTA FLORESTA", "2", "3", "5", "4", "14"],
            ["530010 BRASILIA", "10", "-", "2", "-", "12"],
            ["539999 REGIAO ADM DF", "5", "2", "1", "1", "9"],  # Outro código 53
            ["MUNICIPIO IGNORADO - RO", "99", "99", "99", "99", "396"],  # Ignorado
            ["Total", "116", "104", "107", "104", "431"],
        ],
    )

    painel = saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2007,))

    assert painel.shape == (3, 11)
    assert painel.columns == list(saude.COLUNAS_PAINEL)

    # 1. Município 1100015 (Alta Floresta):
    m11 = painel.filter(pl.col("cod_municipio") == "1100015").to_dicts()[0]
    assert m11["leitos_uti"] == 5  # 2 + 3 (excluiu 5 de intermediária e 4 de COVID)
    assert m11["leitos_internacao"] == 70
    assert m11["equipamentos_imagem"] == 10

    # 2. Município 5300108 (Brasília):
    # Soma de 530010 (10 + 0 UTI) com 539999 (5 + 2 UTI)
    m53 = painel.filter(pl.col("cod_municipio") == "5300108").to_dicts()[0]
    assert m53["leitos_uti"] == 17  # 10 + 0 + 5 + 2
    # Nas tabulações onde Brasília não apareceu na resposta, recebeu 0 (Regra 5)
    assert m53["leitos_internacao"] == 0
    assert m53["obitos_agressao"] == 0

    # 3. Município 1100023 em 2007 tem população, mas não apareceu em nenhuma tabulação -> recebe 0
    m1102 = painel.filter(pl.col("cod_municipio") == "1100023").to_dicts()[0]
    assert m1102["leitos_internacao"] == 0
    assert m1102["leitos_uti"] == 0
    assert m1102["equipamentos_imagem"] == 0
    assert m1102["medicos"] == 0
    
    # 4. Asserção das colunas retiradas
    assert "leitos_internacao_sus" not in painel.columns
    assert "leitos_uti_covid19" not in painel.columns
    assert "medicos_cbo" not in painel.columns


def test_municipio_sem_populacao_fica_nulo(tmp_path: Path, df_municipios: pl.DataFrame, df_populacao: pl.DataFrame):
    """Regra 6: município e ano sem registro de população fica com todas as colunas nulas."""
    ano = 2008
    _montar_estrutura_padrao(tmp_path, ano)

    painel = saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2008,))

    # Município 1100023 NÃO tem população em 2008 no df_populacao
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
    """Testa que medicos usa a tabulação cbo1994 em 2007 e cbo2002 em 2008."""
    _montar_estrutura_padrao(tmp_path, 2007)
    _montar_estrutura_padrao(tmp_path, 2008)

    # Sobrescrever medicos em 2008 para um valor diferente
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
    """Ausência de coluna obrigatória ('Quantidade existente', 'POSTO DE SAUDE', etc.) levanta ValueError."""
    _montar_estrutura_padrao(tmp_path, 2007)

    # Corromper cnes_leitos_internacao removendo 'Quantidade existente'
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
    """Ausência de coluna obrigatória de equipamentos levanta ValueError."""
    _montar_estrutura_padrao(tmp_path, 2007)

    # Corromper cnes_equipamentos_grupo removendo a coluna obrigatória
    _gravar_html(
        tmp_path,
        "cnes_equipamentos_grupo",
        "cnes_equipamentos_grupo_200707.html.gz",
        ["Município", "Equipamentos de Infra-Estrutura"],
        [["110001 ALTA FLORESTA", "1"]],
    )

    with pytest.raises(ValueError, match="Coluna obrigatória 'Equipamentos de Diagnostico por Imagem' ausente"):
        saude.harmonizar(tmp_path, df_municipios, df_populacao, anos=(2007,))
