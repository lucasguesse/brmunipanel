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
    
    # 1/2010 tem escolar e superior
    assert saida.filter(pl.col("cod_municipio") == "1")["instituicoes_basica"][0] == 30
    assert saida.filter(pl.col("cod_municipio") == "1")["instituicoes_superior"][0] == 1
    
    # 2/2010 tem superior e ideb, e nulo basica
    assert saida.filter(pl.col("cod_municipio") == "2")["instituicoes_superior"][0] == 2
    assert saida.filter(pl.col("cod_municipio") == "2")["instituicoes_basica"].is_null()[0]
    
    # 3/2010 escolar integralmente nulo mantido como nulo, not zero
    assert saida.filter(pl.col("cod_municipio") == "3")["instituicoes_basica"].is_null()[0]

    # Município 4 (IDEB all nulls) was dropped during IDEB filtration, 
    # and has no entry in escolar/superior, so it doesn't appear
    assert len(saida.filter(pl.col("cod_municipio") == "4")) == 0

    # 5/2010 tem escolar
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
    
    # Invalid IDEB value
    ideb = pl.DataFrame({
        "cod_municipio": ["1"],
        "ano": pl.Series([2010], dtype=pl.Int16),
        "ideb_anos_iniciais_publica": [5.5], "ideb_anos_finais_publica": [4.5], "ideb_ensino_medio_publica": [11.0] # invalido
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
        "cod_municipio": [1], # inteiro em vez de string
        "ano": pl.Series([2010], dtype=pl.Int16),
        "dependencia": ["Estadual"], "localizacao": ["Urbana"],
        "escolas": [10], "matriculas_infantil": [100], "matriculas_fundamental": [1000], "matriculas_medio": [100], "docentes_basica": [50]
    })
    with pytest.raises(ValueError, match="censo_escolar: cod_municipio deve ser String"):
        consolidar_educacao(escolar_bad_type, censo_superior, ideb)

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
    
    # 2000 is filtered out for superior and ideb (only 2006-2023)
    # but escolar is not filtered explicitly in consolidar_educacao, 
    # wait, escolar doesn't filter year in the function? Let's check `consolidar_educacao`. It doesn't. 
    # But for superior and ideb it filters.
    assert len(saida.filter(pl.col("ano") == 2000).drop_nulls(subset=["instituicoes_superior"])) == 0
    assert len(saida.filter(pl.col("ano") == 2000).drop_nulls(subset=["ideb_anos_iniciais_publica"])) == 0
    
    assert saida.filter(pl.col("ano") == 2010)["instituicoes_superior"][0] == 2
    assert saida.filter(pl.col("ano") == 2010)["ideb_anos_iniciais_publica"][0] == 6.0

import sys
import importlib
from pathlib import Path
import tempfile
import os
import unittest.mock as mock

def test_consolidar_saidas(tmp_path):
    # Mocking run_pipeline._consolidar
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir.parent))
    
    spec = importlib.util.spec_from_file_location("run_pipeline", scripts_dir / "run_pipeline.py")
    run_pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_pipeline)
    
    # Mock paths
    intermediario = tmp_path / "intermediate"
    processado = tmp_path / "processed"
    intermediario.mkdir()
    processado.mkdir()
    
    # Create required intermediate inputs
    arquivos = {
        "ibge_municipios.parquet": pl.DataFrame({"cod_municipio": ["1", "2"], "nome_municipio": ["A", "B"], "cod_uf": [1, 2], "sigla_uf": ["UF", "UF"], "nome_uf": ["Estado", "Estado"], "nome_rg_intermediaria": ["RI", "RI"], "nome_rg_imediata": ["RI", "RI"], "fronteira_internacional": [0, 1], "litoraneo": [1, 0], "area_km2": [10.0, 20.0], "latitude_sede": [-10.0, -20.0], "longitude_sede": [-30.0, -40.0]}),
        "ibge_municipios_limitrofes.parquet": pl.DataFrame({"cod_municipio": ["1"], "cod_municipio_limitrofe": ["2"]}),
        "ibge_populacao.parquet": pl.DataFrame({"cod_municipio": ["1", "2"], "ano": pl.Series([2010, 2010], dtype=pl.Int16), "populacao": [100, 200], "pop_origem": ["a", "b"]}),
        "ibge_pib.parquet": pl.DataFrame({"cod_municipio": ["1", "2"], "ano": pl.Series([2010, 2010], dtype=pl.Int16), "pib": [1.0, 2.0]}),
        "ibge_cempre.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "unidades_locais": [1], "pessoal_ocupado_total": [1], "pessoal_ocupado_assalariado": [1], "pessoal_assalariado_medio": [1.0], "salarios_mil_reais": [1.0]}),
        "tesouro_despesa_funcao_finbra.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2006], dtype=pl.Int16), "desp_01_legislativa": [1.0]}),
        "tesouro_despesa_funcao_siconfi.parquet": pl.DataFrame({"cod_municipio": ["2"], "ano": pl.Series([2014], dtype=pl.Int16), "desp_01_legislativa": [2.0]}),
        "ipea_pbf.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "pbf_beneficios": [10], "pbf_valor_mil_reais": [100.0]}),
        "datasus_saude.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "leitos_internacao": [10], "leitos_uti": [1], "equipamentos_imagem": [1], "medicos": [10], "unidades_basicas": [1], "postos_saude": [1], "obitos_agressao": [1], "obitos_infantis": [1], "nascidos_vivos": [10]}),
        "inep_censo_escolar.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "dependencia": ["E"], "localizacao": ["U"], "escolas": [1], "matriculas_infantil": [1], "matriculas_fundamental": [1], "matriculas_medio": [1], "docentes_basica": [1]}),
        "inep_censo_superior.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "categoria": ["A"], "instituicoes": [1], "matriculas": [1]}),
        "inep_ideb.parquet": pl.DataFrame({"cod_municipio": ["1"], "ano": pl.Series([2010], dtype=pl.Int16), "ideb_anos_iniciais_publica": [5.0], "ideb_anos_finais_publica": [4.0], "ideb_ensino_medio_publica": [3.0]}),
    }
    for f, df in arquivos.items():
        df.write_parquet(intermediario / f)
        
    # Create some obsolete and unmanaged files
    (processado / "painel.parquet").touch()
    (processado / "censo_escolar.parquet").touch()
    (processado / "censo_superior.parquet").touch()
    (processado / "nao_gerenciado.txt").touch()

    # Mock ANOS_PAINEL to limit test duration and dimensions
    with mock.patch("br_municipios_panel.painel.ANOS_PAINEL", [2006, 2010, 2014]):
        old_inter = run_pipeline.INTERMEDIARIO
        old_proc = run_pipeline.PROCESSADO
        old_proj = run_pipeline.PROJETO
        run_pipeline.INTERMEDIARIO = intermediario
        run_pipeline.PROCESSADO = processado
        run_pipeline.PROJETO = tmp_path
        try:
            run_pipeline._consolidar()
        finally:
            run_pipeline.INTERMEDIARIO = old_inter
            run_pipeline.PROCESSADO = old_proc
            run_pipeline.PROJETO = old_proj
            
    # Check outputs
    saidas = {f.name for f in processado.iterdir()}
    
    # 6 valid outputs + 1 unmanaged
    assert "municipios.parquet" in saidas
    assert "municipios_limitrofes.parquet" in saidas
    assert "demografia_economia_social.parquet" in saidas
    assert "financas_publicas.parquet" in saidas
    assert "saude.parquet" in saidas
    assert "educacao.parquet" in saidas
    
    assert "nao_gerenciado.txt" in saidas
    
    # Obsolete ones should be removed
    assert "painel.parquet" not in saidas
    assert "censo_escolar.parquet" not in saidas
    assert "censo_superior.parquet" not in saidas
    assert "assistencia_social.parquet" not in saidas
    
    # Check schemas
    financas = pl.read_parquet(processado / "financas_publicas.parquet")
    assert "desp_legislativa" in financas.columns
    assert "desp_01_legislativa" not in financas.columns
    
    demo = pl.read_parquet(processado / "demografia_economia_social.parquet")
    assert "populacao" in demo.columns
    assert "pop_origem" not in demo.columns
