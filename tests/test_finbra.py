import io
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.nucleo import RespostaInvalida
from brmunipanel.tesouro import finbra
from brmunipanel.tesouro.despesa_funcao import COLUNAS_PUBLICADAS, FUNCOES
from brmunipanel.tesouro.finbra import (
    codigo_6,
    converter_moeda,
    processar_tabela,
    validar_zip,
)

DADOS = Path(__file__).parent / "dados"


def test_converter_moeda():
    assert converter_moeda(260931836000) == 26093183.6
    assert converter_moeda(800) == 0.08
    assert converter_moeda(-500) == -0.05
    assert converter_moeda(0) == 0.0
    assert converter_moeda(None) is None

    with pytest.raises(TypeError):
        converter_moeda("26,093,183.60")

    with pytest.raises(TypeError):
        converter_moeda(1.5)

    with pytest.raises(TypeError):
        converter_moeda(True)


def test_codigo_6():
    assert codigo_6(35, 5030) == "355030"
    assert codigo_6(35.0, 5030.0) == "355030"
    assert codigo_6("35", "5030") == "355030"
    assert codigo_6(11, 15) == "110015"
    assert codigo_6(None, 15) is None


def criar_zip(nomes: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for nome in nomes:
            zf.writestr(nome, b"dummy")
    return buffer.getvalue()


def test_validar_zip():
    # Aceita zip com 1 .mdb
    validar_zip(criar_zip(["x.MDB", "manifest.txt"]))

    with pytest.raises(RespostaInvalida, match="não é um ZIP"):
        validar_zip(b"invalid bytes")

    with pytest.raises(RespostaInvalida, match="ZIP deve conter exatamente 1"):
        validar_zip(criar_zip(["x.txt"]))

    with pytest.raises(RespostaInvalida, match="ZIP deve conter exatamente 1"):
        validar_zip(criar_zip(["x.mdb", "y.mdb"]))


@pytest.fixture
def municipios():
    return pl.DataFrame({
        "cod_municipio_6": ["355030", "110015", "999999"],
        "cod_municipio": ["3550308", "1100150", "9999999"],
    })


def test_processar_tabela_2006(municipios):
    tabela = {
        "UF": [35, 11],
        "Cod Mun": [5030, 15],
        "Despesas por Função": [20000, 10000],
        "Legislativa": [1000, -500],
        "Judiciária": [None, 0],
        "Essencial à Justiça": [0, 0],
        "Administração": [0, 0],
        "Defesa Nacional": [0, 0],
        "Segurança Pública": [0, 0],
        "Relações Exteriores": [0, 0],
        "Assistência Social": [0, 0],
        "Previdência Social": [0, 0],
        "Saúde": [0, 0],
        "Trabalho": [0, 0],
        "Educação": [0, 0],
        "Cultura": [0, 0],
        "Direitos da Cidadania": [0, 0],
        "Urbanismo": [0, 0],
        "Habitação": [0, 0],
        "Saneamento": [0, 0],
        "Gestão Ambiental": [0, 0],
        "Ciência e Tecnologia": [0, 0],
        "Agricultura": [0, 0],
        "Organização Agrária": [0, 0],
        "Indústria": [0, 0],
        "Comércio e Serviços": [0, 0],
        "Comunicações": [0, 0],
        "Energia": [0, 0],
        "Transporte": [0, 0],
        "Desporto e Lazer": [0, 0],
        "Encargos Especiais": [0, 0],
    }

    df, descartes = processar_tabela(tabela, 2006, municipios)
    assert not descartes

    assert df.height == 2
    assert df.columns == [
        "cod_municipio", "ano", "fonte",
        "desp_01_legislativa", "desp_02_judiciaria", "desp_03_essencial_justica",
        "desp_04_administracao", "desp_05_defesa_nacional", "desp_06_seguranca_publica",
        "desp_07_relacoes_exteriores", "desp_08_assistencia_social", "desp_09_previdencia_social",
        "desp_10_saude", "desp_11_trabalho", "desp_12_educacao",
        "desp_13_cultura", "desp_14_direitos_cidadania", "desp_15_urbanismo",
        "desp_16_habitacao", "desp_17_saneamento", "desp_18_gestao_ambiental",
        "desp_19_ciencia_tecnologia", "desp_20_agricultura", "desp_21_organizacao_agraria",
        "desp_22_industria", "desp_23_comercio_servicos", "desp_24_comunicacoes",
        "desp_25_energia", "desp_26_transporte", "desp_27_desporto_lazer",
        "desp_28_encargos_especiais", "desp_total_funcoes", "desp_intraorcamentaria",
        "declara_intraorcamentaria"
    ]
    
    assert df.schema["cod_municipio"] == pl.String
    assert df.schema["fonte"] == pl.String
    assert df.schema["ano"] == pl.Int16
    for c in df.columns:
        if c.startswith("desp_"):
            assert df.schema[c] == pl.Float64
    assert df.schema["declara_intraorcamentaria"] == pl.Boolean
    
    # Ordem de cod_municipio
    assert df["cod_municipio"].to_list() == ["1100150", "3550308"]
    assert df["ano"].to_list() == [2006, 2006]
    assert df["fonte"].to_list() == ["finbra", "finbra"]
    assert df["desp_01_legislativa"].to_list() == [-0.05, 0.1]
    assert df["desp_02_judiciaria"].to_list() == [0.0, None]
    assert df["desp_intraorcamentaria"].to_list() == [None, None]
    assert df["declara_intraorcamentaria"].to_list() == [None, None]
    assert df["desp_total_funcoes"].to_list() == [1.0, 2.0]


def test_processar_tabela_2010(municipios):
    tabela = {
        "UF": [35, 11, 99],
        "Cod Mun": [5030, 15, 9999],
        "Despesas por Função": [10000, 20000, 30000],
        "Legislativa": [0, 0, 0],
        "Judiciária": [0, 0, 0],
        "Essencial à Justiça": [0, 0, 0],
        "Administração": [0, 0, 0],
        "Defesa Nacional": [0, 0, 0],
        "Segurança Pública": [0, 0, 0],
        "Relações Exteriores": [0, 0, 0],
        "Assistência Social": [0, 0, 0],
        "Previdência Social": [0, 0, 0],
        "Saúde": [0, 0, 0],
        "Trabalho": [0, 0, 0],
        "Educação": [0, 0, 0],
        "Cultura": [0, 0, 0],
        "Direitos da Cidadania": [0, 0, 0],
        "Urbanismo": [0, 0, 0],
        "Habitação": [0, 0, 0],
        "Saneamento": [0, 0, 0],
        "Gestão Ambiental": [0, 0, 0],
        "Ciência e Tecnologia": [0, 0, 0],
        "Agricultura": [0, 0, 0],
        "Organização Agrária": [0, 0, 0],
        "Indústria": [0, 0, 0],
        "Comércio e Serviços": [0, 0, 0],
        "Comunicações": [0, 0, 0],
        "Energia": [0, 0, 0],
        "Transporte": [0, 0, 0],
        "Desporto e Lazer": [0, 0, 0],
        "Encargos Especiais": [0, 0, 0],
        "Desp por Função Intra-Orçamentária": [50000, 0, None],
        "0118": [1, 2, 3],
        "73424,011": [1, 2, 3],
    }

    df, descartes = processar_tabela(tabela, 2010, municipios)
    assert not descartes
    assert df.height == 3
    assert "0118" not in df.columns
    assert "73424,011" not in df.columns

    # 9999999 -> desp_intra None, declara False
    # 1100150 -> desp_intra 0, declara False
    # 3550308 -> desp_intra 5, declara True
    
    # Ordered by cod_municipio
    assert df["cod_municipio"].to_list() == ["1100150", "3550308", "9999999"]
    assert df["desp_intraorcamentaria"].to_list() == [0.0, 5.0, None]
    assert df["declara_intraorcamentaria"].to_list() == [False, True, False]


def test_erros_processar_tabela(municipios):
    tabela = {
        "UF": [35],
        "Cod Mun": [5030],
        "Despesas por Função": [10000],
        "Legislativa": [0],
        "Judiciária": [0],
        "Essencial à Justiça": [0],
        "Administração": [0],
        "Defesa Nacional": [0],
        "Segurança Pública": [0],
        "Relações Exteriores": [0],
        "Assistência Social": [0],
        "Previdência Social": [0],
        "Saúde": [0],
        "Trabalho": [0],
        "Educação": [0],
        "Cultura": [0],
        "Direitos da Cidadania": [0],
        "Urbanismo": [0],
        "Habitação": [0],
        "Saneamento": [0],
        "Gestão Ambiental": [0],
        "Ciência e Tecnologia": [0],
        "Agricultura": [0],
        "Organização Agrária": [0],
        "Indústria": [0],
        "Comércio e Serviços": [0],
        "Comunicações": [0],
        "Energia": [0],
        "Transporte": [0],
        "Desporto e Lazer": [0],
    }

    # Falta Encargos Especiais
    with pytest.raises(ValueError, match="Colunas faltando.*Encargos Especiais"):
        processar_tabela(tabela, 2006, municipios)

    tabela["Encargos Especiais"] = [0]
    
    # Duas intra
    tabela_intra = tabela.copy()
    tabela_intra["Intra 1"] = [0]
    tabela_intra["Intra 2"] = [0]
    with pytest.raises(ValueError, match="Múltiplas colunas intraorçamentárias"):
        processar_tabela(tabela_intra, 2006, municipios)
        
    # Chave repetida
    tabela_rep = {k: v * 2 for k, v in tabela.items()}
    with pytest.raises(ValueError, match="Chaves repetidas.*355030"):
        processar_tabela(tabela_rep, 2006, municipios)


def test_descartes(municipios):
    tabela = {
        "UF": [None, 35, 12],
        "Cod Mun": [5030, None, 15],
        "Despesas por Função": [10000, 10000, 10000],
        "Legislativa": [0, 0, 0],
        "Judiciária": [0, 0, 0],
        "Essencial à Justiça": [0, 0, 0],
        "Administração": [0, 0, 0],
        "Defesa Nacional": [0, 0, 0],
        "Segurança Pública": [0, 0, 0],
        "Relações Exteriores": [0, 0, 0],
        "Assistência Social": [0, 0, 0],
        "Previdência Social": [0, 0, 0],
        "Saúde": [0, 0, 0],
        "Trabalho": [0, 0, 0],
        "Educação": [0, 0, 0],
        "Cultura": [0, 0, 0],
        "Direitos da Cidadania": [0, 0, 0],
        "Urbanismo": [0, 0, 0],
        "Habitação": [0, 0, 0],
        "Saneamento": [0, 0, 0],
        "Gestão Ambiental": [0, 0, 0],
        "Ciência e Tecnologia": [0, 0, 0],
        "Agricultura": [0, 0, 0],
        "Organização Agrária": [0, 0, 0],
        "Indústria": [0, 0, 0],
        "Comércio e Serviços": [0, 0, 0],
        "Comunicações": [0, 0, 0],
        "Energia": [0, 0, 0],
        "Transporte": [0, 0, 0],
        "Desporto e Lazer": [0, 0, 0],
        "Encargos Especiais": [0, 0, 0],
    }

    df, descartes = processar_tabela(tabela, 2006, municipios)
    assert df.height == 0
    assert len(descartes) == 3
    assert descartes[0]["motivo"] == "chave nula"
    assert descartes[1]["motivo"] == "chave nula"
    assert descartes[2]["motivo"] == "fora da DTB"


def test_amostras_reais():
    with open(DADOS / "finbra_dsubfuncao_2006_amostra.json", encoding="utf-8") as f:
        tabela_2006 = json.load(f)
    
    with open(DADOS / "finbra_dsubfuncao_2010_amostra.json", encoding="utf-8") as f:
        tabela_2010 = json.load(f)

    muns_reais = pl.DataFrame({
        "cod_municipio_6": ["355030", "110009", "110013"],
        "cod_municipio": ["3550308", "1100098", "1100130"],
    })
    
    df_2006, d_2006 = processar_tabela(tabela_2006, 2006, muns_reais)
    assert df_2006.height == 3
    
    df_2010, d_2010 = processar_tabela(tabela_2010, 2010, muns_reais)
    assert df_2010.height == 3
    
    # O total de São Paulo igual ao inteiro da amostra / 10000
    sp_2006_raw = tabela_2006["Despesas por Função"][tabela_2006["Cod Mun"].index(5030)]
    sp_2006_df = df_2006.filter(pl.col("cod_municipio") == "3550308")["desp_total_funcoes"][0]
    assert sp_2006_df == sp_2006_raw / 10000.0
    
    sp_2010_raw = tabela_2010["Despesas por Função"][tabela_2010["Cod Mun"].index(5030)]
    sp_2010_df = df_2010.filter(pl.col("cod_municipio") == "3550308")["desp_total_funcoes"][0]
    assert sp_2010_df == sp_2010_raw / 10000.0

    assert "0118" in tabela_2010
    assert "0118" not in df_2010.columns
    
    sp_2010_intra = df_2010.filter(pl.col("cod_municipio") == "3550308")["desp_intraorcamentaria"][0]
    assert sp_2010_intra == 10311896708400 / 10000.0
    
    assert df_2010.filter(pl.col("cod_municipio") == "3550308")["declara_intraorcamentaria"][0] is True
    assert df_2010.filter(pl.col("cod_municipio") == "1100098")["declara_intraorcamentaria"][0] is True
    assert df_2010.filter(pl.col("cod_municipio") == "1100130")["declara_intraorcamentaria"][0] is False

    # Soma das funções a menos de 0,1%
    funcoes_cols = [c for c in df_2006.columns if c.startswith("desp_") and c not in ("desp_total_funcoes", "desp_intraorcamentaria")]
    
    def check_soma(df, df_nome):
        for row in df.iter_rows(named=True):
            soma = sum(row[c] for c in funcoes_cols if row[c] is not None)
            total = row["desp_total_funcoes"]
            if total > 0:
                diff = abs(soma - total)
                rel_diff = diff / total
                if rel_diff >= 0.001:
                    assert False, f"[{df_nome}] Município {row['cod_municipio']} não fechou: soma={soma}, total={total}, rel_diff={rel_diff}"
    
    check_soma(df_2006, "2006")
    check_soma(df_2010, "2010")


def test_colunas_publicadas():
    assert len(COLUNAS_PUBLICADAS) == 30
    assert COLUNAS_PUBLICADAS[0] == "cod_municipio"
    assert COLUNAS_PUBLICADAS[1] == "ano"
    for i, (_, _, c_out) in enumerate(FUNCOES):
        assert COLUNAS_PUBLICADAS[i + 2] == c_out


def test_harmonizar(tmp_path, monkeypatch):
    
    with open(DADOS / "finbra_dsubfuncao_2006_amostra.json", encoding="utf-8") as f:
        tabela_2006 = json.load(f)
    with open(DADOS / "finbra_dsubfuncao_2010_amostra.json", encoding="utf-8") as f:
        tabela_2010 = json.load(f)
        
    def mock_ler_dsubfuncao(pasta, ano):
        if ano <= 2009:
            return tabela_2006
        else:
            return tabela_2010
            
    monkeypatch.setattr(finbra, "ler_dsubfuncao", mock_ler_dsubfuncao)
    
    municipios = pl.DataFrame({
        "cod_municipio_6": ["355030", "110009", "110013"],
        "cod_municipio": ["3550308", "1100098", "1100130"],
    })
    
    df = finbra.harmonizar(tmp_path, municipios)
    
    assert df.columns == COLUNAS_PUBLICADAS
    assert "fonte" not in df.columns
    assert "desp_total_funcoes" not in df.columns
    assert "desp_intraorcamentaria" not in df.columns
    assert "declara_intraorcamentaria" not in df.columns
    
    assert df.is_sorted(["cod_municipio", "ano"])
    assert df.height == 3 * 7  # 3 municípios, 7 anos (2006-2012)
    assert df.schema["cod_municipio"] == pl.String
    assert df.schema["ano"] == pl.Int16
    for c in COLUNAS_PUBLICADAS[2:]:
        assert df.schema[c] == pl.Float64
