import pytest
import polars as pl
import pandas as pd
from pathlib import Path
from brmunipanel.inep.ideb import harmonizar, _ler_planilha, _encontrar_linha_cabecalho
import hashlib

def test_encontrar_cabecalho(tmp_path):
    df_fake = pd.DataFrame({
        0: ["info1", "info2", "SG_UF", "SP"],
        1: ["x", "y", "CO_MUNICIPIO", "3550308"]
    })
    caminho = tmp_path / "fake.xlsx"
    df_fake.to_excel(caminho, index=False, header=False)
    
    assert _encontrar_linha_cabecalho(caminho) == 2

    # Header not found (total absence)
    df_err = pd.DataFrame({0: ["info1"], 1: ["x"]})
    df_err.to_excel(tmp_path / "err.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Cabeçalho não encontrado"):
        _encontrar_linha_cabecalho(tmp_path / "err.xlsx")
        
    # Header not found (has CO_MUNICIPIO but does not have SG_UF)
    df_err2 = pd.DataFrame({0: ["info1", "info2"], 1: ["CO_MUNICIPIO", "3550308"]})
    df_err2.to_excel(tmp_path / "err2.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Cabeçalho não encontrado"):
        _encontrar_linha_cabecalho(tmp_path / "err2.xlsx")

def test_harmonizar_sucesso(tmp_path):
    valid_mun = pl.DataFrame({"cod_municipio": ["1100015", "3550308", "3304557"]})
    
    for etapa in ["anos_iniciais", "anos_finais", "ensino_medio"]:
        pasta_etapa = tmp_path / etapa
        pasta_etapa.mkdir()
        
        # Create synthetic data for each stage
        df = pd.DataFrame([
            {"bla": "info"},
            {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "NO_MUNICIPIO": "NO_MUNICIPIO", "REDE": "REDE", 
             "VL_OBSERVADO_2005": "VL_OBSERVADO_2005", "VL_OBSERVADO_2007": "VL_OBSERVADO_2007"},
            {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "NO_MUNICIPIO": "Alta Floresta", "REDE": "Pública",
             "VL_OBSERVADO_2005": "4,5" if etapa == "anos_iniciais" else "-", 
             "VL_OBSERVADO_2007": "4.8"}, # decimal dot
            {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "NO_MUNICIPIO": "Alta Floresta", "REDE": "Estadual",
             "VL_OBSERVADO_2005": "5.0", "VL_OBSERVADO_2007": "5.0"}, # Should be ignored (does not sum networks)
            {"SG_UF": "SP", "CO_MUNICIPIO": "3550308", "NO_MUNICIPIO": "São Paulo", "REDE": "Pública",
             "VL_OBSERVADO_2005": "ND", "VL_OBSERVADO_2007": "ND*"},
            {"SG_UF": "RJ", "CO_MUNICIPIO": "3304557", "NO_MUNICIPIO": "Rio de Janeiro", "REDE": "Pública",
             "VL_OBSERVADO_2005": "ND***", "VL_OBSERVADO_2007": None} # empty as null
        ])
        caminho = pasta_etapa / "arquivo.xlsx"
        df.to_excel(caminho, index=False, header=False)
        
    res = harmonizar(tmp_path, valid_mun)
    
    assert res.height == 6 # 3 municipalities * 2 years
    assert res.columns == [
        "cod_municipio", "ano", 
        "ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"
    ]
    
    assert res.schema["cod_municipio"] == pl.Utf8
    assert res.schema["ano"] == pl.Int16
    assert res.schema["ideb_anos_iniciais_publica"] == pl.Float64
    
    # Order and sorting
    municipios = res["cod_municipio"].to_list()
    anos = res["ano"].to_list()
    assert municipios == sorted(municipios)
    assert anos[:2] == [2005, 2007] # Each municipality must have 2005 and 2007 in order
    
    # 1100015 in 2005
    linha_1100015_2005 = res.filter((pl.col("cod_municipio") == "1100015") & (pl.col("ano") == 2005))
    assert linha_1100015_2005["ideb_anos_iniciais_publica"][0] == 4.5
    assert linha_1100015_2005["ideb_anos_finais_publica"][0] is None # Was "-"
    assert linha_1100015_2005["ideb_ensino_medio_publica"][0] is None
    
    # 1100015 in 2007 decimal dot
    linha_1100015_2007 = res.filter((pl.col("cod_municipio") == "1100015") & (pl.col("ano") == 2007))
    assert linha_1100015_2007["ideb_anos_iniciais_publica"][0] == 4.8
    
    # 3550308 in 2005 and 2007 (ND and ND*)
    linha_3550308 = res.filter(pl.col("cod_municipio") == "3550308")
    assert linha_3550308["ideb_anos_iniciais_publica"][0] is None
    assert linha_3550308["ideb_anos_iniciais_publica"][1] is None
    
    # 3304557 in 2005 and 2007 (ND*** and None)
    linha_3304557 = res.filter(pl.col("cod_municipio") == "3304557")
    assert linha_3304557["ideb_anos_iniciais_publica"][0] is None
    assert linha_3304557["ideb_anos_iniciais_publica"][1] is None

    # Determinism of parquet writing
    p1 = tmp_path / "out1.parquet"
    p2 = tmp_path / "out2.parquet"
    res.write_parquet(p1)
    res.write_parquet(p2)
    assert hashlib.sha256(p1.read_bytes()).hexdigest() == hashlib.sha256(p2.read_bytes()).hexdigest()

def test_uniao_externa(tmp_path):
    valid_mun = pl.DataFrame({"cod_municipio": ["1100015", "3550308", "3304557"]})
    
    # anos_iniciais: has only 1100015
    pasta = tmp_path / "anos_iniciais"
    pasta.mkdir()
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "REDE": "Pública", "VL_OBSERVADO_2005": "4.5"},
    ])
    df.to_excel(pasta / "a.xlsx", index=False, header=False)

    # anos_finais: has only 3550308
    pasta = tmp_path / "anos_finais"
    pasta.mkdir()
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "3550308", "REDE": "Pública", "VL_OBSERVADO_2005": "4.8"},
    ])
    df.to_excel(pasta / "b.xlsx", index=False, header=False)

    # ensino_medio: has only 3304557
    pasta = tmp_path / "ensino_medio"
    pasta.mkdir()
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "RJ", "CO_MUNICIPIO": "3304557", "REDE": "Pública", "VL_OBSERVADO_2005": "4.2"},
    ])
    df.to_excel(pasta / "c.xlsx", index=False, header=False)

    res = harmonizar(tmp_path, valid_mun)
    
    assert res.height == 3
    
    linha1 = res.filter(pl.col("cod_municipio") == "1100015")
    assert linha1["ideb_anos_iniciais_publica"][0] == 4.5
    assert linha1["ideb_anos_finais_publica"][0] is None
    assert linha1["ideb_ensino_medio_publica"][0] is None

    linha2 = res.filter(pl.col("cod_municipio") == "3550308")
    assert linha2["ideb_anos_iniciais_publica"][0] is None
    assert linha2["ideb_anos_finais_publica"][0] == 4.8
    assert linha2["ideb_ensino_medio_publica"][0] is None

    linha3 = res.filter(pl.col("cod_municipio") == "3304557")
    assert linha3["ideb_anos_iniciais_publica"][0] is None
    assert linha3["ideb_anos_finais_publica"][0] is None
    assert linha3["ideb_ensino_medio_publica"][0] == 4.2


def test_erros_diversos(tmp_path):
    valid_mun = pl.DataFrame({"cod_municipio": ["1100015"]})
    pasta = tmp_path / "anos_iniciais"
    
    # 1. Missing folder
    with pytest.raises(FileNotFoundError, match="Pasta da etapa não encontrada"):
        harmonizar(tmp_path, valid_mun)
        
    pasta.mkdir()
    
    # 2. Missing file
    with pytest.raises(FileNotFoundError, match="Nenhum .xlsx encontrado"):
        harmonizar(tmp_path, valid_mun)
        
    # 3. Multiple files
    (pasta / "a.xlsx").touch()
    (pasta / "b.xlsx").touch()
    with pytest.raises(ValueError, match="Mais de um arquivo .xlsx"):
        harmonizar(tmp_path, valid_mun)
        
    (pasta / "b.xlsx").unlink()
    
    # 4. Missing column (REDE)
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "3550308"}
    ])
    df.to_excel(pasta / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Coluna REDE ausente"):
        harmonizar(tmp_path, valid_mun)
        
    # 5. Missing public network
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "3550308", "REDE": "Estadual"}
    ])
    df.to_excel(pasta / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Rede 'Pública' não encontrada"):
        harmonizar(tmp_path, valid_mun)

    # 6. Missing value column
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "1100015", "REDE": "Pública"}
    ])
    df.to_excel(pasta / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Nenhuma coluna VL_OBSERVADO_AAAA encontrada"):
        harmonizar(tmp_path, valid_mun)
        
    # 7. Municipality outside registry
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "9999999", "REDE": "Pública", "VL_OBSERVADO_2005": "5.0"}
    ])
    df.to_excel(pasta / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="fora do cadastro municipal"):
        harmonizar(tmp_path, valid_mun)

    # 8. Duplicate key
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "REDE": "Pública", "VL_OBSERVADO_2005": "5.0"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "REDE": "Pública", "VL_OBSERVADO_2005": "5.0"}
    ])
    df.to_excel(pasta / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="duplicada encontrada"):
        # Need to create the other folders so it does not fail before full join/harmonize
        (tmp_path / "anos_finais").mkdir()
        (tmp_path / "ensino_medio").mkdir()
        df.to_excel(tmp_path / "anos_finais" / "b.xlsx", index=False, header=False)
        df.to_excel(tmp_path / "ensino_medio" / "c.xlsx", index=False, header=False)
        harmonizar(tmp_path, valid_mun)
