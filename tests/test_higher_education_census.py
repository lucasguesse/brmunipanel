import hashlib
import json
import zipfile
import pytest
import polars as pl
from pathlib import Path

from brmunipanel.inep import higher_education_census
from brmunipanel.core import download_batch as core_download_batch


@pytest.fixture
def base_dir(tmp_path):
    return tmp_path

@pytest.fixture
def sample_dir():
    return Path(__file__).parent / "data"

@pytest.fixture
def mock_municipalities():
    return pl.DataFrame({"municipality_code": ["1100205", "1501402", "3550308", "4106902", "5300108"]})

def create_zip(folder: Path, year: int, sample_dir: Path, courses_name="cadastro_cursos", hei_name="_ies_"):
    folder_inep = folder / "higher-education-census"
    folder_inep.mkdir(parents=True, exist_ok=True)
    zip_path = folder_inep / f"higher-education-census_{year}.zip"
    
    with zipfile.ZipFile(zip_path, 'w') as z:
        if courses_name:
            z.write(sample_dir / f"higher_education_census_courses_{year}_sample.csv", arcname=f"{courses_name}.csv")
        if hei_name:
            z.write(sample_dir / f"higher_education_census_hei_{year}_sample.csv", arcname=f"{hei_name}.csv")

def test_schema(base_dir, sample_dir, mock_municipalities, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    create_zip(base_dir, 2023, sample_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    # Need to add sample municipality codes to the mock
    courses = pl.read_csv(sample_dir / "higher_education_census_courses_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    hei = pl.read_csv(sample_dir / "higher_education_census_hei_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    munis = set(courses["CO_MUNICIPIO"].to_list() + hei["CO_MUNICIPIO_IES"].to_list())
    mock_munis = pl.DataFrame({"municipality_code": list(munis)})
    
    df = higher_education_census.harmonize(base_dir, mock_munis)
    
    columns_esp = ["municipality_code", "year", "category", "institutions", "enrollments", "hq_institutions", "hq_teachers"]
    assert df.columns == columns_esp
    
    assert df.schema["municipality_code"] == pl.Utf8
    assert df.schema["year"] == pl.Int16
    assert df.schema["category"] == pl.Utf8
    assert df.schema["institutions"] == pl.Int64
    assert df.schema["enrollments"] == pl.Int64
    assert df.schema["hq_institutions"] == pl.Int64
    assert df.schema["hq_teachers"] == pl.Int64

def test_distance_and_without_course(base_dir, sample_dir, mock_municipalities, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    create_zip(base_dir, 2023, sample_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    courses = pl.read_csv(sample_dir / "higher_education_census_courses_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    hei = pl.read_csv(sample_dir / "higher_education_census_hei_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    munis = set(courses["CO_MUNICIPIO"].to_list() + hei["CO_MUNICIPIO_IES"].to_list())
    mock_munis = pl.DataFrame({"municipality_code": list(munis)})
    
    df = higher_education_census.harmonize(base_dir, mock_munis)
    
    assert df["hq_institutions"].sum() == 1

def test_values(base_dir, sample_dir, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    create_zip(base_dir, 2023, sample_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    courses = pl.read_csv(sample_dir / "higher_education_census_courses_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    hei = pl.read_csv(sample_dir / "higher_education_census_hei_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    munis = set(courses["CO_MUNICIPIO"].to_list() + hei["CO_MUNICIPIO_IES"].to_list())
    mock_munis = pl.DataFrame({"municipality_code": list(munis)})
    
    df = higher_education_census.harmonize(base_dir, mock_munis)
    
    on_campus = courses.filter(pl.col("TP_MODALIDADE_ENSINO") == "1")
    if len(on_campus) > 0:
        muni = on_campus["CO_MUNICIPIO"][0]
        cat_id = on_campus["TP_CATEGORIA_ADMINISTRATIVA"][0]
        cat_map = {"1": "federal", "2": "state", "3": "municipal", "4": "private", "5": "private", "6": "private", "8": "private", "9": "private", "7": "special"}
        cat = cat_map[cat_id]
        
        on_campus_group = on_campus.filter((pl.col("CO_MUNICIPIO") == muni) & (pl.col("TP_CATEGORIA_ADMINISTRATIVA") == cat_id))
        mat_esp = sum([int(x) if x else 0 for x in on_campus_group["QT_MAT"].to_list()])
        
        row = df.filter((pl.col("municipality_code") == muni) & (pl.col("category") == cat))
        assert row["enrollments"][0] == mat_esp

def test_two_institutions_same_muni(base_dir, sample_dir, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    create_zip(base_dir, 2023, sample_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    courses = pl.read_csv(sample_dir / "higher_education_census_courses_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    hei = pl.read_csv(sample_dir / "higher_education_census_hei_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    
    # Create duplicate course for the same IES in the same municipality
    on_campus = courses.filter(pl.col("TP_MODALIDADE_ENSINO") == "1")
    if len(on_campus) > 0:
        row1 = on_campus.row(0, named=True)
        # force a duplicate IES
        duplicate_courses = pl.concat([courses, pl.DataFrame([row1])])
        
        path_csv = base_dir / "mod_cursos.csv"
        duplicate_courses.write_csv(path_csv, separator=";")
        
        zip_path = base_dir / "higher-education-census" / "higher-education-census_2023.zip"
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(path_csv, arcname="MICRODADOS_CADASTRO_CURSOS_2023.CSV")
            z.write(sample_dir / "higher_education_census_hei_2023_sample.csv", arcname="MICRODADOS_CADASTRO_IES_2023.CSV")
            
        munis = set(duplicate_courses["CO_MUNICIPIO"].to_list() + hei["CO_MUNICIPIO_IES"].to_list())
        mock_munis = pl.DataFrame({"municipality_code": list(munis)})
        df = higher_education_census.harmonize(base_dir, mock_munis)
        
        cat_map = {"1": "federal", "2": "state", "3": "municipal", "4": "private", "5": "private", "6": "private", "8": "private", "9": "private", "7": "special"}
        cat = cat_map[row1["TP_CATEGORIA_ADMINISTRATIVA"]]
        
        row_agg = df.filter((pl.col("municipality_code") == row1["CO_MUNICIPIO"]) & (pl.col("category") == cat))
        
        # The IES has 2 courses, but only counts as 1 in institutions
        # Checks whether the number of IES in that group matches the manual unique count
        on_campus_group = duplicate_courses.filter(
            (pl.col("CO_MUNICIPIO") == row1["CO_MUNICIPIO"]) & 
            (pl.col("TP_CATEGORIA_ADMINISTRATIVA") == row1["TP_CATEGORIA_ADMINISTRATIVA"]) &
            (pl.col("TP_MODALIDADE_ENSINO") == "1")
        )
        hei_count_esp = on_campus_group["CO_IES"].n_unique()
        assert row_agg["institutions"][0] == hei_count_esp

def test_group_hq_only_or_course_only(base_dir, sample_dir, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    
    courses = pl.DataFrame({
        "CO_MUNICIPIO": ["1100205"],
        "CO_IES": ["1"],
        "TP_MODALIDADE_ENSINO": ["1"],
        "TP_CATEGORIA_ADMINISTRATIVA": ["1"],
        "QT_MAT": ["100"]
    })
    hei = pl.DataFrame({
        "CO_IES": ["1"],
        "CO_MUNICIPIO_IES": ["5300108"], # Different seat
        "TP_CATEGORIA_ADMINISTRATIVA": ["1"],
        "QT_DOC_EXE": ["50"]
    })
    
    folder_inep = base_dir / "higher-education-census"
    folder_inep.mkdir(parents=True, exist_ok=True)
    zip_path = folder_inep / "higher-education-census_2023.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr("cadastro_cursos.csv", courses.write_csv(separator=";"))
        z.writestr("_ies_.csv", hei.write_csv(separator=";"))
        
    mock_munis = pl.DataFrame({"municipality_code": ["1100205", "5300108"]})
    df = higher_education_census.harmonize(base_dir, mock_munis)
    
    # 1100205 = course, enrollments; seat = 0
    row_course = df.filter(pl.col("municipality_code") == "1100205")
    assert row_course["institutions"][0] == 1
    assert row_course["enrollments"][0] == 100
    assert row_course["hq_institutions"][0] == 0
    assert row_course["hq_teachers"][0] == 0
    
    # 5300108 = seat; course = 0
    row_hq = df.filter(pl.col("municipality_code") == "5300108")
    assert row_hq["institutions"][0] == 0
    assert row_hq["enrollments"][0] == 0
    assert row_hq["hq_institutions"][0] == 1
    assert row_hq["hq_teachers"][0] == 50

def test_legacy_codes_2009(base_dir, sample_dir, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2009])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    
    courses = pl.DataFrame({
        "CO_MUNICIPIO": ["1100205"],
        "CO_IES": ["1"],
        "TP_MODALIDADE_ENSINO": ["1"],
        "TP_CATEGORIA_ADMINISTRATIVA": ["6"], # 6, 8, 9 become privada
        "QT_MAT": ["100"]
    })
    hei = pl.DataFrame({
        "CO_IES": ["1"],
        "CO_MUNICIPIO_IES": ["1100205"],
        "TP_CATEGORIA_ADMINISTRATIVA": ["6"],
        "QT_DOCENTE_EXE": ["50"] # 2009
    })
    
    folder_inep = base_dir / "higher-education-census"
    folder_inep.mkdir(parents=True, exist_ok=True)
    zip_path = folder_inep / "higher-education-census_2009.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr("cadastro_cursos.csv", courses.write_csv(separator=";"))
        z.writestr("_ies_.csv", hei.write_csv(separator=";"))
        
    mock_munis = pl.DataFrame({"municipality_code": ["1100205"]})
    df = higher_education_census.harmonize(base_dir, mock_munis)
    
    assert df["category"][0] == "private"
    assert df["hq_teachers"][0] == 50

def test_sorting_and_uniqueness(base_dir, sample_dir, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    create_zip(base_dir, 2023, sample_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    courses = pl.read_csv(sample_dir / "higher_education_census_courses_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    hei = pl.read_csv(sample_dir / "higher_education_census_hei_2023_sample.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    munis = set(courses["CO_MUNICIPIO"].to_list() + hei["CO_MUNICIPIO_IES"].to_list())
    mock_munis = pl.DataFrame({"municipality_code": list(munis)})
    
    df = higher_education_census.harmonize(base_dir, mock_munis)
    
    assert len(df.unique(subset=["municipality_code", "year", "category"])) == len(df)
    # test sort
    df_sorted = df.sort(["municipality_code", "year", "category"])
    assert df.equals(df_sorted)

def test_errors(base_dir, sample_dir, monkeypatch):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    mock_munis = pl.DataFrame({"municipality_code": ["1100205"]})
    
    def write_zip(courses, hei):
        folder_inep = base_dir / "higher-education-census"
        folder_inep.mkdir(parents=True, exist_ok=True)
        zip_path = folder_inep / "higher-education-census_2023.zip"
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.writestr("cadastro_cursos.csv", courses.write_csv(separator=";"))
            z.writestr("_ies_.csv", hei.write_csv(separator=";"))
    
    # Category outside the list
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["99"], "QT_MAT": ["100"]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["99"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="invalid values in TP_CATEGORIA_ADMINISTRATIVA"):
        higher_education_census.harmonize(base_dir, mock_munis)
        
    # Municipality outside the table
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["9999999"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": ["100"]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="invalid or null municipalities in CO_MUNICIPIO"):
        higher_education_census.harmonize(base_dir, mock_munis)
        
    # QT_MAT non-int
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": ["a"]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="non-integer, negative or empty values in column QT_MAT"):
        higher_education_census.harmonize(base_dir, mock_munis)
        
    # IES absent from the IES table
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": ["100"]}),
        pl.DataFrame({"CO_IES": ["2"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="institution with an on-campus course missing"):
        higher_education_census.harmonize(base_dir, mock_munis)
        

    # QT_MAT empty in an in-person row
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": [""]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="non-integer, negative or empty values in column QT_MAT"):
        higher_education_census.harmonize(base_dir, mock_munis)
        
    # Without IES file
    folder_inep = base_dir / "higher-education-census"
    zip_path = folder_inep / "higher-education-census_2023.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr("cadastro_cursos.csv", pl.DataFrame({"A": [1]}).write_csv(separator=";"))
    with pytest.raises(ValueError, match="expected exactly 1 CSV file of HEI"):
        higher_education_census.harmonize(base_dir, mock_munis)

def test_download(base_dir, monkeypatch):
    calls = []
    
    def fake_download_batch(reqs, folder, validate, interval, **kwargs):
        calls.extend(reqs)
        
    monkeypatch.setattr(higher_education_census, "download_batch", fake_download_batch)
    
    higher_education_census.download(base_dir)
    assert len(calls) == 25
    assert calls[0].key == "higher-education-census/2000"
    assert calls[0].file == "higher-education-census/higher-education-census_2000.zip"
    assert calls[0].url == "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2000.zip"
    assert calls[0].compress is False

    # case where the manifest already has the key and the file exists
    monkeypatch.setattr(higher_education_census, "ALL_YEARS", [2023])
    
    class FailingSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("Must not call the network")
        def post(self, *args, **kwargs):
            raise RuntimeError("Must not call the network")
            
    # Create folder and manifest with existing file
    folder_inep = base_dir / "higher-education-census"
    folder_inep.mkdir(parents=True, exist_ok=True)
    file = folder_inep / "higher-education-census_2023.zip"
    file.write_bytes(b"PK\x03\x04" + b"X" * 100) # zip mock
    
    sha256 = hashlib.sha256(file.read_bytes()).hexdigest()
    
    manifest = {
        "higher-education-census/2023": {
            "file": "higher-education-census/higher-education-census_2023.zip",
            "method": "GET",
            "url": "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2023.zip",
            "bytes": file.stat().st_size,
            "sha256": sha256
        }
    }
    with open(base_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)
        
    # calls download for real, but with injected session
    monkeypatch.setattr(higher_education_census, "download_batch", core_download_batch)
    
    higher_education_census.download(base_dir, session=FailingSession())


@pytest.fixture
def mock_legacy_municipalities():
    return pl.DataFrame({
        "municipality_code": ["5103403", "4314902", "1100205", "3550308", "5002704"]
    })

def create_mock_zip(tmp_path, year, sample_dir):
    z_path = tmp_path / "higher-education-census" / f"higher-education-census_{year}.zip"
    z_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z_path, "w") as z:
        z.write(f"{sample_dir}/higher_education_census_{year}_undergraduate_sample.csv", "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write(f"{sample_dir}/higher_education_census_{year}_sequential_sample.csv", "DADOS/FORME_PRESENCIAL.CSV")
        z.write(f"{sample_dir}/higher_education_census_{year}_institution_sample.csv", "DADOS/INSTITUICAO.CSV")
    return tmp_path

def test_legacy_case_01_schema(tmp_path, mock_legacy_municipalities, sample_dir):
    munis = set()
    for year in [2000, 2007, 2008]:
        for prefix in ["undergraduate", "sequential", "institution"]:
            df = pl.read_csv(sample_dir / f"higher_education_census_{year}_{prefix}_sample.csv", separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
            df = df.rename({col: col.strip() for col in df.columns})
            df = df.select(pl.all().str.strip_chars())
            
            for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
                if col in df.columns:
                    for val in df[col].drop_nulls().to_list():
                        if len(val) == 12:
                            val = val[:2] + val[7:12]
                        munis.add(val)
    
    valid_municipalities = munis
    
    folder = create_mock_zip(tmp_path, 2000, sample_dir)
    c, i = higher_education_census.read_legacy_year(folder, 2000, valid_municipalities)
    df_year = higher_education_census.aggregate(c, i, 2000)
    
    assert list(df_year.columns) == ["municipality_code", "category", "institutions", "enrollments", "hq_institutions", "hq_teachers", "year"]
    assert df_year.schema["municipality_code"] == pl.Utf8
    assert df_year.schema["year"] == pl.Int16
    assert df_year.schema["category"] == pl.Utf8
    assert df_year.schema["institutions"] == pl.Int64
    assert df_year.schema["enrollments"] == pl.Int64
    assert df_year.schema["hq_institutions"] == pl.Int64
    assert df_year.schema["hq_teachers"] == pl.Int64

def _get_year(year, tmp_path, sample_dir):
    munis = set()
    for prefix in ["undergraduate", "sequential", "institution"]:
        df = pl.read_csv(sample_dir / f"higher_education_census_{year}_{prefix}_sample.csv", separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
        df = df.rename({col: col.strip() for col in df.columns})
        df = df.select(pl.all().str.strip_chars())
        for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
            if col in df.columns:
                for val in df[col].drop_nulls().to_list():
                    if len(val) == 12:
                        val = val[:2] + val[7:12]
                    munis.add(val)
    folder = create_mock_zip(tmp_path, year, sample_dir)
    c, i = higher_education_census.read_legacy_year(folder, year, munis)
    return higher_education_census.aggregate(c, i, year)

def test_legacy_case_02_simple(tmp_path, sample_dir):
    df_year = _get_year(2000, tmp_path, sample_dir)
    res = df_year.filter((pl.col("municipality_code") == "3205309") & (pl.col("category") == "private")).row(0, named=True)
    assert res["institutions"] == 2
    assert res["enrollments"] == 1127
    assert res["hq_institutions"] == 2
    assert res["hq_teachers"] == 27

def test_legacy_case_03_sequential(tmp_path, sample_dir):
    df_2000 = _get_year(2000, tmp_path, sample_dir)
    res = df_2000.filter((pl.col("municipality_code") == "4318309") & (pl.col("category") == "private")).row(0, named=True)
    assert res["enrollments"] == 1262
    
    df_2007 = _get_year(2007, tmp_path, sample_dir)
    res = df_2007.filter((pl.col("municipality_code") == "3550308") & (pl.col("category") == "private")).row(0, named=True)
    assert res["institutions"] == 1
    assert res["enrollments"] == 154
    assert res["hq_institutions"] == 1
    assert res["hq_teachers"] == 584

def test_legacy_case_04_empty_counts_as_zero(tmp_path, sample_dir):
    df_2000 = _get_year(2000, tmp_path, sample_dir)
    res = df_2000.filter((pl.col("municipality_code") == "3301009") & (pl.col("category") == "federal")).row(0, named=True)
    assert res["institutions"] == 1
    assert res["enrollments"] == 143
    assert res["hq_institutions"] == 1
    assert res["hq_teachers"] == 51

def test_legacy_case_05_teachers(tmp_path, sample_dir):
    df_2000 = _get_year(2000, tmp_path, sample_dir)
    res = df_2000.filter((pl.col("municipality_code") == "3548708") & (pl.col("category") == "private")).row(0, named=True)
    assert res["hq_teachers"] == 25
    
    res2 = df_2000.filter((pl.col("municipality_code") == "4301602") & (pl.col("category") == "private")).row(0, named=True)
    assert res2["hq_teachers"] == 875
    
    df_2007 = _get_year(2007, tmp_path, sample_dir)
    res3 = df_2007.filter((pl.col("municipality_code") == "4204202") & (pl.col("category") == "private")).row(0, named=True)
    assert res3["hq_teachers"] == 452

def test_legacy_case_06_leading_zeros(tmp_path, sample_dir):
    df_2007 = _get_year(2007, tmp_path, sample_dir)
    res = df_2007.filter((pl.col("municipality_code") == "5107040") & (pl.col("category") == "private")).row(0, named=True)
    assert res["institutions"] == 1
    assert res["enrollments"] == 382
    assert res["hq_institutions"] == 1
    assert res["hq_teachers"] == 92

def test_legacy_case_07_hei_2008(tmp_path, sample_dir):
    df_2008 = _get_year(2008, tmp_path, sample_dir)
    res = df_2008.filter((pl.col("municipality_code") == "1600303") & (pl.col("category") == "federal")).row(0, named=True)
    assert res["institutions"] == 1
    assert res["enrollments"] == 7346
    assert res["hq_institutions"] == 1
    assert res["hq_teachers"] == 172

def test_legacy_case_08_hei_without_course(tmp_path, sample_dir):
    df_2007 = _get_year(2007, tmp_path, sample_dir)
    assert len(df_2007.filter(pl.col("municipality_code") == "5221809")) == 0
    
    df_2008 = _get_year(2008, tmp_path, sample_dir)
    assert len(df_2008.filter(pl.col("municipality_code") == "4105508")) == 0

def test_legacy_case_09_course_outside(tmp_path, sample_dir):
    df_2008 = _get_year(2008, tmp_path, sample_dir)
    res = df_2008.filter((pl.col("municipality_code") == "1600279") & (pl.col("category") == "federal")).row(0, named=True)
    assert res["institutions"] == 1
    assert res["enrollments"] == 195
    assert res["hq_institutions"] == 0
    assert res["hq_teachers"] == 0

def test_legacy_case_10_errors(tmp_path, sample_dir):
    valid_municipalities = {"5103403", "4314902", "1100205", "3550308", "5002704"}
    folder = create_mock_zip(tmp_path, 2000, sample_dir)
    
    z_path = tmp_path / "higher-education-census" / "higher-education-census_2000.zip"
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        
        lines = (sample_dir / "higher_education_census_2000_institution_sample.csv").read_bytes().splitlines(True)
        corrupted = lines[0] + lines[1].replace(b"PRIVADA", b"INEXISTENTE") + b"".join(lines[2:])
        z.writestr("DADOS/INSTITUICAO.CSV", corrupted)
        
    with pytest.raises(ValueError, match="CATEGADM outside the list"):
        higher_education_census.read_legacy_year(folder, 2000, valid_municipalities)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_institution_sample.csv"), "DADOS/INSTITUICAO.CSV")
        
    with pytest.raises(ValueError, match="invalid or null municipalities in the courses table|invalid or null municipalities in the HEI table"):
        higher_education_census.read_legacy_year(folder, 2000, {"9999999"})
        
    with zipfile.ZipFile(z_path, "w") as z:
        lines = (sample_dir / "higher_education_census_2000_undergraduate_sample.csv").read_text(encoding="latin1").splitlines(True)
        idx = lines[0].split("|").index("C0421")
        parts = lines[1].split("|")
        parts[idx] = "ABC"
        corrupted = "|".join(parts)
        out_lines = lines[0] + corrupted + "".join(lines[2:])
        z.writestr("DADOS/GRADUACAO_PRESENCIAL.CSV", out_lines.encode("latin1"))
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_institution_sample.csv"), "DADOS/INSTITUICAO.CSV")
        
    with pytest.raises(ValueError, match="non-integer or negative value"):
        higher_education_census.read_legacy_year(folder, 2000, valid_municipalities)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        lines = (sample_dir / "higher_education_census_2000_institution_sample.csv").read_bytes().splitlines(True)
        z.writestr("DADOS/INSTITUICAO.CSV", lines[0])
        
    with pytest.raises(ValueError, match="course of an institution that is not in INSTITUICAO.CSV"):
        munis = set()
        df = pl.read_csv((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
        df = df.rename({col: col.strip() for col in df.columns})
        df = df.select(pl.all().str.strip_chars())
        for val in df["CODMUNICCURSO"].drop_nulls().to_list():
            if len(val) == 12:
                val = val[:2] + val[7:12]
            munis.add(val)
        higher_education_census.read_legacy_year(folder, 2000, munis)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_institution_sample.csv"), "DADOS/INSTITUICAO.CSV")
        
    with pytest.raises(ValueError, match="expected exactly 1 CSV file of forme_presencial.csv in the ZIP"):
        higher_education_census.read_legacy_year(folder, 2000, valid_municipalities)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        lines = (sample_dir / "higher_education_census_2000_institution_sample.csv").read_bytes().splitlines(True)
        corrupted = lines[1].replace(b"2000", b"2001")
        z.writestr("DADOS/INSTITUICAO.CSV", lines[0] + corrupted + b"".join(lines[2:]))
        
    with pytest.raises(ValueError, match="ANO differs from the package year"):
        higher_education_census.read_legacy_year(folder, 2000, valid_municipalities)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((sample_dir / "higher_education_census_2000_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        lines = (sample_dir / "higher_education_census_2000_institution_sample.csv").read_text(encoding="latin1").splitlines(True)
        idx = lines[0].split("|").index("I1111")
        parts = lines[1].split("|")
        parts[idx] = "999999"
        corrupted = "|".join(parts)
        z.writestr("DADOS/INSTITUICAO.CSV", (lines[0] + corrupted + "".join(lines[2:])).encode("latin1"))
        
    with pytest.raises(ValueError, match="more teachers on leave than the total"):
        higher_education_census.read_legacy_year(folder, 2000, munis)

    # Negative in enrollment
    with zipfile.ZipFile(z_path, "w") as z:
        lines = (sample_dir / "higher_education_census_2000_undergraduate_sample.csv").read_text(encoding="latin1").splitlines(True)
        idx = lines[0].split("|").index("C0421")
        parts = lines[1].split("|")
        parts[idx] = "-4"
        corrupted = "|".join(parts)
        out_lines = lines[0] + corrupted + "".join(lines[2:])
        z.writestr("DADOS/GRADUACAO_PRESENCIAL.CSV", out_lines.encode("latin1"))
        z.write((sample_dir / "higher_education_census_2000_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2000_institution_sample.csv"), "DADOS/INSTITUICAO.CSV")
    with pytest.raises(ValueError, match="non-integer or negative value in C0421"):
        higher_education_census.read_legacy_year(folder, 2000, munis)

    # 2007 package without I44
    folder2007 = create_mock_zip(tmp_path, 2007, sample_dir)
    z_path_2007 = tmp_path / "higher-education-census" / "higher-education-census_2007.zip"
    with zipfile.ZipFile(z_path_2007, "w") as z:
        z.write((sample_dir / "higher_education_census_2007_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2007_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        
        lines = (sample_dir / "higher_education_census_2007_institution_sample.csv").read_text(encoding="latin1").splitlines(True)
        headers = lines[0].split("|")
        idx_to_keep = [i for i, h in enumerate(headers) if not h.startswith("I44")]
        
        new_lines = []
        for line in lines:
            parts = line.split("|")
            new_lines.append("|".join([parts[i] for i in idx_to_keep]))
        z.writestr("DADOS/INSTITUICAO.CSV", "".join(new_lines).encode("latin1"))
        
    munis_2007 = set()
    for prefix in ["undergraduate", "sequential", "institution"]:
        df = pl.read_csv(sample_dir / f"higher_education_census_2007_{prefix}_sample.csv", separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
        df = df.rename({col: col.strip() for col in df.columns})
        df = df.select(pl.all().str.strip_chars())
        for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
            if col in df.columns:
                for val in df[col].drop_nulls().to_list():
                    if len(val) == 12:
                        val = val[:2] + val[7:12]
                    munis_2007.add(val)
    with pytest.raises(ValueError, match="no I44 column found"):
        higher_education_census.read_legacy_year(folder2007, 2007, munis_2007)

def test_legacy_case_11_harmonize_legacy_and_current(tmp_path, monkeypatch, sample_dir):
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [2008])
    monkeypatch.setattr(higher_education_census, "CURRENT_YEARS", [2023])
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [])
    
    folder = tmp_path / "higher-education-census"
    folder.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(folder / "higher-education-census_2008.zip", "w") as z:
        z.write((sample_dir / "higher_education_census_2008_undergraduate_sample.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2008_sequential_sample.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((sample_dir / "higher_education_census_2008_institution_sample.csv"), "DADOS/INSTITUICAO.CSV")
        
    with zipfile.ZipFile(folder / "higher-education-census_2023.zip", "w") as z:
        z.write((sample_dir / "higher_education_census_courses_2023_sample.csv"), "DADOS/CADASTRO_CURSOS.CSV")
        z.write((sample_dir / "higher_education_census_hei_2023_sample.csv"), "DADOS/MICRODADOS_ED_SUP_IES_2023.CSV")
        
    munis = set()
    for f in ["higher_education_census_2008_undergraduate_sample.csv", "higher_education_census_courses_2023_sample.csv", "higher_education_census_hei_2023_sample.csv", "higher_education_census_2008_institution_sample.csv"]:
        if "2023" in f:
            df = pl.read_csv(sample_dir / f, separator=";", encoding="utf8-lossy", infer_schema_length=0)
            for c in ["CO_MUNICIPIO", "CO_MUNICIPIO_IES"]:
                if c in df.columns:
                    munis.update(df[c].drop_nulls().to_list())
        else:
            df = pl.read_csv(sample_dir / f, separator="|", encoding="utf8-lossy", infer_schema_length=0)
            df = df.rename({col: col.strip() for col in df.columns})
            df = df.select(pl.all().str.strip_chars())
            for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
                if col in df.columns:
                    for val in df[col].drop_nulls().to_list():
                        if len(val) == 12:
                            val = val[:2] + val[7:12]
                        munis.add(val)
    
    municipalities_df = pl.DataFrame({"municipality_code": list(munis)})
    
    # harmonize reads higher_education_census.LEGACY_YEARS, which is why the constant is replaced here
    monkeypatch.setattr(higher_education_census, "LEGACY_YEARS", [2008])
    
    df_final = higher_education_census.harmonize(tmp_path, municipalities_df)
    
    assert len(df_final.filter(pl.col("year") == 2008)) == 6
    assert df_final.equals(df_final.sort(["municipality_code", "year", "category"]))
    assert df_final.shape[0] == df_final.select(["municipality_code", "year", "category"]).n_unique()
    
    df_2023_alone = higher_education_census.aggregate(*higher_education_census.read_current_year(tmp_path, 2023, munis), 2023)
    df_2023_in_final = df_final.filter(pl.col("year") == 2023)
    
    df_2023_alone = df_2023_alone.sort(["municipality_code", "year", "category"]).select(df_final.columns)
    assert df_2023_in_final.equals(df_2023_alone)


def test_download_uses_the_inep_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    def mock_download_batch(reqs, folder, **options):
        calls.append(options)

    monkeypatch.setattr(higher_education_census, "download_batch", mock_download_batch)

    from brmunipanel.inep import connection
    import requests

    # Case 1: without session provided
    higher_education_census.download(tmp_path)
    assert len(calls) == 1
    session_default = calls[0].get("session")
    assert isinstance(session_default, requests.Session)
    assert session_default.verify == str(connection.certificate_authorities())

    # Case 2: with explicit session
    obj_session = requests.Session()
    higher_education_census.download(tmp_path, session=obj_session)
    assert len(calls) == 2
    session_custom = calls[1].get("session")
    assert session_custom is obj_session

