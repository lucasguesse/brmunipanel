
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from brmunipanel.painel import (
    montar_municipios,
    montar_despesa,
    montar_tabela_longitudinal,
    montar_limitrofes,
    consolidar_educacao,
)

def test_montar_municipios():
    municipios = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "nome_municipio": ["A", "B"],
        "cod_uf": [1, 2],
        "sigla_uf": ["UF", "UF"],
        "nome_uf": ["Estado", "Estado"],
        "nome_rg_intermediaria": ["RI", "RI"],
        "nome_rg_imediata": ["RI", "RI"],
        "fronteira_internacional": [0, 1],
        "litoraneo": [1, 0],
        "area_km2": [10.0, 20.0],
        "latitude_sede": [-10.0, -20.0],
        "longitude_sede": [-30.0, -40.0],
    })
    
    saida = montar_municipios(municipios)
    assert_frame_equal(saida, municipios)

def test_montar_municipios_erros():
    municipios_dup = pl.DataFrame({"cod_municipio": ["1", "1"]})
    with pytest.raises(ValueError, match="municipios:.*chaves repetidas"):
        montar_municipios(municipios_dup)
        
    municipios_falta = pl.DataFrame({
        "cod_municipio": ["1"],
        "nome_municipio": ["A"],
    })
    with pytest.raises(ValueError, match="Falta coluna cod_uf em municipios"):
        montar_municipios(municipios_falta)

def test_montar_despesa():
    finbra = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "desp_01_legislativa": [10.0],
        "desp_intraorcamentaria": [5.0]
    })
    siconfi = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2013], dtype=pl.Int16),
        "desp_01_legislativa": [12.0],
        "desp_intraorcamentaria": [6.0]
    })
    
    saida = montar_despesa(finbra, siconfi)
    
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2010, 2013], dtype=pl.Int16),
        "desp_legislativa": [10.0, 12.0],
        "desp_intraorcamentaria": [5.0, 6.0]
    })
    
    assert_frame_equal(saida, esperado)

def test_montar_despesa_erros():
    finbra = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "v": [10.0],
    })
    siconfi = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "v": [12.0],
    })
    with pytest.raises(ValueError, match="casos do mesmo munic.*pio e ano"):
        montar_despesa(finbra, siconfi)

def test_montar_tabela_longitudinal():
    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    anos = range(2010, 2012)
    
    f1 = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2010, 2011], dtype=pl.Int16),
        "v1": [1.0, 2.0],
    })
    f2 = pl.DataFrame({
        "cod_municipio": ["2", "1", "1"],
        "ano": pl.Series([2011, 2010, 2011], dtype=pl.Int16),
        "v2": ["A", "B", None],
    })
    
    saida = montar_tabela_longitudinal(municipios, [f1, f2], anos=anos, nome_tabela="teste")
    
    assert saida.columns == ["cod_municipio", "ano", "v1", "v2"]
    assert len(saida) == 4
    
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "1", "2", "2"],
        "ano": pl.Series([2010, 2011, 2010, 2011], dtype=pl.Int16),
        "v1": [1.0, None, None, 2.0],
        "v2": ["B", None, None, "A"],
    })
    assert_frame_equal(saida, esperado)

    painel_f1 = saida.join(f1.select(["cod_municipio", "ano"]), on=["cod_municipio", "ano"], how="inner").select(["cod_municipio", "ano", "v1"])
    assert_frame_equal(painel_f1.sort(["cod_municipio", "ano"]), f1.sort(["cod_municipio", "ano"]))

    painel_f2 = saida.join(f2.select(["cod_municipio", "ano"]), on=["cod_municipio", "ano"], how="inner").select(["cod_municipio", "ano", "v2"])
    assert_frame_equal(painel_f2.sort(["cod_municipio", "ano"]), f2.sort(["cod_municipio", "ano"]))

def test_montar_tabela_longitudinal_erros():
    municipios = pl.DataFrame({"cod_municipio": ["1"]})
    anos = range(2010, 2012)
    
    f = pl.DataFrame({"cod_municipio": ["2"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="teste .*c.*digos fora da tabela"):
        montar_tabela_longitudinal(municipios, [f], anos=anos, nome_tabela="teste")
        
    f = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2012], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="teste .*anos fora da janela"):
        montar_tabela_longitudinal(municipios, [f], anos=anos, nome_tabela="teste")
        
    f = pl.DataFrame({"cod_municipio": ["1", "1"], "ano": pl.Series([2010, 2010], dtype=pl.Int16), "v": [1, 2]})
    with pytest.raises(ValueError, match="teste .*chaves repetidas"):
        montar_tabela_longitudinal(municipios, [f], anos=anos, nome_tabela="teste")
        
    f1 = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    f2 = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [2]})
    with pytest.raises(ValueError, match="teste .*coluna com nome que outra fonte"):
        montar_tabela_longitudinal(municipios, [f1, f2], anos=anos, nome_tabela="teste")
        
def test_montar_limitrofes():
    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    lims = pl.DataFrame({
        "cod_municipio": ["2", "1"],
        "cod_municipio_limitrofe": ["1", "2"],
    })
    saida = montar_limitrofes(municipios, lims)
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "cod_municipio_limitrofe": ["2", "1"],
    })
    assert_frame_equal(saida, esperado)

def test_montar_limitrofes_erros():
    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    lims = pl.DataFrame({"cod_municipio": ["1", "1"], "cod_municipio_limitrofe": ["2", "2"]})
    with pytest.raises(ValueError, match="limitrofes:.*pares repetidos"):
        montar_limitrofes(municipios, lims)
    lims = pl.DataFrame({"cod_municipio": ["3"], "cod_municipio_limitrofe": ["1"]})
    with pytest.raises(ValueError, match="limitrofes:.*c.*digos fora"):
        montar_limitrofes(municipios, lims)

def test_consolidar_educacao():
    censo_escolar = pl.DataFrame({
        "cod_municipio": ["1", "1", "3", "5"],
        "ano": pl.Series([2010, 2010, 2010, 2010], dtype=pl.Int16),
        "dependencia": ["Estadual", "Municipal", "Estadual", "Municipal"],
        "localizacao": ["Urbana", "Rural", "Urbana", "Urbana"],
        "escolas": [10, 20, None, 10],
        "matriculas_infantil": [100, 200, None, 100],
        "matriculas_fundamental": [1000, 2000, None, 1000],
        "matriculas_medio": [100, 200, None, 100],
        "docentes_basica": [50, 100, None, 50],
    })
    censo_superior = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "categoria": ["A", "A"],
        "instituicoes": [1, 2],
        "matriculas": [1000, 2000],
    })
    ideb = pl.DataFrame({
        "cod_municipio": ["2", "4"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [5.5, None],
        "ideb_anos_finais_publica": [4.5, None],
        "ideb_ensino_medio_publica": [3.5, None],
    })
    
    saida = consolidar_educacao(censo_escolar, censo_superior, ideb)
    
    assert len(saida) == 4
    assert saida.columns == [
        "cod_municipio", "ano",
        "instituicoes_basica", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica",
        "instituicoes_superior", "matriculas_superior",
        "ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"
    ]
    
    assert saida.filter(pl.col("cod_municipio") == "1")["instituicoes_basica"][0] == 30
    assert saida.filter(pl.col("cod_municipio") == "1")["instituicoes_superior"][0] == 1
    
    assert saida.filter(pl.col("cod_municipio") == "2")["instituicoes_superior"][0] == 2
    assert saida.filter(pl.col("cod_municipio") == "2")["instituicoes_basica"].is_null()[0]
    
    assert saida.filter(pl.col("cod_municipio") == "3")["instituicoes_basica"].is_null()[0]

    assert len(saida.filter(pl.col("cod_municipio") == "4")) == 0

    assert saida.filter(pl.col("cod_municipio") == "5")["instituicoes_basica"][0] == 10

def test_consolidar_educacao_erros():
    censo_escolar = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "dependencia": ["Estadual"], "localizacao": ["Urbana"],
        "escolas": [10], "matriculas_infantil": [100], "matriculas_fundamental": [1000], "matriculas_medio": [100], "docentes_basica": [50]
    })
    censo_superior = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "categoria": ["A"], "instituicoes": [1], "matriculas": [1000]
    })
    
    ideb = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [5.5], "ideb_anos_finais_publica": [4.5], "ideb_ensino_medio_publica": [11.0]
    })
    with pytest.raises(ValueError, match="ideb: valores fora"):
        consolidar_educacao(censo_escolar, censo_superior, ideb)

    ideb_dup = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [5.5, 5.5], "ideb_anos_finais_publica": [4.5, 4.5], "ideb_ensino_medio_publica": [3.5, 3.5]
    })
    with pytest.raises(ValueError, match="Chaves duplicadas na entrada ideb"):
        consolidar_educacao(censo_escolar, censo_superior, ideb_dup)

    escolar_null = pl.DataFrame({
        "cod_municipio": pl.Series([None], dtype=pl.String),
        "ano": pl.Series([2010], dtype=pl.Int16),
        "dependencia": ["Estadual"], "localizacao": ["Urbana"],
        "escolas": [10], "matriculas_infantil": [100], "matriculas_fundamental": [1000], "matriculas_medio": [100], "docentes_basica": [50]
    })
    with pytest.raises(ValueError, match="Chaves nulas na entrada censo_escolar"):
        consolidar_educacao(escolar_null, censo_superior, ideb_dup)
        
    escolar_dup = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "dependencia": ["Estadual", "Estadual"], "localizacao": ["Urbana", "Urbana"],
        "escolas": [10, 20], "matriculas_infantil": [100, 100], "matriculas_fundamental": [1000, 1000], "matriculas_medio": [100, 100], "docentes_basica": [50, 50]
    })
    with pytest.raises(ValueError, match="censo_escolar: chaves dimensionais duplicadas antes da agregação"):
        consolidar_educacao(escolar_dup, censo_superior, ideb)
        
    escolar_bad_type = pl.DataFrame({
        "cod_municipio": [1],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "dependencia": ["Estadual"], "localizacao": ["Urbana"],
        "escolas": [10], "matriculas_infantil": [100], "matriculas_fundamental": [1000], "matriculas_medio": [100], "docentes_basica": [50]
    })
    with pytest.raises(ValueError, match="censo_escolar: cod_municipio deve ser String"):
        consolidar_educacao(escolar_bad_type, censo_superior, ideb)
        
    escolar_bad_ano = censo_escolar.with_columns(pl.col("ano").cast(pl.Int32))
    with pytest.raises(ValueError, match="censo_escolar: ano deve ser Int16"):
        consolidar_educacao(escolar_bad_ano, censo_superior, ideb)
        
    escolar_bad_medida = censo_escolar.with_columns(pl.col("escolas").cast(pl.Float64))
    with pytest.raises(ValueError, match="censo_escolar: escolas deve ser inteiro"):
        consolidar_educacao(escolar_bad_medida, censo_superior, ideb)
        
    superior_bad_ano = censo_superior.with_columns(pl.col("ano").cast(pl.Int64))
    with pytest.raises(ValueError, match="censo_superior: ano deve ser Int16"):
        consolidar_educacao(censo_escolar, superior_bad_ano, ideb)
        
    superior_bad_medida = censo_superior.with_columns(pl.col("instituicoes").cast(pl.String))
    with pytest.raises(ValueError, match="censo_superior: instituicoes deve ser inteiro"):
        consolidar_educacao(censo_escolar, superior_bad_medida, ideb)
        
    ideb_bad_ano = ideb.with_columns(pl.col("ano").cast(pl.Int32))
    with pytest.raises(ValueError, match="ideb: ano deve ser Int16"):
        consolidar_educacao(censo_escolar, censo_superior, ideb_bad_ano)
        
    ideb_bad_medida = ideb.with_columns(pl.col("ideb_anos_iniciais_publica").cast(pl.Int64))
    with pytest.raises(ValueError, match="ideb: ideb_anos_iniciais_publica deve ser Float64"):
        consolidar_educacao(censo_escolar, censo_superior, ideb_bad_medida)


def test_consolidar_educacao_filtros():
    censo_escolar = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2000, 2010], dtype=pl.Int16),
        "dependencia": ["Estadual", "Estadual"],
        "localizacao": ["Urbana", "Urbana"],
        "escolas": [10, 10],
        "matriculas_infantil": [100, 100],
        "matriculas_fundamental": [1000, 1000],
        "matriculas_medio": [100, 100],
        "docentes_basica": [50, 50],
    })
    censo_superior = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2000, 2010], dtype=pl.Int16),
        "categoria": ["A", "A"],
        "instituicoes": [1, 2],
        "matriculas": [1000, 2000],
    })
    ideb = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2000, 2010], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [5.5, 6.0],
        "ideb_anos_finais_publica": [4.5, 5.0],
        "ideb_ensino_medio_publica": [3.5, 4.0],
    })
    
    saida = consolidar_educacao(censo_escolar, censo_superior, ideb)
    
    assert len(saida.filter(pl.col("ano") == 2000).drop_nulls(subset=["instituicoes_superior"])) == 0
    assert len(saida.filter(pl.col("ano") == 2000).drop_nulls(subset=["ideb_anos_iniciais_publica"])) == 0
    
    assert saida.filter(pl.col("ano") == 2010)["instituicoes_superior"][0] == 2
    assert saida.filter(pl.col("ano") == 2010)["ideb_anos_iniciais_publica"][0] == 6.0

def test_consolidar_educacao_agregacao_e_ideb():
    censo_escolar = pl.DataFrame({
        "cod_municipio": ["1", "1", "1", "2"],
        "ano": pl.Series([2008, 2010, 2010, 2010], dtype=pl.Int16),
        "dependencia": ["M", "E", "M", "E"],
        "localizacao": ["U", "U", "U", "U"],
        "escolas": [10, 20, 30, 40],
        "matriculas_infantil": [1, 2, 3, 4],
        "matriculas_fundamental": [1, 2, 3, 4],
        "matriculas_medio": [1, 2, 3, 4],
        "docentes_basica": [1, 2, 3, 4],
    })
    
    # Censo superior has multiple categories for the same cod/ano
    censo_superior = pl.DataFrame({
        "cod_municipio": ["1", "1", "2"],
        "ano": pl.Series([2010, 2010, 2010], dtype=pl.Int16),
        "categoria": ["Pública", "Privada", "Privada"],
        "instituicoes": [1, 2, 5],
        "matriculas": [1000, 2000, 5000],
    })
    
    # IDEB: 2008, even year, enters with all three stages null, and 2009 enters with value
    ideb = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2008, 2009], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [None, 6.0],
        "ideb_anos_finais_publica": [None, 5.0],
        "ideb_ensino_medio_publica": [None, 4.0],
    })
    
    saida = consolidar_educacao(censo_escolar, censo_superior, ideb)
    
    # Assert aggregation for superior
    sup_mun1 = saida.filter((pl.col("cod_municipio") == "1") & (pl.col("ano") == 2010))
    assert sup_mun1["instituicoes_superior"][0] == 3
    assert sup_mun1["matriculas_superior"][0] == 3000
    
    # Assert even year null for IDEB (2008)
    mun1_2008 = saida.filter((pl.col("cod_municipio") == "1") & (pl.col("ano") == 2008))
    assert mun1_2008["ideb_anos_iniciais_publica"].is_null()[0]
    
    # Assert odd year IDEB separated correctly
    mun1_2009 = saida.filter((pl.col("cod_municipio") == "1") & (pl.col("ano") == 2009))
    assert mun1_2009["ideb_anos_iniciais_publica"][0] == 6.0
    assert mun1_2009["ideb_anos_finais_publica"][0] == 5.0
    assert mun1_2009["ideb_ensino_medio_publica"][0] == 4.0

