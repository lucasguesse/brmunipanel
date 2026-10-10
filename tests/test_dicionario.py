import pytest
import polars as pl
from br_municipios_panel.metadata import dicionario, auditoria

def test_compute_statistics_tipos_nulos_vazios():
    df = pl.DataFrame({
        "num": [1, 2, None, 4],
        "txt": ["a", "b", "a", None],
        "bool_col": [True, False, None, True],
        "vazia": [None, None, None, None]
    }, schema={
        "num": pl.Int64,
        "txt": pl.Utf8,
        "bool_col": pl.Boolean,
        "vazia": pl.Float64
    })
    
    stats_num = dicionario.compute_statistics(df, "num")
    assert stats_num["nulos"] == 1
    assert stats_num["percentual_nulos"] == 25.0
    assert stats_num["minimo"] == "1"
    assert stats_num["maximo"] == "4"
    assert stats_num["dominio"] == ""
    
    stats_txt = dicionario.compute_statistics(df, "txt")
    assert stats_txt["nulos"] == 1
    assert stats_txt["minimo"] == ""
    assert stats_txt["maximo"] == ""
    assert stats_txt["dominio"] == "a, b"
    
    stats_bool = dicionario.compute_statistics(df, "bool_col")
    assert stats_bool["nulos"] == 1
    assert stats_bool["minimo"] == ""
    assert stats_bool["maximo"] == ""
    assert stats_bool["dominio"] == "false, true"
    
    stats_vazia = dicionario.compute_statistics(df, "vazia")
    assert stats_vazia["nulos"] == 4
    assert stats_vazia["percentual_nulos"] == 100.0
    assert stats_vazia["minimo"] == ""
    assert stats_vazia["maximo"] == ""
    assert stats_vazia["dominio"] == ""

def test_dominio_cardinalidade():
    # <= 35 should show, > 35 should hide
    df_small = pl.DataFrame({"txt": [str(i) for i in range(35)]}, schema={"txt": pl.Utf8})
    df_large = pl.DataFrame({"txt": [str(i) for i in range(36)]}, schema={"txt": pl.Utf8})
    
    stats_small = dicionario.compute_statistics(df_small, "txt")
    assert stats_small["dominio"] != ""
    
    stats_large = dicionario.compute_statistics(df_large, "txt")
    assert stats_large["dominio"] == ""

def test_build_dictionary():
    df = pl.DataFrame({
        "cod": ["1", "2"],
        "val": [10, 20]
    }, schema={"cod": pl.Utf8, "val": pl.Int64})
    
    meta = {
        "cod": {"descricao_pt": "Codigo", "descricao_en": "Code", "unidade": "ID", "fonte": "IBGE", "periodo": "2023", "nota_metodologica": ""},
        "val": {"descricao_pt": "Valor", "descricao_en": "Value", "unidade": "R$", "fonte": "N/A", "periodo": "2023", "nota_metodologica": ""}
    }
    
    dict_df = dicionario.build_table_dictionary(df, "teste", meta, ["cod"])
    assert dict_df.height == 2
    assert dict_df["chave"][0] == "Sim"
    assert dict_df["chave"][1] == "Não"
    
def test_metadado_ausente_orfaos():
    df = pl.DataFrame({"cod": ["1"], "falta": [10]})
    meta = {"cod": {}}
    
    with pytest.raises(ValueError, match="Metadado ausente para a coluna 'falta'"):
        dicionario.build_table_dictionary(df, "teste", meta, ["cod"])

def test_tabela_vazia():
    df = pl.DataFrame(schema={"cod": pl.Utf8, "val": pl.Int64})
    meta = {
        "cod": {"descricao_pt": "Codigo"},
        "val": {"descricao_pt": "Valor"}
    }
    dict_df = dicionario.build_table_dictionary(df, "teste", meta, ["cod"])
    assert dict_df.height == 2
    assert dict_df["nulos"][0] == 0
    assert dict_df["percentual_nulos"][0] == 0.0

def test_auditoria_resumo():
    df = pl.DataFrame({"cod": ["1", "2", "2"], "val": [10, None, 20], "ano": [2000, 2001, 2001]})
    res = auditoria.auditar_tabela_resumo(df, "teste", ["cod", "ano"])
    assert res["linhas"] == 3
    assert res["colunas"] == 3
    assert res["duplicatas_de_chave"] == 1
    assert res["ano_minimo"] == "2000"
    assert res["ano_maximo"] == "2001"
    assert res["celulas_nulas"] == 1
