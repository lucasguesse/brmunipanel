"""Tests for the brmunipanel.ibge.territory module."""

from __future__ import annotations

import io
import sqlite3
import zipfile

import pandas as pd
import polars as pl
import pytest

from brmunipanel.ibge import territory
from brmunipanel.core import InvalidResponse


def test_validate_dtb() -> None:
    # Valid: zip containing municipalities report
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("RELATORIO_DTB_BRASIL_2025_MUNICIPIOS.xls", b"dados falsos")
    territory.validate_dtb(buf.getvalue())

    # Invalid: not a zip
    with pytest.raises(InvalidResponse, match="Invalid"):
        territory.validate_dtb(b"conteudo nao zip")

    # Invalid: zip without expected file
    empty_buf = io.BytesIO()
    with zipfile.ZipFile(empty_buf, "w") as zf:
        zf.writestr("other_file.txt", b"foo")
    with pytest.raises(InvalidResponse, match="not found"):
        territory.validate_dtb(empty_buf.getvalue())


def test_validate_localities() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BR_localidades_2022.gpkg", b"sqlite")
    territory.validate_localities(buf.getvalue())
    
    with pytest.raises(InvalidResponse, match="Invalid"):
        territory.validate_localities(b"nao zip")
        
    empty_buf = io.BytesIO()
    with zipfile.ZipFile(empty_buf, "w") as zf:
        zf.writestr("outro.txt", b"foo")
    with pytest.raises(InvalidResponse, match="not found"):
        territory.validate_localities(empty_buf.getvalue())


def test_validate_neighboring() -> None:
    # Valid: OLE signature
    territory.validate_neighboring(b"\xd0\xcf\x11\xe0cabecalho_ole")

    # Invalid: another signature
    with pytest.raises(InvalidResponse, match="OLE signature"):
        territory.validate_neighboring(b"PK\x03\x04zip")


def test_process_areas_df() -> None:
    df_raw = pd.DataFrame({
        "CD_MUN": ["1100015", "4300001", "", "OBS:", "3550308", "ABCDEFG"],
        "AR_MUN_2025": ["100.5", "200.0", "", "qualquer", "1522.683", "100.5"]
    })
    areas = territory.process_areas_df(df_raw)
    assert areas == {"1100015": 100.5, "4300001": 200.0, "3550308": 1522.683}

    repeated_df = pd.DataFrame({
        "CD_MUN": ["1100015", "1100015"],
        "AR_MUN_2025": ["100.5", "100.5"]
    })
    with pytest.raises(ValueError, match="1100015"):
        territory.process_areas_df(repeated_df)

    invalid_df = pd.DataFrame({
        "CD_MUN": ["1100015"],
        "AR_MUN_2025": ["nao_numero"]
    })
    with pytest.raises(ValueError, match="1100015"):
        territory.process_areas_df(invalid_df)

    df_empty1 = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": [None]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_areas_df(df_empty1)
        
    df_empty2 = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": [float("nan")]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_areas_df(df_empty2)

    df_empty3 = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": [""]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_areas_df(df_empty3)

    df_nan_str = pd.DataFrame({"CD_MUN": ["1100015"], "AR_MUN_2025": ["nan"]})
    with pytest.raises(ValueError, match="NaN.*1100015"):
        territory.process_areas_df(df_nan_str)


def test_process_geoloc_df() -> None:
    df_raw = pd.DataFrame({
        "CD_MUN": ["1100015", "1100205", "1100205", "5300108", "2605459", "1100015", "5300108"],
        "CT_LOCALIDADE": ["Cidade", "Cidade", "Cidade", "Cidade", "Distrito Estadual de Fernando de Noronha", "Povoado", "Regiões Administrativas do Distrito Federal"],
        "LAT_LOCALIDADE": [-11.932999610900879, -9.646200180053711, -9.646200180053711, -15.784299850463867, -3.841300010681152, -12.5, -15.9],
        "LONG_LOCALIDADE": [-62.003700256347656, -63.95989990234375, -63.95989990234375, -47.90810012817383, -32.4109001159668, -62.5, -48.0]
    })
    geoloc = territory.process_geoloc_df(df_raw)
    assert geoloc == {"1100015": (-11.933, -62.0037), "1100205": (-9.6462, -63.9599), "5300108": (-15.7843, -47.9081), "2605459": (-3.8413, -32.4109)}


def test_process_geoloc_df_errors() -> None:
    # 1. Two different rows
    df1 = pd.DataFrame({"CD_MUN": ["1100205", "1100205"], "CT_LOCALIDADE": ["Cidade", "Cidade"], "LAT_LOCALIDADE": [-9.6462, -9.7], "LONG_LOCALIDADE": [-63.9599, -63.9599]})
    with pytest.raises(ValueError, match="1100205"):
        territory.process_geoloc_df(df1)
        
    # 2. Latitude None
    df2 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [None], "LONG_LOCALIDADE": [-62.0037]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_geoloc_df(df2)
        
    # 3. Longitude NaN
    df3 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [-11.933], "LONG_LOCALIDADE": [float("nan")]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_geoloc_df(df3)
        
    # 4. String latitude
    df4 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": ["abc"], "LONG_LOCALIDADE": [-62.0037]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_geoloc_df(df4)
        
    # 5. Swapped coordinates
    df5 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [62.0037], "LONG_LOCALIDADE": [-11.933]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_geoloc_df(df5)
        
    # 6. Out of bounds
    df6 = pd.DataFrame({"CD_MUN": ["1100015"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [-11.933], "LONG_LOCALIDADE": [-20.0]})
    with pytest.raises(ValueError, match="1100015"):
        territory.process_geoloc_df(df6)
        
    # 7. Shorter code
    df7 = pd.DataFrame({"CD_MUN": ["110001"], "CT_LOCALIDADE": ["Cidade"], "LAT_LOCALIDADE": [-11.933], "LONG_LOCALIDADE": [-62.0037]})
    with pytest.raises(ValueError, match="110001"):
        territory.process_geoloc_df(df7)


def test_process_dtb_df() -> None:
    # DataFrame simulating structure read from DTB
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

    border = {"1100015"}
    coastal = {"3550308"}
    areas = {"1100015": 100.5, "3550308": 1522.683}

    res = territory.process_dtb_df(df_raw, border, coastal, areas=areas, geoloc={"1100015": (-11.933, -62.0037), "3550308": (-23.5548, -46.579)})

    # 1. Schema
    expected_columns = [
        "municipality_code", "municipality_code_6", "municipality_name", "state_code", "state_abbr", "state_name",
        "intermediate_region_code", "intermediate_region_name", "immediate_region_code", "immediate_region_name",
        "international_border", "coastal", "area_km2", "latitude", "longitude"
    ]
    assert res.columns == expected_columns
    assert res.columns[12] == "area_km2"
    assert res.schema == {
        "municipality_code": pl.String,
        "municipality_code_6": pl.String,
        "municipality_name": pl.String,
        "state_code": pl.String,
        "state_abbr": pl.String,
        "state_name": pl.String,
        "intermediate_region_code": pl.String,
        "intermediate_region_name": pl.String,
        "immediate_region_code": pl.String,
        "immediate_region_name": pl.String,
        "international_border": pl.Boolean,
        "coastal": pl.Boolean,
        "area_km2": pl.Float64,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
    }

    # 2. Derivation of 6-digit code
    assert res["municipality_code_6"].to_list() == ["110001", "355030", "530010"]

    # 3. Mapped UF abbreviations
    assert res["state_abbr"].to_list() == ["RO", "SP", "DF"]

    # 4. Border and coastal flags
    assert res.filter(pl.col("municipality_code") == "1100015")["international_border"][0] is True
    assert res.filter(pl.col("municipality_code") == "1100015")["coastal"][0] is False

    assert res.filter(pl.col("municipality_code") == "3550308")["international_border"][0] is False
    assert res.filter(pl.col("municipality_code") == "3550308")["coastal"][0] is True

    assert res.filter(pl.col("municipality_code") == "5300108")["international_border"][0] is False
    assert res.filter(pl.col("municipality_code") == "5300108")["coastal"][0] is False
    
    # 5. Areas
    assert res.filter(pl.col("municipality_code") == "1100015")["area_km2"][0] == 100.5
    assert res.filter(pl.col("municipality_code") == "5300108")["area_km2"][0] is None
    
    # 6. Without areas
    res_sem_area = territory.process_dtb_df(df_raw, border, coastal)
    assert res_sem_area["area_km2"].null_count() == 3

    assert res.columns[-2:] == ["latitude", "longitude"]
    assert res.filter(pl.col("municipality_code") == "1100015")["latitude"][0] == -11.933
    assert res.filter(pl.col("municipality_code") == "1100015")["longitude"][0] == -62.0037
    assert res.filter(pl.col("municipality_code") == "5300108")["latitude"][0] is None
    assert res.filter(pl.col("municipality_code") == "5300108")["longitude"][0] is None
    assert res_sem_area["latitude"].null_count() == 3
    assert res_sem_area["longitude"].null_count() == 3


def test_process_neighboring_df() -> None:
    df_raw = pd.DataFrame({
        "CD_MUN": ["1100015", "1100379", "2605459", "4300001", "1100015"],
        "NM_MUN": ["Alta Floresta D'Oeste", "Alto Alegre dos Parecis", "Fernando de Noronha", "Lagoa Mirim", "Alta Floresta D'Oeste"],
        "N_LIM": ["2", "1", "0", "1", "2"],
        "CD_LIM": ["1100379", "1100015", None, "1100015", "4300001"],
        "NM_LIM": ["Alto Alegre dos Parecis", "Alta Floresta D'Oeste", None, "Alta Floresta D'Oeste", "Lagoa Mirim"],
        "COMP_KM": ["191.181", "191.181", None, "50.0", "50.0"],
    })

    codes_dtb = {"1100015", "1100379", "2605459"}

    res = territory.process_neighboring_df(df_raw, municipality_codes=codes_dtb)

    assert res.schema == {
        "municipality_code": pl.String,
        "neighbor_municipality_code": pl.String,
        "border_length_km": pl.Float64,
    }

    # 1. Without neighbor (2605459) and pairs with code outside DTB (4300001) removed
    assert res.height == 2
    assert set(res["municipality_code"]) == {"1100015", "1100379"}
    assert set(res["neighbor_municipality_code"]) == {"1100015", "1100379"}

    # 2. No nulls
    assert res["municipality_code"].null_count() == 0
    assert res["neighbor_municipality_code"].null_count() == 0
    assert res["border_length_km"].null_count() == 0


def test_read_geoloc(tmp_path) -> None:
    db_path = tmp_path / "test_localities.gpkg"
    con = sqlite3.connect(db_path)
    try:
        con.execute('CREATE TABLE "BR_localidades_2022" (CD_MUN TEXT, NM_MUN TEXT, CT_LOCALIDADE TEXT, SCT_LOCALIDADE TEXT, LAT_LOCALIDADE REAL, LONG_LOCALIDADE REAL)')
        con.execute('INSERT INTO "BR_localidades_2022" VALUES (?, ?, ?, ?, ?, ?)', ("1100015", "Alta Floresta", "Cidade", "Sede", -11.932999610900879, -62.003700256347656))
        con.execute('INSERT INTO "BR_localidades_2022" VALUES (?, ?, ?, ?, ?, ?)', ("1100015", "Alta Floresta", "Povoado", "", -12.5, -62.5))
        con.execute('INSERT INTO "BR_localidades_2022" VALUES (?, ?, ?, ?, ?, ?)', ("2605459", "Fernando", "Distrito Estadual de Fernando de Noronha", "", -3.841300010681152, -32.4109001159668))
        con.commit()
    finally:
        con.close()
    
    database = db_path.read_bytes()
    
    with zipfile.ZipFile(tmp_path / "Localidades_Brasil_gpkg.zip", "w") as zf:
        zf.writestr("BR_localidades_2022.gpkg", database)
        
    geoloc = territory.read_geoloc(tmp_path)
    assert geoloc == {"1100015": (-11.933, -62.0037), "2605459": (-3.8413, -32.4109)}
