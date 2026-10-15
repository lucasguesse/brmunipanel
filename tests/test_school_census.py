import os
from pathlib import Path
import io
import hashlib
import json
import zipfile
import tempfile
import polars as pl
import pytest

from brmunipanel.inep import school_census
from brmunipanel.core import InvalidResponse, download_batch as core_download_batch

DATA = Path(__file__).parent / "data"

@pytest.fixture
def raw_folder_2007(tmp_path):
    file = tmp_path / "school-census" / "school-census_2007.zip"
    file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file, "w") as z:
        z.write(DATA / "school_census_2007_sample.csv", "microdados_ed_basica_2007.csv")
    return tmp_path

@pytest.fixture
def raw_folder_2023(tmp_path):
    file = tmp_path / "school-census" / "school-census_2023.zip"
    file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file, "w") as z:
        z.write(DATA / "school_census_2023_sample.csv", "MICRODADOS_ED_BASICA_2023.CSV")
    return tmp_path

@pytest.fixture
def municipalities_mock():
    df = pl.read_csv(DATA / "school_census_2007_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    muni_2007 = df["CO_MUNICIPIO"].unique().to_list()
    df2 = pl.read_csv(DATA / "school_census_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    muni_2023 = df2["CO_MUNICIPIO"].unique().to_list()
    df3 = pl.read_csv(DATA / "school_census_2006_sample.csv", separator="|", encoding="utf8-lossy", infer_schema_length=0)
    muni_2006 = [(m[:2] + m[-5:]) for m in df3["CODMUNIC"].unique().to_list()]
    munis = list(set(muni_2007 + muni_2023 + muni_2006))
    return pl.DataFrame({"municipality_code": munis})

def test_school_census_schema(raw_folder_2007, municipalities_mock, monkeypatch):
    monkeypatch.setattr(school_census, "ALL_YEARS", [2007])
    df = school_census.harmonize(raw_folder_2007, municipalities_mock)
    
    assert df.shape[1] == 53
    col_order = ["municipality_code", "year", "admin_dependency", "location", "schools"]
    for _, dest in school_census.COUNT_COLUMNS:
        col_order.append(dest)
        
    assert df.columns == col_order
    assert df.schema["municipality_code"] == pl.String
    assert df.schema["year"] == pl.Int16
    assert df.schema["admin_dependency"] == pl.String
    assert df.schema["location"] == pl.String
    assert df.schema["schools"] == pl.Int64
    for c in col_order[5:]:
        assert df.schema[c] == pl.Int64

def test_school_census_count_schools_activity(raw_folder_2023, municipalities_mock, monkeypatch):
    monkeypatch.setattr(school_census, "ALL_YEARS", [2023])
    df = school_census.harmonize(raw_folder_2023, municipalities_mock)
    
    raw = pl.read_csv(DATA / "school_census_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    active = raw.filter(pl.col("TP_SITUACAO_FUNCIONAMENTO") == "1").shape[0]
    assert df["schools"].sum() == active

def test_school_census_aggregation_and_empty(raw_folder_2007, municipalities_mock, monkeypatch):
    monkeypatch.setattr(school_census, "ALL_YEARS", [2007])
    df = school_census.harmonize(raw_folder_2007, municipalities_mock)
    
    # Check case where only part of the schools have empty value (sum of the others)
    # Group ('1100114', '3', '2') (municipal, rural) has 2 schools, one with empty and another with 1
    row_m_r = df.filter(
        (pl.col("municipality_code") == "1100114") &
        (pl.col("admin_dependency") == "municipal") &
        (pl.col("location") == "rural")
    )
    assert row_m_r["schools"][0] == 2
    assert row_m_r["enroll_basic_edu"][0] == 32
    assert row_m_r["teachers_basic_edu"][0] == 1
    assert row_m_r["classes_basic_edu"][0] == 3
    
    # Check case where all schools in the group have empty value (remains null)
    # Group ('1100205', '4', '1') (privada, urbana) has 1 school with empty value
    row_p_u = df.filter(
        (pl.col("municipality_code") == "1100205") &
        (pl.col("admin_dependency") == "private") &
        (pl.col("location") == "urban")
    )
    assert row_p_u["schools"][0] == 1
    assert row_p_u["enroll_basic_edu"][0] == 8
    assert row_p_u["teachers_basic_edu"][0] is None
    assert row_p_u["classes_basic_edu"][0] == 1

def test_school_census_sorting_and_unique_key(raw_folder_2007, raw_folder_2023, tmp_path, municipalities_mock, monkeypatch):
    file23 = tmp_path / "school-census" / "school-census_2023.zip"
    file23.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file23, "w") as z:
        z.write(DATA / "school_census_2023_sample.csv", "MICRODADOS_ED_BASICA_2023.CSV")
        
    file07 = tmp_path / "school-census" / "school-census_2007.zip"
    with zipfile.ZipFile(file07, "w") as z:
        z.write(DATA / "school_census_2007_sample.csv", "microdados_ed_basica_2007.csv")

    monkeypatch.setattr(school_census, "ALL_YEARS", [2007, 2023])
    df = school_census.harmonize(tmp_path, municipalities_mock)
    
    assert df.shape[0] == df.select(["municipality_code", "year", "admin_dependency", "location"]).unique().shape[0]
    
    df_sorted = df.sort(["municipality_code", "year", "admin_dependency", "location"])
    assert df.equals(df_sorted)

def test_school_census_errors(raw_folder_2007, municipalities_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(school_census, "ALL_YEARS", [2007])
    
    # Municipality outside
    file = tmp_path / "school-census" / "school-census_2007.zip"
    file.parent.mkdir(parents=True, exist_ok=True)
    
    raw = pl.read_csv(DATA / "school_census_2007_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("9999999").alias("CO_MUNICIPIO"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "microdados_ed_basica.csv"
        raw.write_csv(tmpcsv, separator=";")
        with zipfile.ZipFile(file, "w") as z:
            z.write(tmpcsv, "microdados_ed_basica.csv")
    
    with pytest.raises(ValueError, match="invalid or null municipalities"):
        school_census.harmonize(tmp_path, municipalities_mock)
        
    # Dependency outside
    raw = pl.read_csv(DATA / "school_census_2007_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("9").alias("TP_DEPENDENCIA"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "microdados_ed_basica.csv"
        raw.write_csv(tmpcsv, separator=";")
        with zipfile.ZipFile(file, "w") as z:
            z.write(tmpcsv, "microdados_ed_basica.csv")
            
    with pytest.raises(ValueError, match="invalid values in TP_DEPENDENCIA"):
        school_census.harmonize(tmp_path, municipalities_mock)

    # Negative int
    raw = pl.read_csv(DATA / "school_census_2007_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("-1").alias("QT_MAT_BAS"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "microdados_ed_basica.csv"
        raw.write_csv(tmpcsv, separator=";")
        with zipfile.ZipFile(file, "w") as z:
            z.write(tmpcsv, "microdados_ed_basica.csv")
            
    with pytest.raises(ValueError, match="non-integer or negative values in column QT_MAT_BAS"):
        school_census.harmonize(tmp_path, municipalities_mock)

    # package without csv
    with zipfile.ZipFile(file, "w") as z:
        z.write(DATA / "school_census_2007_sample.csv", "outro.csv")
        
    with pytest.raises(ValueError, match="expected exactly 1 CSV file"):
        school_census.harmonize(tmp_path, municipalities_mock)

def test_school_census_download_mock(monkeypatch):
    calls = []
    def mock_download_batch(reqs, folder, validate, interval, **options):
        calls.extend(reqs)
        try:
            validate(b"PK\x03\x04...")
        except Exception:
            pytest.fail("Zip validation failed for valid content")
        with pytest.raises(InvalidResponse):
            validate(b"<html>...</html>")

    monkeypatch.setattr(school_census, "download_batch", mock_download_batch)
    school_census.download("dummy")
    assert len(calls) == 18
    years = list(range(2006, 2024))
    for req, year in zip(calls, years):
        assert req.key == f"school-census/{year}"
        assert req.file == f"school-census/school-census_{year}.zip"
        assert req.url == f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{year}.zip"
        assert req.compress is False

    # case where the manifest already has the key and the file exists
    monkeypatch.setattr(school_census, "ALL_YEARS", [2023])
    
    class FailingSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("Must not call the network")
        def post(self, *args, **kwargs):
            raise RuntimeError("Must not call the network")
            
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        folder_inep = td / "school-census"
        folder_inep.mkdir(parents=True, exist_ok=True)
        
        manifest = {}
        for year in range(2006, 2024):
            file = folder_inep / f"school-census_{year}.zip"
            file.write_bytes(b"PK\x03\x04" + b"X" * 10)
            manifest[f"school-census/{year}"] = {
                "file": f"school-census/school-census_{year}.zip",
                "method": "GET",
                "url": f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{year}.zip",
                "bytes": file.stat().st_size,
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest()
            }
        with open(td / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
            
        monkeypatch.setattr(school_census, "download_batch", core_download_batch)
        
        school_census.download(td, session=FailingSession())

@pytest.fixture
def raw_folder_2006(tmp_path):
    folder_inep = tmp_path / "school-census"
    folder_inep.mkdir(parents=True, exist_ok=True)
    file = folder_inep / "school-census_2006.zip"
    with zipfile.ZipFile(file, "w") as z:
        z.write(os.path.join(os.path.dirname(__file__), "data", "school_census_2006_sample.csv"), "CENSOESC_2006.CSV")
        z.write(os.path.join(os.path.dirname(__file__), "data", "school_census_2006_educprof_sample.csv"), "EDUCPROF_2006.CSV")
        
    return tmp_path

def test_school_census_2006_cases(raw_folder_2006, municipalities_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(school_census, "ALL_YEARS", [2006])
    df = school_census.harmonize(raw_folder_2006, municipalities_mock)
    
    # Case 1: The 2006 output has the 53 columns, in the table order and types
    assert df.shape[1] == 53
    col_order = ["municipality_code", "year", "admin_dependency", "location", "schools"]
    for _, dest in school_census.COUNT_COLUMNS:
        col_order.append(dest)
        
    assert df.columns == col_order
    assert df.schema["municipality_code"] == pl.String
    assert df.schema["year"] == pl.Int16
    assert df.schema["admin_dependency"] == pl.String
    assert df.schema["location"] == pl.String
    assert df.schema["schools"] == pl.Int64
    for c in col_order[5:]:
        assert df.schema[c] == pl.Int64
        
    # Case 3: The fourteen columns without information are null across all 2006 rows
    fourteen = [
        "enroll_basic_edu", "classes_basic_edu", "teachers_early_childhood", "teachers_elementary_early_years",
        "teachers_elementary_final_years", "teachers_eja_elementary", "teachers_eja_secondary",
        "teachers_inclusive_ed_common_classes", "teachers_inclusive_ed_exclusive_classes", "classes_vocational",
        "classes_vocational_technical", "classes_inclusive_ed", "classes_inclusive_ed_common_classes", "classes_inclusive_ed_exclusive_classes"
    ]
    for c in fourteen:
        assert df.select(pl.col(c).is_null().all())[c][0] is True
        
    others = [c for c in col_order if c not in fourteen]
    for c in others:
        assert df.select(pl.col(c).is_null().any())[c][0] is False
        
    # Case 2: Values of a group (e.g. municipality_code, dependency, and location), calculated by hand from the sample
    row = df.filter((pl.col("admin_dependency") == "federal") & (pl.col("municipality_code") == "1100023")).to_dicts()[0]
    assert row["schools"] == 1
    assert row["enroll_elementary"] == 0
    assert row["enroll_secondary"] == 0
    assert row["enroll_vocational"] == 204
    assert row["teachers_basic_edu"] == 16
    assert row["classes_elementary"] == 0
    
    # Municipal and rural of 1100205, with schools equal to 1 (extinct school does not count)
    row_muni_rural = df.filter((pl.col("admin_dependency") == "municipal") & (pl.col("municipality_code") == "1100205") & (pl.col("location") == "rural")).to_dicts()[0]
    assert row_muni_rural["schools"] == 1
    # Check day care and 9-year elementary
    assert row_muni_rural["enroll_elementary_early_years"] == 28 # Has DE9F11C to DE9F11G = 28 in school 54264611
    
    # Inactive school does not count in group privada and urbana of 1100205
    row_priv_urb = df.filter((pl.col("admin_dependency") == "private") & (pl.col("municipality_code") == "1100205") & (pl.col("location") == "urban")).to_dicts()[0]
    assert row_priv_urb["schools"] == 2 # 54261222 and 54262913 (54261227 inactive does not count)
    assert row_priv_urb["enroll_daycare"] == 18 # Has DPE119 = 18 in 54262913
    
    # Case 4: Empty counts as zero: a group without EJA has enroll_eja equal to zero, not null
    row = df.filter((pl.col("admin_dependency") == "federal") & (pl.col("municipality_code") == "1100023")).to_dicts()[0]
    assert row["enroll_eja"] == 0
    
    # Case 5: Normal school course is not added to upper secondary
    # ('1100205', 'state', 'urban') has the school with normal school course (DCN)
    row = df.filter((pl.col("municipality_code") == "1100205") & (pl.col("admin_dependency") == "state") & (pl.col("location") == "urban")).to_dicts()[0]
    assert row["enroll_secondary"] == 147
    
    # Case 6: EJA sums in-person and blended, and EJA classes count in-person
    # ('1100338', 'state', 'urban') has blended EJA (VES12A3)
    row = df.filter((pl.col("municipality_code") == "1100338") & (pl.col("admin_dependency") == "state") & (pl.col("location") == "urban")).to_dicts()[0]
    assert row["enroll_eja"] == 712
    assert row["classes_eja"] == 8
    
    # Case 7: Special education follows prefixes
    # inclusive: '1100205', privada, urbana
    row = df.filter((pl.col("municipality_code") == "1100205") & (pl.col("admin_dependency") == "private") & (pl.col("location") == "urban")).to_dicts()[0]
    assert row["enroll_inclusive_ed_common_classes"] == 6
    assert row["enroll_inclusive_ed_exclusive_classes"] == 0
    # exclusive: '1100205', estadual, urbana
    row = df.filter((pl.col("municipality_code") == "1100205") & (pl.col("admin_dependency") == "state") & (pl.col("location") == "urban")).to_dicts()[0]
    assert row["enroll_inclusive_ed_common_classes"] == 0
    assert row["enroll_inclusive_ed_exclusive_classes"] == 190
    
    # Case 8: Vocational education comes from the courses file, and inactive course does not count
    row = df.filter((pl.col("admin_dependency") == "private") & (pl.col("location") == "urban") & (pl.col("municipality_code") == "1100023")).to_dicts()[0]
    assert row["enroll_vocational"] == 43
    
    # In case 8, the inactive course is set up in the test
    file_tmp = tmp_path / "school-census_inactive" / "school-census" / "school-census_2006.zip"
    file_tmp.parent.mkdir(parents=True, exist_ok=True)
    # Replace Ativo with Inativo in the EDUCPROF CSV
    edu_csv = (DATA / "school_census_2006_educprof_sample.csv").read_text(encoding="utf8")
    edu_csv = edu_csv.replace("|Ativo|", "|Inativo|")
    with zipfile.ZipFile(file_tmp, "w") as z:
        z.write(DATA / "school_census_2006_sample.csv", "CENSOESC_2006.CSV")
        z.writestr("EDUCPROF_2006.CSV", edu_csv)
    df_inactive = school_census.harmonize(tmp_path / "school-census_inactive", municipalities_mock)
    row_inactive = df_inactive.filter((pl.col("admin_dependency") == "private") & (pl.col("location") == "urban") & (pl.col("municipality_code") == "1100023")).to_dicts()[0]
    assert row_inactive["enroll_vocational"] == 0

def test_school_census_2006_errors(raw_folder_2006, municipalities_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(school_census, "ALL_YEARS", [2006])
    file = tmp_path / "school-census" / "school-census_2006.zip"
    file.parent.mkdir(parents=True, exist_ok=True)
    
    orig_path = raw_folder_2006 / "school-census" / "school-census_2006.zip"
    with zipfile.ZipFile(orig_path, 'r') as z:
        census_csv = z.read("CENSOESC_2006.CSV")
        edu_csv = z.read("EDUCPROF_2006.CSV")
    
    # Error 1: DEP outside the list
    raw = pl.read_csv(io.BytesIO(census_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("Fora").alias("DEP"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "CENSOESC_2006.CSV"
        raw.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(file, "w") as z:
            z.write(tmpcsv, "CENSOESC_2006.CSV")
            z.writestr("EDUCPROF_2006.CSV", edu_csv)
    with pytest.raises(ValueError, match="invalid values in DEP"):
        school_census.harmonize(tmp_path, municipalities_mock)
        
    # Error 2: Municipality outside the table
    raw = pl.read_csv(io.BytesIO(census_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("999999999999").alias("CODMUNIC"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "CENSOESC_2006.CSV"
        raw.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(file, "w") as z:
            z.write(tmpcsv, "CENSOESC_2006.CSV")
            z.writestr("EDUCPROF_2006.CSV", edu_csv)
    with pytest.raises(ValueError, match="invalid or null municipalities in CODMUNIC"):
        school_census.harmonize(tmp_path, municipalities_mock)
        
    # Error 3: Non-integer value
    raw = pl.read_csv(io.BytesIO(census_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("-1").alias("DPE119"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "CENSOESC_2006.CSV"
        raw.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(file, "w") as z:
            z.write(tmpcsv, "CENSOESC_2006.CSV")
            z.writestr("EDUCPROF_2006.CSV", edu_csv)
    with pytest.raises(ValueError, match="non-integer or negative values in column DPE119"):
        school_census.harmonize(tmp_path, municipalities_mock)
        
    # Error 4: active technical course in school not in activity
    raw_edu = pl.read_csv(io.BytesIO(edu_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw_edu = raw_edu.with_columns(pl.lit("99999999").alias("MASCARA"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "EDUCPROF_2006.CSV"
        raw_edu.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(file, "w") as z:
            z.writestr("CENSOESC_2006.CSV", census_csv)
            z.write(tmpcsv, "EDUCPROF_2006.CSV")
    with pytest.raises(ValueError, match="active technical course of an inactive or missing school"):
        school_census.harmonize(tmp_path, municipalities_mock)
        
    # Error 5: Package missing one of the two CSVs
    with zipfile.ZipFile(file, "w") as z:
        z.writestr("CENSOESC_2006.CSV", census_csv)
    with pytest.raises(ValueError, match="CENSOESC_2006.CSV or EDUCPROF_2006.CSV missing from the ZIP"):
        school_census.harmonize(tmp_path, municipalities_mock)

def test_school_census_2006_and_2007(raw_folder_2007, tmp_path, municipalities_mock, monkeypatch):
    file07 = tmp_path / "school-census" / "school-census_2007.zip"
    file07.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file07, "w") as z:
        z.write(DATA / "school_census_2007_sample.csv", "microdados_ed_basica_2007.csv")
        
    file06 = tmp_path / "school-census" / "school-census_2006.zip"
    with zipfile.ZipFile(file06, "w") as z:
        z.write(DATA / "school_census_2006_sample.csv", "CENSOESC_2006.CSV")
        z.write(DATA / "school_census_2006_educprof_sample.csv", "EDUCPROF_2006.CSV")

    monkeypatch.setattr(school_census, "ALL_YEARS", [2006, 2007])
    df = school_census.harmonize(tmp_path, municipalities_mock)
    
    assert df.shape[0] == df.select(["municipality_code", "year", "admin_dependency", "location"]).unique().shape[0]
    
    df_sorted = df.sort(["municipality_code", "year", "admin_dependency", "location"])
    assert df.equals(df_sorted)
    
    # The 2007 rows come out identical
    monkeypatch.setattr(school_census, "ALL_YEARS", [2007])
    df_2007_only = school_census.harmonize(raw_folder_2007, municipalities_mock)
    df_filtered = df.filter(pl.col("year") == 2007)
    
    assert df_filtered.equals(df_2007_only)


def test_download_uses_the_inep_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    def mock_download_batch(reqs, folder, **options):
        calls.append(options)

    monkeypatch.setattr(school_census, "download_batch", mock_download_batch)

    from brmunipanel.inep import connection
    import requests

    # Case 1: without session provided
    school_census.download(tmp_path)
    assert len(calls) == 1
    session_default = calls[0].get("session")
    assert isinstance(session_default, requests.Session)
    assert session_default.verify == str(connection.certificate_authorities())

    # Case 2: with explicit session
    obj_session = requests.Session()
    school_census.download(tmp_path, session=obj_session)
    assert len(calls) == 2
    session_custom = calls[1].get("session")
    assert session_custom is obj_session

