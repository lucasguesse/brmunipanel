"""Tests for the TabNet client (DATASUS)."""

from pathlib import Path

import pytest

from brmunipanel.datasus.tabnet import TABULATIONS, extract_table, build_body, dbf_name, validate
from brmunipanel.core import InvalidResponse

FOLDER_DATA = Path(__file__).parent / "data"


def _get_tabulation(name: str):
    for tab in TABULATIONS:
        if tab.name == name:
            return tab
    raise KeyError(name)


def test_build_body_cnes_inpatient_beds_2006():
    """1. build_body for cnes_inpatient_beds in 2006 returns the exact expected body."""
    tab = _get_tabulation("cnes_inpatient_beds")
    body = build_body(tab, "2006")
    expected = (
        "Linha=Munic%EDpio&Coluna=--N%E3o-Ativa--&Incremento=Quantidade_existente"
        "&Incremento=Quantidade_SUS&Arquivos=ltbr0607.dbf&formato=prn&mostre=Mostra"
    )
    assert body == expected

    body_07 = build_body(tab, "200607")
    assert body_07 == expected


def test_build_body_sim_assault_deaths_2023():
    """2. build_body for sim_assault_deaths in 2023 contains expected parameters and filters."""
    tab = _get_tabulation("sim_assault_deaths")
    body = build_body(tab, "2023")
    assert "Incremento=%D3bitos_p%2FResid%EAnc" in body
    assert "Arquivos=obtbr23.dbf" in body
    assert "SGrupo_CID-10=246" in body
    assert "formato=prn" in body
    assert "mostre=Mostra" in body


def test_dbf_name_by_tabulation_and_period():
    """3. The .dbf file name by tabulation and period, including pfbr0708.dbf."""
    t_beds = _get_tabulation("cnes_inpatient_beds")
    assert dbf_name(t_beds, "200607") == "ltbr0607.dbf"
    assert dbf_name(t_beds, "202307") == "ltbr2307.dbf"

    t_legacy_sec = _get_tabulation("cnes_physicians_cbo1994")
    assert dbf_name(t_legacy_sec, "200607") == "pfbr0607.dbf"
    assert dbf_name(t_legacy_sec, "200707") == "pfbr0707.dbf"

    t_sec_new = _get_tabulation("cnes_physicians_cbo2002")
    assert dbf_name(t_sec_new, "200708") == "pfbr0708.dbf"
    assert dbf_name(t_sec_new, "200807") == "pfbr0807.dbf"
    assert dbf_name(t_sec_new, "202307") == "pfbr2307.dbf"

    t_deaths = _get_tabulation("sim_assault_deaths")
    assert dbf_name(t_deaths, "2006") == "obtbr06.dbf"
    assert dbf_name(t_deaths, "2023") == "obtbr23.dbf"

    t_early_childhood = _get_tabulation("sim_infant_deaths")
    assert dbf_name(t_early_childhood, "2006") == "infbr06.dbf"

    t_born = _get_tabulation("sinasc_live_births")
    assert dbf_name(t_born, "2006") == "nvbr06.dbf"
    assert dbf_name(t_born, "2023") == "nvbr23.dbf"


def test_extract_table_and_validate_real_samples():
    """4. extract_table and validate on real samples and rejection of 'Nenhum record selecionado'."""
    # Sample without active column
    content_without_column = (FOLDER_DATA / "tabnet_without_column_sample.html").read_bytes()
    header, rows = extract_table(content_without_column)
    assert header == ["Município", "Quantidade existente", "Quantidade SUS"]
    assert len(rows) == 11  # 10 municipalities + Total
    assert rows[-1][0].lower() == "total"
    validate(content_without_column, min_rows=10)

    # Sample with active column
    content_with_column = (FOLDER_DATA / "tabnet_with_column_sample.html").read_bytes()
    cab_col, rows_col = extract_table(content_with_column)
    assert cab_col[0] == "Município"
    assert len(cab_col) > 2
    assert len(rows_col) == 11  # 10 municipalities + Total
    assert rows_col[-1][0].lower() == "total"
    validate(content_with_column, min_rows=10)

    # Empty sample ("Nenhum record selecionado")
    empty_content = (FOLDER_DATA / "tabnet_empty_sample.html").read_bytes()
    with pytest.raises(InvalidResponse, match="Nenhum registro selecionado"):
        validate(empty_content, min_rows=10)


def test_extract_table_malformed_row_before_total_raises_error():
    """Malformed row before Total with mismatched column count raises InvalidResponse with label."""
    malformed_html = (
        b"<PRE>"
        b'"Municipio";"Col1";"Col2"\n'
        b'"110001 ALTA FLORESTA";10;20\n'
        b'"110002 ARIQUEMES";15\n'
        b'"Total";25;20\n'
        b"</PRE>"
    )
    with pytest.raises(InvalidResponse, match="Malformed row before Total: label '110002 ARIQUEMES'"):
        extract_table(malformed_html)

    # Divergent rows AFTER Total are ignored without raising error
    html_divergent_footer = (
        b"<PRE>"
        b'"Municipio";"Col1";"Col2"\n'
        b'"110001 ALTA FLORESTA";10;20\n'
        b'"Total";10;20\n'
        b"Fonte: DATASUS - TabNet\n"
        b"</PRE>"
    )
    hdr, rows = extract_table(html_divergent_footer)
    assert len(rows) == 2
    assert rows[-1][0].lower() == "total"

