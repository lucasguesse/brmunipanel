"""Testes do módulo brmunipanel.ibge.territorio."""

from __future__ import annotations

import io
import sqlite3
import zipfile

import pandas as pd
import polars as pl
import pytest

from brmunipanel.ibge import territorio
from brmunipanel.nucleo import RespostaInvalida


def test_validar_dtb() -> None:
    # Válido: zip contendo o relatório de municípios
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("RELATORIO_DTB_BRASIL_2025_MUNICIPIOS.xls", b"dados falsos")
    territorio.validar_dtb(buf.getvalue())

    # Inválido: não é zip
    with pytest.raises(RespostaInvalida, match="inválido"):
        territorio.validar_dtb(b"conteudo nao zip")

    # Inválido: zip sem o arquivo esperado
    buf_vazio = io.BytesIO()
    with zipfile.ZipFile(buf_vazio, "w") as zf:
        zf.writestr("outro_arquivo.txt", b"foo")
    with pytest.raises(RespostaInvalida, match="não encontrado"):
        territorio.validar_dtb(buf_vazio.getvalue())


def test_validar_localidades() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BR_localidades_2022.gpkg", b"sqlite")
    territorio.validar_localidades(buf.getvalue())
    
    with pytest.raises(RespostaInvalida, match="inválido"):
        territorio.validar_localidades(b"nao zip")
        
    buf_vazio = io.BytesIO()
    with zipfile.ZipFile(buf_vazio, "w") as zf:
        zf.writestr("outro.txt", b"foo")
    with pytest.raises(RespostaInvalida, match="não encontrado"):
        territorio.validar_localidades(buf_vazio.getvalue())


def test_validar_limitrofes() -> None:
    # Válido: assinatura OLE
    territorio.validar_limitrofes(b"\xd0\xcf\x11\xe0cabecalho_ole")

    # Inválido: outra assinatura
    with pytest.raises(RespostaInvalida, match="Assinatura OLE"):
        territorio.validar_limitrofes(b"PK\x03\x04zip")


def test_processar_areas_df() -> None:
    df_raw = pd.DataFrame({
        "CD_MUN": ["1100015", "4300001", "", "OBS:", "3550308", "ABCDEFG"],
        "AR_MUN_2025": ["100.5", "200.0", "", "qualquer", "1522.683", "100.5"]
    })
    areas = territorio.processar_areas_df(df_raw)
    assert areas == {"1100015": 100.5, "4300001": 200.0, "3550308": 1522.683}

    df_repetido = pd.DataFrame({
        "CD_MUN": ["1100015", "1100015"],
        "AR_MUN_2025": ["100.5", "100.5"]
    })
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_areas_df(df_repetido)

    df_invalido = pd.DataFrame({
        "CD_MUN": ["1100015"],
        "AR_MUN_2025": ["nao_numero"]
    })
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_areas_df(df_invalido)

    df_vazio1 = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": [None]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_areas_df(df_vazio1)
        
    df_vazio2 = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": [float("nan")]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_areas_df(df_vazio2)

    df_vazio3 = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": [""]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_areas_df(df_vazio3)

    df_nan_str = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": ["nan"]})
    with pytest.raises(ValueError, match="NaN.*1100015"):
        territorio.processar_areas_df(df_nan_str)


def test_processar_sedes_df() -> None:
    df_raw = pd.DataFrame({
        "CD_MUN": ["1100015", "1100205", "1100205", "5300108", "2605459", "1100015", "5300108"],
        "CT_LOCALIDADE": ["Cidade", "Cidade", "Cidade", "Cidade", "Distrito Estadual de Fernando de Noronha", "Povoado", "Regiões Administrativas do Distrito Federal"],
        "LAT_LOCALIDADE": [-11.932999610900879, -9.646200180053711, -9.646200180053711, -15.784299850463867, -3.841300010681152, -12.5, -15.9],
        "LONG_LOCALIDADE": [-62.003700256347656, -63.95989990234375, -63.95989990234375, -47.90810012817383, -32.4109001159668, -62.5, -48.0]
    })
    sedes = territorio.processar_sedes_df(df_raw)
    assert sedes == {"1100015": (-11.933, -62.0037), "1100205": (-9.6462, -63.9599), "5300108": (-15.7843, -47.9081), "2605459": (-3.8413, -32.4109)}


def test_processar_sedes_df_erros() -> None:
    # 1. Duas linhas diferentes
    df1 = pd.DataFrame({"CD_MUN": ["1100205", "1100205"], "CT_LOCALIDADE": ["Cidade", "Cidade"], "LAT_LOCALIDADE": [-9.6462, -9.7], "LONG_LOCALIDADE": [-63.9599, -63.9599]})
    with pytest.raises(ValueError, match="1100205"):
        territorio.processar_sedes_df(df1)
        
    # 2. Latitude None
    df2 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [None], "LONG_LOCALIDADE": [-62.0037]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_sedes_df(df2)
        
    # 3. Longitude NaN
    df3 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [-11.933], "LONG_LOCALIDADE": [float("nan")]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_sedes_df(df3)
        
    # 4. Latitude texto
    df4 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": ["abc"], "LONG_LOCALIDADE": [-62.0037]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_sedes_df(df4)
        
    # 5. Coordenada trocada
    df5 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [62.0037], "LONG_LOCALIDADE": [-11.933]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_sedes_df(df5)
        
    # 6. Fora do limite
    df6 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [-11.933], "LONG_LOCALIDADE": [-20.0]})
    with pytest.raises(ValueError, match="1100015"):
        territorio.processar_sedes_df(df6)
        
    # 7. Código menor
    df7 = pd.DataFrame({"CD_MUN": ["110001"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [-11.933], "LONG_LOCALIDADE": [-62.0037]})
    with pytest.raises(ValueError, match="110001"):
        territorio.processar_sedes_df(df7)


def test_processar_dtb_df() -> None:
    # DataFrame simulando estrutura lida da DTB
    df_raw = pd.DataFrame({
        "UF": ["11", "35", "53"],
        "Nome_UF": ["Rondônia", "São Paulo", "Distrito Federal"],
        "Região Geográfica Intermediária": ["1101", "3501", "5301"],
        "Nome Região Geográfica Intermediária": ["Porto Velho", "São Paulo", "Distrito Federal"],
        "Região Geográfica Imediata": ["110001", "350001", "530001"],
        "Nome Região Geográfica Imediata": ["Porto Velho", "São Paulo", "Distrito Federal"],
        "Município": ["00015", "50308", "0108"],
        "Código Município Completo": ["1100015", "3550308", "5300108"],
        "Nome_Município": ["Alta Floresta D'Oeste", "São Paulo", "Brasília"],
    })

    fronteira = {"1100015"}
    litoral = {"3550308"}
    areas = {"1100015": 100.5, "3550308": 1522.683}

    res = territorio.processar_dtb_df(df_raw, fronteira, litoral, areas=areas, sedes={"1100015": (-11.933, -62.0037), "3550308": (-23.5548, -46.579)})

    # 1. Esquema
    colunas_esperadas = [
        "cod_municipio", "cod_municipio_6", "nome_municipio", "cod_uf", "sigla_uf", "nome_uf",
        "cod_rg_intermediaria", "nome_rg_intermediaria", "cod_rg_imediata", "nome_rg_imediata",
        "fronteira_internacional", "litoraneo", "area_km2", "latitude_sede", "longitude_sede"
    ]
    assert res.columns == colunas_esperadas
    assert res.columns[12] == "area_km2"
    assert res.schema == {
        "cod_municipio": pl.String,
        "cod_municipio_6": pl.String,
        "nome_municipio": pl.String,
        "cod_uf": pl.String,
        "sigla_uf": pl.String,
        "nome_uf": pl.String,
        "cod_rg_intermediaria": pl.String,
        "nome_rg_intermediaria": pl.String,
        "cod_rg_imediata": pl.String,
        "nome_rg_imediata": pl.String,
        "fronteira_internacional": pl.Boolean,
        "litoraneo": pl.Boolean,
        "area_km2": pl.Float64,
        "latitude_sede": pl.Float64,
        "longitude_sede": pl.Float64,
    }

    # 2. Derivação do código de 6 dígitos
    assert res["cod_municipio_6"].to_list() == ["110001", "355030", "530010"]

    # 3. Siglas de UF mapeadas
    assert res["sigla_uf"].to_list() == ["RO", "SP", "DF"]

    # 4. Flags de fronteira e litoral
    assert res.filter(pl.col("cod_municipio") == "1100015")["fronteira_internacional"][0] is True
    assert res.filter(pl.col("cod_municipio") == "1100015")["litoraneo"][0] is False

    assert res.filter(pl.col("cod_municipio") == "3550308")["fronteira_internacional"][0] is False
    assert res.filter(pl.col("cod_municipio") == "3550308")["litoraneo"][0] is True

    assert res.filter(pl.col("cod_municipio") == "5300108")["fronteira_internacional"][0] is False
    assert res.filter(pl.col("cod_municipio") == "5300108")["litoraneo"][0] is False
    
    # 5. Áreas
    assert res.filter(pl.col("cod_municipio") == "1100015")["area_km2"][0] == 100.5
    assert res.filter(pl.col("cod_municipio") == "5300108")["area_km2"][0] is None
    
    # 6. Sem areas
    res_sem_area = territorio.processar_dtb_df(df_raw, fronteira, litoral)
    assert res_sem_area["area_km2"].null_count() == 3

    assert res.columns[-2:] == ["latitude_sede", "longitude_sede"]
    assert res.filter(pl.col("cod_municipio") == "1100015")["latitude_sede"][0] == -11.933
    assert res.filter(pl.col("cod_municipio") == "1100015")["longitude_sede"][0] == -62.0037
    assert res.filter(pl.col("cod_municipio") == "5300108")["latitude_sede"][0] is None
    assert res.filter(pl.col("cod_municipio") == "5300108")["longitude_sede"][0] is None
    assert res_sem_area["latitude_sede"].null_count() == 3
    assert res_sem_area["longitude_sede"].null_count() == 3


def test_processar_limitrofes_df() -> None:
    df_raw = pd.DataFrame({
        "CD_MUN": ["1100015", "1100379", "2605459", "4300001", "1100015"],
        "NM_MUN": ["Alta Floresta D'Oeste", "Alto Alegre dos Parecis", "Fernando de Noronha", "Lagoa Mirim", "Alta Floresta D'Oeste"],
        "N_LIM": ["2", "1", "0", "1", "2"],
        "CD_LIM": ["1100379", "1100015", None, "1100015", "4300001"],
        "NM_LIM": ["Alto Alegre dos Parecis", "Alta Floresta D'Oeste", None, "Alta Floresta D'Oeste", "Lagoa Mirim"],
        "COMP_KM": ["191.181", "191.181", None, "50.0", "50.0"],
    })

    codigos_dtb = {"1100015", "1100379", "2605459"}

    res = territorio.processar_limitrofes_df(df_raw, codigos_municipios=codigos_dtb)

    assert res.schema == {
        "cod_municipio": pl.String,
        "cod_municipio_limitrofe": pl.String,
        "comprimento_km": pl.Float64,
    }

    # 1. Sem vizinho (2605459) e pares com código fora da DTB (4300001) retirados
    assert res.height == 2
    assert set(res["cod_municipio"]) == {"1100015", "1100379"}
    assert set(res["cod_municipio_limitrofe"]) == {"1100015", "1100379"}

    # 2. Sem nulos
    assert res["cod_municipio"].null_count() == 0
    assert res["cod_municipio_limitrofe"].null_count() == 0
    assert res["comprimento_km"].null_count() == 0


def test_ler_sedes(tmp_path) -> None:
    db_path = tmp_path / "teste_localidades.gpkg"
    con = sqlite3.connect(db_path)
    try:
        con.execute('CREATE TABLE "BR_localidades_2022" (CD_MUN TEXT, NM_MUN TEXT, CT_LOCALIDADE TEXT, SCT_LOCALIDADE TEXT, LAT_LOCALIDADE REAL, LONG_LOCALIDADE REAL)')
        con.execute('INSERT INTO "BR_localidades_2022" VALUES (?, ?, ?, ?, ?, ?)', ("1100015", "Alta Floresta", "Cidade", "Sede", -11.932999610900879, -62.003700256347656))
        con.execute('INSERT INTO "BR_localidades_2022" VALUES (?, ?, ?, ?, ?, ?)', ("1100015", "Alta Floresta", "Povoado", "", -12.5, -62.5))
        con.execute('INSERT INTO "BR_localidades_2022" VALUES (?, ?, ?, ?, ?, ?)', ("2605459", "Fernando", "Distrito Estadual de Fernando de Noronha", "", -3.841300010681152, -32.4109001159668))
        con.commit()
    finally:
        con.close()
    
    banco = db_path.read_bytes()
    
    with zipfile.ZipFile(tmp_path / "Localidades_Brasil_gpkg.zip", "w") as zf:
        zf.writestr("BR_localidades_2022.gpkg", banco)
        
    sedes = territorio.ler_sedes(tmp_path)
    assert sedes == {"1100015": (-11.933, -62.0037), "2605459": (-3.8413, -32.4109)}
