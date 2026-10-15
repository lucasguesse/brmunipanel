import pytest
import polars as pl
import pandas as pd
from brmunipanel.inep.ideb import harmonize, _find_header_row
import hashlib
import zipfile
import requests
from brmunipanel.inep import ideb, connection
from brmunipanel.core import InvalidResponse

def test_find_header(tmp_path):
    df_fake = pd.DataFrame({
        0: ["info1", "info2", "SG_UF", "SP"],
        1: ["x", "y", "CO_MUNICIPIO", "3550308"]
    })
    path = tmp_path / "fake.xlsx"
    df_fake.to_excel(path, index=False, header=False)
    
    assert _find_header_row(path) == 2

    # Header not found (total absence)
    df_err = pd.DataFrame({0: ["info1"], 1: ["x"]})
    df_err.to_excel(tmp_path / "err.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Header not found"):
        _find_header_row(tmp_path / "err.xlsx")
        
    # Header not found (has CO_MUNICIPIO but does not have SG_UF)
    df_err2 = pd.DataFrame({0: ["info1", "info2"], 1: ["CO_MUNICIPIO", "3550308"]})
    df_err2.to_excel(tmp_path / "err2.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Header not found"):
        _find_header_row(tmp_path / "err2.xlsx")

def test_harmonize_success(tmp_path):
    valid_muni = pl.DataFrame({"municipality_code": ["1100015", "3550308", "3304557"]})
    
    for stage in ["anos_iniciais", "anos_finais", "ensino_medio"]:
        folder_stage = tmp_path / stage
        folder_stage.mkdir()
        
        # Create synthetic data for each stage
        df = pd.DataFrame([
            {"bla": "info"},
            {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "NO_MUNICIPIO": "NO_MUNICIPIO", "REDE": "REDE", 
             "VL_OBSERVADO_2005": "VL_OBSERVADO_2005", "VL_OBSERVADO_2007": "VL_OBSERVADO_2007"},
            {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "NO_MUNICIPIO": "Alta Floresta", "REDE": "Pública",
             "VL_OBSERVADO_2005": "4,5" if stage == "anos_iniciais" else "-", 
             "VL_OBSERVADO_2007": "4.8"}, # decimal dot
            {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "NO_MUNICIPIO": "Alta Floresta", "REDE": "Estadual",
             "VL_OBSERVADO_2005": "5.0", "VL_OBSERVADO_2007": "5.0"}, # Should be ignored (does not sum networks)
            {"SG_UF": "SP", "CO_MUNICIPIO": "3550308", "NO_MUNICIPIO": "São Paulo", "REDE": "Pública",
             "VL_OBSERVADO_2005": "ND", "VL_OBSERVADO_2007": "ND*"},
            {"SG_UF": "RJ", "CO_MUNICIPIO": "3304557", "NO_MUNICIPIO": "Rio de Janeiro", "REDE": "Pública",
             "VL_OBSERVADO_2005": "ND***", "VL_OBSERVADO_2007": None} # empty as null
        ])
        path = folder_stage / "file.xlsx"
        df.to_excel(path, index=False, header=False)
        
    res = harmonize(tmp_path, valid_muni)
    
    assert res.height == 6 # 3 municipalities * 2 years
    assert res.columns == [
        "municipality_code", "year", 
        "ideb_early_years_public", "ideb_final_years_public", "ideb_secondary_public"
    ]
    
    assert res.schema["municipality_code"] == pl.Utf8
    assert res.schema["year"] == pl.Int16
    assert res.schema["ideb_early_years_public"] == pl.Float64
    
    # Order and sorting
    municipalities = res["municipality_code"].to_list()
    years = res["year"].to_list()
    assert municipalities == sorted(municipalities)
    assert years[:2] == [2005, 2007] # Each municipality must have 2005 and 2007 in order
    
    # 1100015 in 2005
    row_1100015_2005 = res.filter((pl.col("municipality_code") == "1100015") & (pl.col("year") == 2005))
    assert row_1100015_2005["ideb_early_years_public"][0] == 4.5
    assert row_1100015_2005["ideb_final_years_public"][0] is None # Was "-"
    assert row_1100015_2005["ideb_secondary_public"][0] is None
    
    # 1100015 in 2007 decimal dot
    row_1100015_2007 = res.filter((pl.col("municipality_code") == "1100015") & (pl.col("year") == 2007))
    assert row_1100015_2007["ideb_early_years_public"][0] == 4.8
    
    # 3550308 in 2005 and 2007 (ND and ND*)
    row_3550308 = res.filter(pl.col("municipality_code") == "3550308")
    assert row_3550308["ideb_early_years_public"][0] is None
    assert row_3550308["ideb_early_years_public"][1] is None
    
    # 3304557 in 2005 and 2007 (ND*** and None)
    row_3304557 = res.filter(pl.col("municipality_code") == "3304557")
    assert row_3304557["ideb_early_years_public"][0] is None
    assert row_3304557["ideb_early_years_public"][1] is None

    # Determinism of parquet writing
    p1 = tmp_path / "out1.parquet"
    p2 = tmp_path / "out2.parquet"
    res.write_parquet(p1)
    res.write_parquet(p2)
    assert hashlib.sha256(p1.read_bytes()).hexdigest() == hashlib.sha256(p2.read_bytes()).hexdigest()

def test_outer_join(tmp_path):
    valid_muni = pl.DataFrame({"municipality_code": ["1100015", "3550308", "3304557"]})
    
    # anos_iniciais: has only 1100015
    folder = tmp_path / "anos_iniciais"
    folder.mkdir()
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "REDE": "Pública", "VL_OBSERVADO_2005": "4.5"},
    ])
    df.to_excel(folder / "a.xlsx", index=False, header=False)

    # anos_finais: has only 3550308
    folder = tmp_path / "anos_finais"
    folder.mkdir()
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "3550308", "REDE": "Pública", "VL_OBSERVADO_2005": "4.8"},
    ])
    df.to_excel(folder / "b.xlsx", index=False, header=False)

    # ensino_medio: has only 3304557
    folder = tmp_path / "ensino_medio"
    folder.mkdir()
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "RJ", "CO_MUNICIPIO": "3304557", "REDE": "Pública", "VL_OBSERVADO_2005": "4.2"},
    ])
    df.to_excel(folder / "c.xlsx", index=False, header=False)

    res = harmonize(tmp_path, valid_muni)
    
    assert res.height == 3
    
    row1 = res.filter(pl.col("municipality_code") == "1100015")
    assert row1["ideb_early_years_public"][0] == 4.5
    assert row1["ideb_final_years_public"][0] is None
    assert row1["ideb_secondary_public"][0] is None

    row2 = res.filter(pl.col("municipality_code") == "3550308")
    assert row2["ideb_early_years_public"][0] is None
    assert row2["ideb_final_years_public"][0] == 4.8
    assert row2["ideb_secondary_public"][0] is None

    row3 = res.filter(pl.col("municipality_code") == "3304557")
    assert row3["ideb_early_years_public"][0] is None
    assert row3["ideb_final_years_public"][0] is None
    assert row3["ideb_secondary_public"][0] == 4.2


def test_various_errors(tmp_path):
    valid_muni = pl.DataFrame({"municipality_code": ["1100015"]})
    folder = tmp_path / "anos_iniciais"
    
    # 1. Missing folder
    with pytest.raises(FileNotFoundError, match="Stage folder not found"):
        harmonize(tmp_path, valid_muni)
        
    folder.mkdir()
    
    # 2. Missing file
    with pytest.raises(FileNotFoundError, match="No .xlsx found"):
        harmonize(tmp_path, valid_muni)
        
    # 3. Multiple files
    (folder / "a.xlsx").touch()
    (folder / "b.xlsx").touch()
    with pytest.raises(ValueError, match="More than one .xlsx file"):
        harmonize(tmp_path, valid_muni)
        
    (folder / "b.xlsx").unlink()
    
    # 4. Missing column (REDE)
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "3550308"}
    ])
    df.to_excel(folder / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Column REDE missing"):
        harmonize(tmp_path, valid_muni)
        
    # 5. Missing public network
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "3550308", "REDE": "Estadual"}
    ])
    df.to_excel(folder / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Network 'Pública' not found"):
        harmonize(tmp_path, valid_muni)

    # 6. Missing value column
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "1100015", "REDE": "Pública"}
    ])
    df.to_excel(folder / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="No VL_OBSERVADO_AAAA column found"):
        harmonize(tmp_path, valid_muni)
        
    # 7. Municipality outside registry
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "SP", "CO_MUNICIPIO": "9999999", "REDE": "Pública", "VL_OBSERVADO_2005": "5.0"}
    ])
    df.to_excel(folder / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="outside the municipal registry"):
        harmonize(tmp_path, valid_muni)

    # 8. Duplicate key
    df = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "REDE": "REDE", "VL_OBSERVADO_2005": "VL_OBSERVADO_2005"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "REDE": "Pública", "VL_OBSERVADO_2005": "5.0"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "REDE": "Pública", "VL_OBSERVADO_2005": "5.0"}
    ])
    df.to_excel(folder / "a.xlsx", index=False, header=False)
    with pytest.raises(ValueError, match="Duplicate municipality_code-year key"):
        # Need to create the other folders so it does not fail before full join/harmonize
        (tmp_path / "anos_finais").mkdir()
        (tmp_path / "ensino_medio").mkdir()
        df.to_excel(tmp_path / "anos_finais" / "b.xlsx", index=False, header=False)
        df.to_excel(tmp_path / "ensino_medio" / "c.xlsx", index=False, header=False)
        harmonize(tmp_path, valid_muni)


def test_download_builds_three_requests(monkeypatch, tmp_path):
    calls = []

    def mock_download_batch(reqs, folder, **options):
        calls.append((reqs, folder, options))

    monkeypatch.setattr(ideb, "download_batch", mock_download_batch)

    ideb.download(tmp_path)
    assert len(calls) == 1
    reqs, folder, options = calls[0]
    assert folder == tmp_path
    assert len(reqs) == 3

    assert reqs[0].key == "early_years/2025"
    assert reqs[0].url == "https://download.inep.gov.br/ideb/resultados/divulgacao_anos_iniciais_municipios_2025.zip"
    assert reqs[0].file == "divulgacao_anos_iniciais_municipios_2025.zip"
    assert reqs[0].compress is False

    assert reqs[1].key == "final_years/2025"
    assert reqs[1].url == "https://download.inep.gov.br/ideb/resultados/divulgacao_anos_finais_municipios_2025.zip"
    assert reqs[1].file == "divulgacao_anos_finais_municipios_2025.zip"
    assert reqs[1].compress is False

    assert reqs[2].key == "secondary/2025"
    assert reqs[2].url == "https://download.inep.gov.br/ideb/resultados/divulgacao_ensino_medio_municipios_2025.zip"
    assert reqs[2].file == "divulgacao_ensino_medio_municipios_2025.zip"
    assert reqs[2].compress is False

    assert options["validate"] is ideb.validate_zip
    assert options["interval"] == 1.0
    session = options["session"]
    assert isinstance(session, requests.Session)
    assert session.verify == str(connection.certificate_authorities())

    obj = requests.Session()
    ideb.download(tmp_path, session=obj)
    assert len(calls) == 2
    assert calls[1][2]["session"] is obj


def test_validate_zip():
    ideb.validate_zip(b"PK\x03\x04resto")
    with pytest.raises(InvalidResponse):
        ideb.validate_zip(b"<html>")


def test_harmonize_reads_spreadsheet_inside_package(tmp_path):
    valid_muni = pl.DataFrame({"municipality_code": ["1100015"]})
    legacy_folder = tmp_path / "legacy"
    folder_new = tmp_path / "new"
    legacy_folder.mkdir()
    folder_new.mkdir()

    df_base = pd.DataFrame([
        {"SG_UF": "SG_UF", "CO_MUNICIPIO": "CO_MUNICIPIO", "NO_MUNICIPIO": "NO_MUNICIPIO", "REDE": "REDE",
         "VL_OBSERVADO_2005": "VL_OBSERVADO_2005", "VL_OBSERVADO_2007": "VL_OBSERVADO_2007"},
        {"SG_UF": "RO", "CO_MUNICIPIO": "1100015", "NO_MUNICIPIO": "Alta Floresta", "REDE": "Pública",
         "VL_OBSERVADO_2005": "4,5", "VL_OBSERVADO_2007": "4.8"},
    ])

    for stage in ["anos_iniciais", "anos_finais", "ensino_medio"]:
        folder_legacy_stage = legacy_folder / stage
        folder_legacy_stage.mkdir()
        path_xlsx = folder_legacy_stage / "a.xlsx"
        df_base.to_excel(path_xlsx, index=False, header=False)

        package_zip = folder_new / f"divulgacao_{stage}_municipios_2025.zip"
        with zipfile.ZipFile(package_zip, "w") as z:
            z.write(path_xlsx, f"divulgacao_{stage}_municipios_2025/divulgacao_{stage}_municipios_2025.xlsx")
            z.writestr(f"divulgacao_{stage}_municipios_2025/leia-me.txt", "text")
            z.writestr(f"divulgacao_{stage}_municipios_2025/data.ods", b"ods")

    legacy_df = harmonize(legacy_folder, valid_muni)
    df_new = harmonize(folder_new, valid_muni)

    assert df_new.equals(legacy_df)
    assert df_new.height == 2

    l2005 = df_new.filter(pl.col("year") == 2005)
    assert l2005["ideb_early_years_public"][0] == 4.5
    assert l2005["ideb_final_years_public"][0] == 4.5
    assert l2005["ideb_secondary_public"][0] == 4.5

    l2007 = df_new.filter(pl.col("year") == 2007)
    assert l2007["ideb_early_years_public"][0] == 4.8
    assert l2007["ideb_final_years_public"][0] == 4.8
    assert l2007["ideb_secondary_public"][0] == 4.8


def test_package_without_spreadsheet_or_with_two_raises_error(tmp_path):
    valid_muni = pl.DataFrame({"municipality_code": ["1100015"]})
    package = tmp_path / "divulgacao_anos_iniciais_municipios_2025.zip"

    with zipfile.ZipFile(package, "w") as z:
        z.writestr("text.txt", "content")

    with pytest.raises(ValueError, match="should have one spreadsheet"):
        harmonize(tmp_path, valid_muni)

    with zipfile.ZipFile(package, "w") as z:
        z.writestr("spreadsheet1.xlsx", b"")
        z.writestr("spreadsheet2.xlsx", b"")

    with pytest.raises(ValueError, match="should have one spreadsheet"):
        harmonize(tmp_path, valid_muni)
