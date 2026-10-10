import polars as pl
import pytest
from polars.testing import assert_frame_equal

from br_municipios_panel.painel import (
    montar_municipios,
    montar_despesa,
    montar_painel,
    montar_limitrofes,
    montar_educacao,
)

def test_montar_municipios():
    municipios = pl.DataFrame({
        "cod_municipio": ["1", "2", "3"],
        "nome": ["A", "B", "C"],
    })
    regioes = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "regiao": ["R1", "R2"],
    })
    
    saida = montar_municipios(municipios, regioes)
    
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "2", "3"],
        "nome": ["A", "B", "C"],
        "regiao": ["R1", "R2", None],
    })
    
    assert_frame_equal(saida, esperado)
    assert saida.columns == ["cod_municipio", "nome", "regiao"]

def test_montar_municipios_erros():
    # chave repetida nos municipios
    municipios_dup = pl.DataFrame({"cod_municipio": ["1", "1"]})
    regioes = pl.DataFrame({"cod_municipio": ["1"]})
    with pytest.raises(ValueError, match="municipios:.*chaves repetidas"):
        montar_municipios(municipios_dup, regioes)

    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    
    # código fora
    regioes = pl.DataFrame({"cod_municipio": ["3"]})
    with pytest.raises(ValueError, match="regioes_saude:.*códigos fora da tabela de municípios"):
        montar_municipios(municipios, regioes)
        
    # chave repetida
    regioes = pl.DataFrame({"cod_municipio": ["1", "1"]})
    with pytest.raises(ValueError, match="regioes_saude:.*chaves repetidas"):
        montar_municipios(municipios, regioes)
        
    # mesma coluna
    regioes = pl.DataFrame({"cod_municipio": ["1"], "nome": ["X"]})
    municipios = pl.DataFrame({"cod_municipio": ["1"], "nome": ["Y"]})
    with pytest.raises(ValueError, match="Coluna de mesmo nome"):
        montar_municipios(municipios, regioes)

def test_montar_despesa():
    finbra = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2010, 2011], dtype=pl.Int16),
        "v": [10.0, 11.0],
    })
    siconfi = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2013, 2013], dtype=pl.Int16),
        "v": [12.0, 13.0],
    })
    
    saida = montar_despesa(finbra, siconfi)
    
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "1", "1", "2"],
        "ano": pl.Series([2010, 2011, 2013, 2013], dtype=pl.Int16),
        "v": [10.0, 11.0, 12.0, 13.0],
    })
    
    assert_frame_equal(saida, esperado)

def test_montar_despesa_erros():
    finbra = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "v": [10.0],
    })
    
    # mesmo mun/ano
    siconfi = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "v": [12.0],
    })
    with pytest.raises(ValueError, match="casos do mesmo município e ano"):
        montar_despesa(finbra, siconfi)
        
    # esquemas diferentes (colunas em conjunto)
    siconfi = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2013], dtype=pl.Int16),
        "v2": [12.0],
    })
    with pytest.raises(ValueError, match="Colunas diferentes"):
        montar_despesa(finbra, siconfi)

    # ordem diferente das mesmas colunas
    siconfi_ordem = pl.DataFrame({
        "v": [12.0],
        "cod_municipio": ["1"],
        "ano": pl.Series([2013], dtype=pl.Int16),
    })
    with pytest.raises(ValueError, match="Colunas diferentes ou em ordem diferente"):
        montar_despesa(finbra, siconfi_ordem)
        
    # esquemas diferentes (tipos)
    siconfi = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2013], dtype=pl.Int16),
        "v": [12], # int
    })
    with pytest.raises(ValueError, match="Tipos diferentes"):
        montar_despesa(finbra, siconfi)

def test_montar_painel():
    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    anos = range(2010, 2012)
    
    f1 = pl.DataFrame({
        "cod_municipio": ["1", "2"],
        "ano": pl.Series([2010, 2011], dtype=pl.Int16),
        "v1": [1.0, 2.0],
    })
    # fora de ordem e sem o mun 2 em 2010
    # Adicionando um nulo nativo na fonte para distinguir do ausente no join
    f2 = pl.DataFrame({
        "cod_municipio": ["2", "1", "1"],
        "ano": pl.Series([2011, 2010, 2011], dtype=pl.Int16),
        "v2": ["A", "B", None],
    })
    
    saida = montar_painel(municipios, [f1, f2], anos=anos)
    
    assert saida.columns == ["cod_municipio", "ano", "v1", "v2"]
    assert len(saida) == 4
    
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "1", "2", "2"],
        "ano": pl.Series([2010, 2011, 2010, 2011], dtype=pl.Int16),
        "v1": [1.0, None, None, 2.0],
        "v2": ["B", None, None, "A"],
    })
    assert_frame_equal(saida, esperado)
    
    # 6. montar_painel, sem perda: comparando ambas as fontes
    # Filtrando as chaves que existem em f1
    painel_f1 = saida.join(f1.select(["cod_municipio", "ano"]), on=["cod_municipio", "ano"], how="inner").select(["cod_municipio", "ano", "v1"])
    assert_frame_equal(painel_f1.sort(["cod_municipio", "ano"]), f1.sort(["cod_municipio", "ano"]))

    # Filtrando as chaves que existem em f2
    painel_f2 = saida.join(f2.select(["cod_municipio", "ano"]), on=["cod_municipio", "ano"], how="inner").select(["cod_municipio", "ano", "v2"])
    assert_frame_equal(painel_f2.sort(["cod_municipio", "ano"]), f2.sort(["cod_municipio", "ano"]))

def test_montar_painel_erros():
    municipios = pl.DataFrame({"cod_municipio": ["1"]})
    anos = range(2010, 2012)
    
    # fonte com mun fora
    f = pl.DataFrame({"cod_municipio": ["2"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="fonte 0:.*códigos fora da tabela"):
        montar_painel(municipios, [f], anos=anos)
        
    # ano fora
    f = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2012], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="fonte 0:.*anos fora de anos"):
        montar_painel(municipios, [f], anos=anos)
        
    # chave repetida
    f = pl.DataFrame({"cod_municipio": ["1", "1"], "ano": pl.Series([2010, 2010], dtype=pl.Int16), "v": [1, 2]})
    with pytest.raises(ValueError, match="fonte 0:.*chaves repetidas"):
        montar_painel(municipios, [f], anos=anos)
        
    # coluna mesmo nome
    f1 = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    f2 = pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "v": [2]})
    with pytest.raises(ValueError, match="fonte 1: coluna com nome que outra fonte já trouxe"):
        montar_painel(municipios, [f1, f2], anos=anos)
        
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
    
    # par repetido
    lims = pl.DataFrame({"cod_municipio": ["1", "1"], "cod_municipio_limitrofe": ["2", "2"]})
    with pytest.raises(ValueError, match="limitrofes:.*pares repetidos"):
        montar_limitrofes(municipios, lims)
        
    # codigo fora (esquerda)
    lims = pl.DataFrame({"cod_municipio": ["3"], "cod_municipio_limitrofe": ["1"]})
    with pytest.raises(ValueError, match="limitrofes:.*códigos fora"):
        montar_limitrofes(municipios, lims)
        
    # codigo fora (direita)
    lims = pl.DataFrame({"cod_municipio": ["1"], "cod_municipio_limitrofe": ["3"]})
    with pytest.raises(ValueError, match="limitrofes:.*códigos fora"):
        montar_limitrofes(municipios, lims)

def test_montar_educacao():
    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    
    tabela = pl.DataFrame({
        "cod_municipio": ["2", "1", "1"],
        "ano": pl.Series([2000, 2024, 2000], dtype=pl.Int16),
        "categoria": ["A", "B", "A"],
        "v": [1.0, None, 2.0],
    })
    
    chave = ["cod_municipio", "ano", "categoria"]
    
    saida = montar_educacao(municipios, tabela, chave, "tabela_teste")
    
    esperado = pl.DataFrame({
        "cod_municipio": ["1", "1", "2"],
        "ano": pl.Series([2000, 2024, 2000], dtype=pl.Int16),
        "categoria": ["A", "B", "A"],
        "v": [2.0, None, 1.0],
    })
    
    assert_frame_equal(saida, esperado)

def test_montar_educacao_erros():
    municipios = pl.DataFrame({"cod_municipio": ["1", "2"]})
    
    tabela = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "categoria": ["A"],
    })
    chave = ["cod_municipio", "ano", "categoria"]
    
    # Coluna da chave ausente
    with pytest.raises(ValueError, match="tabela_teste: faltam colunas da chave na tabela"):
        montar_educacao(municipios, tabela, ["cod_municipio", "ano", "categoria", "extra"], "tabela_teste")
        
    # 'ano' ausente da chave
    with pytest.raises(ValueError, match="tabela_teste: cod_municipio e ano devem estar em chave"):
        montar_educacao(municipios, tabela, ["cod_municipio", "categoria"], "tabela_teste")
        
    # 'ano' nao e Int16
    tabela_ano_int = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": [2010], # Int64 por padrao
        "categoria": ["A"],
    })
    with pytest.raises(ValueError, match="tabela_teste: 'ano' não é Int16"):
        montar_educacao(municipios, tabela_ano_int, chave, "tabela_teste")
        
    # nulo na coluna da chave
    tabela_nulo = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "categoria": [None],
    })
    with pytest.raises(ValueError, match="tabela_teste: coluna da chave 'categoria' tem nulos"):
        montar_educacao(municipios, tabela_nulo, chave, "tabela_teste")
        
    # chave repetida
    tabela_dup = pl.DataFrame({
        "cod_municipio": ["1", "1"],
        "ano": pl.Series([2010, 2010], dtype=pl.Int16),
        "categoria": ["A", "A"],
    })
    with pytest.raises(ValueError, match="tabela_teste:.*chaves repetidas"):
        montar_educacao(municipios, tabela_dup, chave, "tabela_teste")
        
    # codigo fora da tabela
    tabela_fora = pl.DataFrame({
        "cod_municipio": ["3"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "categoria": ["A"],
    })
    with pytest.raises(ValueError, match="tabela_teste:.*códigos fora da tabela"):
        montar_educacao(municipios, tabela_fora, chave, "tabela_teste")
