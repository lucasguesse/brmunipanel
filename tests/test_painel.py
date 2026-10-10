import polars as pl
import pytest
from polars.testing import assert_frame_equal

from br_municipios_panel.painel import (
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

def test_montar_tabela_longitudinal_erros():
    municipios = pl.DataFrame({"cod_municipio": ["1"]})
    anos = range(2010, 2012)
    
    f = pl.DataFrame({"cod_municipio": ["2"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="teste .*códigos fora da tabela"):
        montar_tabela_longitudinal(municipios, [f], anos=anos, nome_tabela="teste")
        
    f = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2012], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="teste .*anos fora da janela"):
        montar_tabela_longitudinal(municipios, [f], anos=anos, nome_tabela="teste")
        
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

def test_consolidar_educacao():
    censo_escolar = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "escolas": [10, 20],
        "matriculas_infantil": [100, 200],
        "matriculas_fundamental": [1000, 2000],
        "matriculas_medio": [100, 200],
        "docentes_basica": [50, 100],
    })
    censo_superior = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "categoria": ["A", "A"],
        "instituicoes": [1, 2],
        "matriculas": [1000, 2000],
    })
    ideb = pl.DataFrame({
        "cod_municipio": ["2"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [5.5],
        "ideb_anos_finais_publica": [4.5],
        "ideb_ensino_medio_publica": [3.5],
    })
    
    saida = consolidar_educacao(censo_escolar, censo_superior, ideb)
    
    assert len(saida) == 2
    assert saida.columns == [
        "cod_municipio", "ano",
        "instituicoes_basica", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica",
        "instituicoes_superior", "matriculas_superior",
        "ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"
    ]
    
    # 1/2010 tem escolar e superior
    assert saida.filter(pl.col("cod_municipio") == "1")["instituicoes_basica"][0] == 30
    assert saida.filter(pl.col("cod_municipio") == "1")["instituicoes_superior"][0] == 1
    
    # 2/2010 tem superior e ideb, e nulo basica
    assert saida.filter(pl.col("cod_municipio") == "2")["instituicoes_superior"][0] == 2
    assert saida.filter(pl.col("cod_municipio") == "2")["instituicoes_basica"].is_null()[0]
