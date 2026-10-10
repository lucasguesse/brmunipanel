"""Testes do cliente do TabNet (DATASUS)."""

from pathlib import Path

import pytest

from br_municipios_panel.datasus import tabnet
from br_municipios_panel.datasus.tabnet import TABULACOES, extrair_tabela, montar_corpo, nome_dbf, validar
from br_municipios_panel.nucleo import RespostaInvalida

PASTA_DADOS = Path(__file__).parent / "dados"


def _obter_tabulacao(nome: str):
    for tab in TABULACOES:
        if tab.nome == nome:
            return tab
    raise KeyError(nome)


def test_montar_corpo_cnes_leitos_internacao_2006():
    """1. montar_corpo para cnes_leitos_internacao em 2006 devolve o corpo exato esperado."""
    tab = _obter_tabulacao("cnes_leitos_internacao")
    corpo = montar_corpo(tab, "2006")
    esperado = (
        "Linha=Munic%EDpio&Coluna=--N%E3o-Ativa--&Incremento=Quantidade_existente"
        "&Incremento=Quantidade_SUS&Arquivos=ltbr0607.dbf&formato=prn&mostre=Mostra"
    )
    assert corpo == esperado

    corpo_07 = montar_corpo(tab, "200607")
    assert corpo_07 == esperado


def test_montar_corpo_sim_obitos_agressao_2023():
    """2. montar_corpo para sim_obitos_agressao em 2023 contém os parâmetros e filtros esperados."""
    tab = _obter_tabulacao("sim_obitos_agressao")
    corpo = montar_corpo(tab, "2023")
    assert "Incremento=%D3bitos_p%2FResid%EAnc" in corpo
    assert "Arquivos=obtbr23.dbf" in corpo
    assert "SGrupo_CID-10=246" in corpo
    assert "formato=prn" in corpo
    assert "mostre=Mostra" in corpo


def test_nome_dbf_por_tabulacao_e_periodo():
    """3. O nome do arquivo .dbf por tabulação e período, incluindo pfbr0708.dbf."""
    t_leitos = _obter_tabulacao("cnes_leitos_internacao")
    assert nome_dbf(t_leitos, "200607") == "ltbr0607.dbf"
    assert nome_dbf(t_leitos, "202307") == "ltbr2307.dbf"

    t_med_antigo = _obter_tabulacao("cnes_medicos_cbo1994")
    assert nome_dbf(t_med_antigo, "200607") == "pfbr0607.dbf"
    assert nome_dbf(t_med_antigo, "200707") == "pfbr0707.dbf"

    t_med_novo = _obter_tabulacao("cnes_medicos_cbo2002")
    assert nome_dbf(t_med_novo, "200708") == "pfbr0708.dbf"
    assert nome_dbf(t_med_novo, "200807") == "pfbr0807.dbf"
    assert nome_dbf(t_med_novo, "202307") == "pfbr2307.dbf"

    t_obitos = _obter_tabulacao("sim_obitos_agressao")
    assert nome_dbf(t_obitos, "2006") == "obtbr06.dbf"
    assert nome_dbf(t_obitos, "2023") == "obtbr23.dbf"

    t_infantil = _obter_tabulacao("sim_obitos_infantis")
    assert nome_dbf(t_infantil, "2006") == "infbr06.dbf"

    t_nascidos = _obter_tabulacao("sinasc_nascidos_vivos")
    assert nome_dbf(t_nascidos, "2006") == "nvbr06.dbf"
    assert nome_dbf(t_nascidos, "2023") == "nvbr23.dbf"


def test_extrair_tabela_e_validar_amostras_reais():
    """4. extrair_tabela e validar sobre amostras reais e rejeição de 'Nenhum registro selecionado'."""
    # Amostra sem coluna ativa
    conteudo_sem_coluna = (PASTA_DADOS / "tabnet_sem_coluna_amostra.html").read_bytes()
    cabecalho, linhas = extrair_tabela(conteudo_sem_coluna)
    assert cabecalho == ["Município", "Quantidade existente", "Quantidade SUS"]
    assert len(linhas) == 11  # 10 municipios + Total
    assert linhas[-1][0].lower() == "total"
    validar(conteudo_sem_coluna, min_linhas=10)

    # Amostra com coluna ativa
    conteudo_com_coluna = (PASTA_DADOS / "tabnet_com_coluna_amostra.html").read_bytes()
    cab_col, linhas_col = extrair_tabela(conteudo_com_coluna)
    assert cab_col[0] == "Município"
    assert len(cab_col) > 2
    assert len(linhas_col) == 11  # 10 municipios + Total
    assert linhas_col[-1][0].lower() == "total"
    validar(conteudo_com_coluna, min_linhas=10)

    # Amostra vazia ("Nenhum registro selecionado")
    conteudo_vazio = (PASTA_DADOS / "tabnet_vazio_amostra.html").read_bytes()
    with pytest.raises(RespostaInvalida, match="Nenhum registro selecionado"):
        validar(conteudo_vazio, min_linhas=10)


def test_extrair_tabela_linha_malformada_antes_do_total_levanta_erro():
    """Linha com número divergente de colunas antes do Total levanta RespostaInvalida com rótulo."""
    html_malformado = (
        b"<PRE>"
        b'"Municipio";"Col1";"Col2"\n'
        b'"110001 ALTA FLORESTA";10;20\n'
        b'"110002 ARIQUEMES";15\n'
        b'"Total";25;20\n'
        b"</PRE>"
    )
    with pytest.raises(RespostaInvalida, match="Linha malformada antes do Total: rótulo '110002 ARIQUEMES'"):
        extrair_tabela(html_malformado)

    # Linhas divergentes APÓS o Total são ignoradas sem levantar erro
    html_rodape_divergente = (
        b"<PRE>"
        b'"Municipio";"Col1";"Col2"\n'
        b'"110001 ALTA FLORESTA";10;20\n'
        b'"Total";10;20\n'
        b"Fonte: DATASUS - TabNet\n"
        b"</PRE>"
    )
    cab, linhas = extrair_tabela(html_rodape_divergente)
    assert len(linhas) == 2
    assert linhas[-1][0].lower() == "total"

