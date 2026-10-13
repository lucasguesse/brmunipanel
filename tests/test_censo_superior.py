import hashlib
import json
import zipfile
import pytest
import polars as pl
from pathlib import Path

from brmunipanel.inep import censo_superior
from brmunipanel.nucleo import baixar_lote as baixar_lote_do_nucleo


@pytest.fixture
def base_dir(tmp_path):
    return tmp_path

@pytest.fixture
def amostra_dir():
    return Path(__file__).parent / "dados"

@pytest.fixture
def mock_municipios():
    return pl.DataFrame({"cod_municipio": ["1100205", "1501402", "3550308", "4106902", "5300108"]})

def create_zip(pasta: Path, ano: int, amostra_dir: Path, cursos_name="cadastro_cursos", ies_name="_ies_"):
    pasta_inep = pasta / "censo-superior"
    pasta_inep.mkdir(parents=True, exist_ok=True)
    zip_path = pasta_inep / f"censo-superior_{ano}.zip"
    
    with zipfile.ZipFile(zip_path, 'w') as z:
        if cursos_name:
            z.write(amostra_dir / f"censo_superior_cursos_{ano}_amostra.csv", arcname=f"{cursos_name}.csv")
        if ies_name:
            z.write(amostra_dir / f"censo_superior_ies_{ano}_amostra.csv", arcname=f"{ies_name}.csv")

def test_esquema(base_dir, amostra_dir, mock_municipios, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    create_zip(base_dir, 2023, amostra_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    # Need to add sample municipality codes to the mock
    cursos = pl.read_csv(amostra_dir / "censo_superior_cursos_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    ies = pl.read_csv(amostra_dir / "censo_superior_ies_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    muns = set(cursos["CO_MUNICIPIO"].to_list() + ies["CO_MUNICIPIO_IES"].to_list())
    mock_muns = pl.DataFrame({"cod_municipio": list(muns)})
    
    df = censo_superior.harmonizar(base_dir, mock_muns)
    
    colunas_esp = ["cod_municipio", "ano", "categoria", "instituicoes", "matriculas", "instituicoes_sede", "docentes_sede"]
    assert df.columns == colunas_esp
    
    assert df.schema["cod_municipio"] == pl.Utf8
    assert df.schema["ano"] == pl.Int16
    assert df.schema["categoria"] == pl.Utf8
    assert df.schema["instituicoes"] == pl.Int64
    assert df.schema["matriculas"] == pl.Int64
    assert df.schema["instituicoes_sede"] == pl.Int64
    assert df.schema["docentes_sede"] == pl.Int64

def test_distancia_e_sem_curso(base_dir, amostra_dir, mock_municipios, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    create_zip(base_dir, 2023, amostra_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    cursos = pl.read_csv(amostra_dir / "censo_superior_cursos_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    ies = pl.read_csv(amostra_dir / "censo_superior_ies_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    muns = set(cursos["CO_MUNICIPIO"].to_list() + ies["CO_MUNICIPIO_IES"].to_list())
    mock_muns = pl.DataFrame({"cod_municipio": list(muns)})
    
    df = censo_superior.harmonizar(base_dir, mock_muns)
    
    assert df["instituicoes_sede"].sum() == 1

def test_valores(base_dir, amostra_dir, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    create_zip(base_dir, 2023, amostra_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    cursos = pl.read_csv(amostra_dir / "censo_superior_cursos_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    ies = pl.read_csv(amostra_dir / "censo_superior_ies_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    muns = set(cursos["CO_MUNICIPIO"].to_list() + ies["CO_MUNICIPIO_IES"].to_list())
    mock_muns = pl.DataFrame({"cod_municipio": list(muns)})
    
    df = censo_superior.harmonizar(base_dir, mock_muns)
    
    pres = cursos.filter(pl.col("TP_MODALIDADE_ENSINO") == "1")
    if len(pres) > 0:
        mun = pres["CO_MUNICIPIO"][0]
        cat_id = pres["TP_CATEGORIA_ADMINISTRATIVA"][0]
        cat_map = {"1": "federal", "2": "estadual", "3": "municipal", "4": "privada", "5": "privada", "6": "privada", "8": "privada", "9": "privada", "7": "especial"}
        cat = cat_map[cat_id]
        
        pres_grupo = pres.filter((pl.col("CO_MUNICIPIO") == mun) & (pl.col("TP_CATEGORIA_ADMINISTRATIVA") == cat_id))
        mat_esp = sum([int(x) if x else 0 for x in pres_grupo["QT_MAT"].to_list()])
        
        row = df.filter((pl.col("cod_municipio") == mun) & (pl.col("categoria") == cat))
        assert row["matriculas"][0] == mat_esp

def test_duas_instituicoes_mesmo_mun(base_dir, amostra_dir, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    create_zip(base_dir, 2023, amostra_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    cursos = pl.read_csv(amostra_dir / "censo_superior_cursos_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    ies = pl.read_csv(amostra_dir / "censo_superior_ies_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    
    # Create duplicate course for the same IES in the same municipality
    pres = cursos.filter(pl.col("TP_MODALIDADE_ENSINO") == "1")
    if len(pres) > 0:
        row1 = pres.row(0, named=True)
        # force a duplicate IES
        cursos_duplicados = pl.concat([cursos, pl.DataFrame([row1])])
        
        caminho_csv = base_dir / "mod_cursos.csv"
        cursos_duplicados.write_csv(caminho_csv, separator=";")
        
        zip_path = base_dir / "censo-superior" / "censo-superior_2023.zip"
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(caminho_csv, arcname="MICRODADOS_CADASTRO_CURSOS_2023.CSV")
            z.write(amostra_dir / "censo_superior_ies_2023_amostra.csv", arcname="MICRODADOS_CADASTRO_IES_2023.CSV")
            
        muns = set(cursos_duplicados["CO_MUNICIPIO"].to_list() + ies["CO_MUNICIPIO_IES"].to_list())
        mock_muns = pl.DataFrame({"cod_municipio": list(muns)})
        df = censo_superior.harmonizar(base_dir, mock_muns)
        
        cat_map = {"1": "federal", "2": "estadual", "3": "municipal", "4": "privada", "5": "privada", "6": "privada", "8": "privada", "9": "privada", "7": "especial"}
        cat = cat_map[row1["TP_CATEGORIA_ADMINISTRATIVA"]]
        
        row_agg = df.filter((pl.col("cod_municipio") == row1["CO_MUNICIPIO"]) & (pl.col("categoria") == cat))
        
        # The IES has 2 courses, but only counts as 1 in instituicoes
        # Checks whether the number of IES in that group matches the manual unique count
        pres_grupo = cursos_duplicados.filter(
            (pl.col("CO_MUNICIPIO") == row1["CO_MUNICIPIO"]) & 
            (pl.col("TP_CATEGORIA_ADMINISTRATIVA") == row1["TP_CATEGORIA_ADMINISTRATIVA"]) &
            (pl.col("TP_MODALIDADE_ENSINO") == "1")
        )
        ies_count_esp = pres_grupo["CO_IES"].n_unique()
        assert row_agg["instituicoes"][0] == ies_count_esp

def test_grupo_so_sede_ou_so_curso(base_dir, amostra_dir, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    
    cursos = pl.DataFrame({
        "CO_MUNICIPIO": ["1100205"],
        "CO_IES": ["1"],
        "TP_MODALIDADE_ENSINO": ["1"],
        "TP_CATEGORIA_ADMINISTRATIVA": ["1"],
        "QT_MAT": ["100"]
    })
    ies = pl.DataFrame({
        "CO_IES": ["1"],
        "CO_MUNICIPIO_IES": ["5300108"], # Different seat
        "TP_CATEGORIA_ADMINISTRATIVA": ["1"],
        "QT_DOC_EXE": ["50"]
    })
    
    pasta_inep = base_dir / "censo-superior"
    pasta_inep.mkdir(parents=True, exist_ok=True)
    zip_path = pasta_inep / "censo-superior_2023.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr("cadastro_cursos.csv", cursos.write_csv(separator=";"))
        z.writestr("_ies_.csv", ies.write_csv(separator=";"))
        
    mock_muns = pl.DataFrame({"cod_municipio": ["1100205", "5300108"]})
    df = censo_superior.harmonizar(base_dir, mock_muns)
    
    # 1100205 = course, enrollments; seat = 0
    row_curso = df.filter(pl.col("cod_municipio") == "1100205")
    assert row_curso["instituicoes"][0] == 1
    assert row_curso["matriculas"][0] == 100
    assert row_curso["instituicoes_sede"][0] == 0
    assert row_curso["docentes_sede"][0] == 0
    
    # 5300108 = seat; course = 0
    row_sede = df.filter(pl.col("cod_municipio") == "5300108")
    assert row_sede["instituicoes"][0] == 0
    assert row_sede["matriculas"][0] == 0
    assert row_sede["instituicoes_sede"][0] == 1
    assert row_sede["docentes_sede"][0] == 50

def test_codigos_antigos_2009(base_dir, amostra_dir, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2009])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    
    cursos = pl.DataFrame({
        "CO_MUNICIPIO": ["1100205"],
        "CO_IES": ["1"],
        "TP_MODALIDADE_ENSINO": ["1"],
        "TP_CATEGORIA_ADMINISTRATIVA": ["6"], # 6, 8, 9 become privada
        "QT_MAT": ["100"]
    })
    ies = pl.DataFrame({
        "CO_IES": ["1"],
        "CO_MUNICIPIO_IES": ["1100205"],
        "TP_CATEGORIA_ADMINISTRATIVA": ["6"],
        "QT_DOCENTE_EXE": ["50"] # 2009
    })
    
    pasta_inep = base_dir / "censo-superior"
    pasta_inep.mkdir(parents=True, exist_ok=True)
    zip_path = pasta_inep / "censo-superior_2009.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr("cadastro_cursos.csv", cursos.write_csv(separator=";"))
        z.writestr("_ies_.csv", ies.write_csv(separator=";"))
        
    mock_muns = pl.DataFrame({"cod_municipio": ["1100205"]})
    df = censo_superior.harmonizar(base_dir, mock_muns)
    
    assert df["categoria"][0] == "privada"
    assert df["docentes_sede"][0] == 50

def test_ordenacao_e_unica(base_dir, amostra_dir, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    create_zip(base_dir, 2023, amostra_dir, "MICRODADOS_CADASTRO_CURSOS_2023", "MICRODADOS_CADASTRO_IES_2023")
    
    cursos = pl.read_csv(amostra_dir / "censo_superior_cursos_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    ies = pl.read_csv(amostra_dir / "censo_superior_ies_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    muns = set(cursos["CO_MUNICIPIO"].to_list() + ies["CO_MUNICIPIO_IES"].to_list())
    mock_muns = pl.DataFrame({"cod_municipio": list(muns)})
    
    df = censo_superior.harmonizar(base_dir, mock_muns)
    
    assert len(df.unique(subset=["cod_municipio", "ano", "categoria"])) == len(df)
    # test sort
    df_sorted = df.sort(["cod_municipio", "ano", "categoria"])
    assert df.equals(df_sorted)

def test_erros(base_dir, amostra_dir, monkeypatch):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    mock_muns = pl.DataFrame({"cod_municipio": ["1100205"]})
    
    def write_zip(cursos, ies):
        pasta_inep = base_dir / "censo-superior"
        pasta_inep.mkdir(parents=True, exist_ok=True)
        zip_path = pasta_inep / "censo-superior_2023.zip"
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.writestr("cadastro_cursos.csv", cursos.write_csv(separator=";"))
            z.writestr("_ies_.csv", ies.write_csv(separator=";"))
    
    # Category outside the list
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["99"], "QT_MAT": ["100"]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["99"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="Valores inválidos em TP_CATEGORIA_ADMINISTRATIVA"):
        censo_superior.harmonizar(base_dir, mock_muns)
        
    # Municipality outside the table
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["9999999"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": ["100"]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="Municípios inválidos ou nulos em CO_MUNICIPIO"):
        censo_superior.harmonizar(base_dir, mock_muns)
        
    # QT_MAT non-int
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": ["a"]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="Valores não inteiros, negativos ou vazios na coluna QT_MAT"):
        censo_superior.harmonizar(base_dir, mock_muns)
        
    # IES absent from the IES table
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": ["100"]}),
        pl.DataFrame({"CO_IES": ["2"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="Instituição com curso presencial ausente"):
        censo_superior.harmonizar(base_dir, mock_muns)
        

    # QT_MAT empty in an in-person row
    write_zip(
        pl.DataFrame({"CO_MUNICIPIO": ["1100205"], "CO_IES": ["1"], "TP_MODALIDADE_ENSINO": ["1"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_MAT": [""]}),
        pl.DataFrame({"CO_IES": ["1"], "CO_MUNICIPIO_IES": ["1100205"], "TP_CATEGORIA_ADMINISTRATIVA": ["1"], "QT_DOC_EXE": ["50"]})
    )
    with pytest.raises(ValueError, match="Valores não inteiros, negativos ou vazios na coluna QT_MAT"):
        censo_superior.harmonizar(base_dir, mock_muns)
        
    # Without IES file
    pasta_inep = base_dir / "censo-superior"
    zip_path = pasta_inep / "censo-superior_2023.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.writestr("cadastro_cursos.csv", pl.DataFrame({"A": [1]}).write_csv(separator=";"))
    with pytest.raises(ValueError, match="esperado exatamente 1 arquivo CSV de IES"):
        censo_superior.harmonizar(base_dir, mock_muns)

def test_baixar(base_dir, monkeypatch):
    calls = []
    
    def fake_baixar_lote(reqs, pasta, validar, intervalo, **kwargs):
        calls.extend(reqs)
        
    monkeypatch.setattr(censo_superior, "baixar_lote", fake_baixar_lote)
    
    censo_superior.baixar(base_dir)
    assert len(calls) == 25
    assert calls[0].chave == "censo-superior/2000"
    assert calls[0].arquivo == "censo-superior/censo-superior_2000.zip"
    assert calls[0].url == "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2000.zip"
    assert calls[0].compactar is False

    # case where the manifest already has the key and the file exists
    monkeypatch.setattr(censo_superior, "ANOS_TODOS", [2023])
    
    class SessaoFalha:
        def get(self, *args, **kwargs):
            raise RuntimeError("Não deveria chamar a rede")
        def post(self, *args, **kwargs):
            raise RuntimeError("Não deveria chamar a rede")
            
    # Create folder and manifest with existing file
    pasta_inep = base_dir / "censo-superior"
    pasta_inep.mkdir(parents=True, exist_ok=True)
    arquivo = pasta_inep / "censo-superior_2023.zip"
    arquivo.write_bytes(b"PK\x03\x04" + b"X" * 100) # zip mock
    
    sha256 = hashlib.sha256(arquivo.read_bytes()).hexdigest()
    
    manifesto = {
        "censo-superior/2023": {
            "arquivo": "censo-superior_2023.zip",
            "url": "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_2023.zip",
            "bytes": arquivo.stat().st_size,
            "sha256": sha256
        }
    }
    with open(base_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifesto, f)
        
    # calls baixar for real, but with injected session
    monkeypatch.setattr(censo_superior, "baixar_lote", baixar_lote_do_nucleo)
    
    censo_superior.baixar(base_dir, sessao=SessaoFalha())


@pytest.fixture
def mock_municipios_antigo():
    return pl.DataFrame({
        "cod_municipio": ["5103403", "4314902", "1100205", "3550308", "5002704"]
    })

def create_mock_zip(tmp_path, ano, amostra_dir):
    z_path = tmp_path / "censo-superior" / f"censo-superior_{ano}.zip"
    z_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z_path, "w") as z:
        z.write(f"{amostra_dir}/censo_superior_{ano}_graduacao_amostra.csv", "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write(f"{amostra_dir}/censo_superior_{ano}_sequencial_amostra.csv", "DADOS/FORME_PRESENCIAL.CSV")
        z.write(f"{amostra_dir}/censo_superior_{ano}_instituicao_amostra.csv", "DADOS/INSTITUICAO.CSV")
    return tmp_path

def test_antigo_caso_01_esquema(tmp_path, mock_municipios_antigo, amostra_dir):
    muns = set()
    for ano in [2000, 2007, 2008]:
        for prefix in ["graduacao", "sequencial", "instituicao"]:
            df = pl.read_csv(amostra_dir / f"censo_superior_{ano}_{prefix}_amostra.csv", separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
            df = df.rename({col: col.strip() for col in df.columns})
            df = df.select(pl.all().str.strip_chars())
            
            for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
                if col in df.columns:
                    for val in df[col].drop_nulls().to_list():
                        if len(val) == 12:
                            val = val[:2] + val[7:12]
                        muns.add(val)
    
    valid_municipios = muns
    
    pasta = create_mock_zip(tmp_path, 2000, amostra_dir)
    c, i = censo_superior.ler_ano_antigo(pasta, 2000, valid_municipios)
    df_ano = censo_superior.agregar(c, i, 2000)
    
    assert list(df_ano.columns) == ["cod_municipio", "categoria", "instituicoes", "matriculas", "instituicoes_sede", "docentes_sede", "ano"]
    assert df_ano.schema["cod_municipio"] == pl.Utf8
    assert df_ano.schema["ano"] == pl.Int16
    assert df_ano.schema["categoria"] == pl.Utf8
    assert df_ano.schema["instituicoes"] == pl.Int64
    assert df_ano.schema["matriculas"] == pl.Int64
    assert df_ano.schema["instituicoes_sede"] == pl.Int64
    assert df_ano.schema["docentes_sede"] == pl.Int64

def _get_ano(ano, tmp_path, amostra_dir):
    muns = set()
    for prefix in ["graduacao", "sequencial", "instituicao"]:
        df = pl.read_csv(amostra_dir / f"censo_superior_{ano}_{prefix}_amostra.csv", separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
        df = df.rename({col: col.strip() for col in df.columns})
        df = df.select(pl.all().str.strip_chars())
        for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
            if col in df.columns:
                for val in df[col].drop_nulls().to_list():
                    if len(val) == 12:
                        val = val[:2] + val[7:12]
                    muns.add(val)
    pasta = create_mock_zip(tmp_path, ano, amostra_dir)
    c, i = censo_superior.ler_ano_antigo(pasta, ano, muns)
    return censo_superior.agregar(c, i, ano)

def test_antigo_caso_02_simples(tmp_path, amostra_dir):
    df_ano = _get_ano(2000, tmp_path, amostra_dir)
    res = df_ano.filter((pl.col("cod_municipio") == "3205309") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res["instituicoes"] == 2
    assert res["matriculas"] == 1127
    assert res["instituicoes_sede"] == 2
    assert res["docentes_sede"] == 27

def test_antigo_caso_03_sequencial(tmp_path, amostra_dir):
    df_2000 = _get_ano(2000, tmp_path, amostra_dir)
    res = df_2000.filter((pl.col("cod_municipio") == "4318309") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res["matriculas"] == 1262
    
    df_2007 = _get_ano(2007, tmp_path, amostra_dir)
    res = df_2007.filter((pl.col("cod_municipio") == "3550308") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res["instituicoes"] == 1
    assert res["matriculas"] == 154
    assert res["instituicoes_sede"] == 1
    assert res["docentes_sede"] == 584

def test_antigo_caso_04_vazio_vale_zero(tmp_path, amostra_dir):
    df_2000 = _get_ano(2000, tmp_path, amostra_dir)
    res = df_2000.filter((pl.col("cod_municipio") == "3301009") & (pl.col("categoria") == "federal")).row(0, named=True)
    assert res["instituicoes"] == 1
    assert res["matriculas"] == 143
    assert res["instituicoes_sede"] == 1
    assert res["docentes_sede"] == 51

def test_antigo_caso_05_docentes(tmp_path, amostra_dir):
    df_2000 = _get_ano(2000, tmp_path, amostra_dir)
    res = df_2000.filter((pl.col("cod_municipio") == "3548708") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res["docentes_sede"] == 25
    
    res2 = df_2000.filter((pl.col("cod_municipio") == "4301602") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res2["docentes_sede"] == 875
    
    df_2007 = _get_ano(2007, tmp_path, amostra_dir)
    res3 = df_2007.filter((pl.col("cod_municipio") == "4204202") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res3["docentes_sede"] == 452

def test_antigo_caso_06_zeros_esquerda(tmp_path, amostra_dir):
    df_2007 = _get_ano(2007, tmp_path, amostra_dir)
    res = df_2007.filter((pl.col("cod_municipio") == "5107040") & (pl.col("categoria") == "privada")).row(0, named=True)
    assert res["instituicoes"] == 1
    assert res["matriculas"] == 382
    assert res["instituicoes_sede"] == 1
    assert res["docentes_sede"] == 92

def test_antigo_caso_07_ies_2008(tmp_path, amostra_dir):
    df_2008 = _get_ano(2008, tmp_path, amostra_dir)
    res = df_2008.filter((pl.col("cod_municipio") == "1600303") & (pl.col("categoria") == "federal")).row(0, named=True)
    assert res["instituicoes"] == 1
    assert res["matriculas"] == 7346
    assert res["instituicoes_sede"] == 1
    assert res["docentes_sede"] == 172

def test_antigo_caso_08_ies_sem_curso(tmp_path, amostra_dir):
    df_2007 = _get_ano(2007, tmp_path, amostra_dir)
    assert len(df_2007.filter(pl.col("cod_municipio") == "5221809")) == 0
    
    df_2008 = _get_ano(2008, tmp_path, amostra_dir)
    assert len(df_2008.filter(pl.col("cod_municipio") == "4105508")) == 0

def test_antigo_caso_09_curso_fora(tmp_path, amostra_dir):
    df_2008 = _get_ano(2008, tmp_path, amostra_dir)
    res = df_2008.filter((pl.col("cod_municipio") == "1600279") & (pl.col("categoria") == "federal")).row(0, named=True)
    assert res["instituicoes"] == 1
    assert res["matriculas"] == 195
    assert res["instituicoes_sede"] == 0
    assert res["docentes_sede"] == 0

def test_antigo_caso_10_erros(tmp_path, amostra_dir):
    valid_municipios = {"5103403", "4314902", "1100205", "3550308", "5002704"}
    pasta = create_mock_zip(tmp_path, 2000, amostra_dir)
    
    z_path = tmp_path / "censo-superior" / "censo-superior_2000.zip"
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        
        lines = (amostra_dir / "censo_superior_2000_instituicao_amostra.csv").read_bytes().splitlines(True)
        corrupted = lines[0] + lines[1].replace(b"PRIVADA", b"INEXISTENTE") + b"".join(lines[2:])
        z.writestr("DADOS/INSTITUICAO.CSV", corrupted)
        
    with pytest.raises(ValueError, match="CATEGADM fora da lista"):
        censo_superior.ler_ano_antigo(pasta, 2000, valid_municipios)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_instituicao_amostra.csv"), "DADOS/INSTITUICAO.CSV")
        
    with pytest.raises(ValueError, match="Municípios inválidos ou nulos na tabela de cursos|Municípios inválidos ou nulos na tabela de IES"):
        censo_superior.ler_ano_antigo(pasta, 2000, {"9999999"})
        
    with zipfile.ZipFile(z_path, "w") as z:
        lines = (amostra_dir / "censo_superior_2000_graduacao_amostra.csv").read_text(encoding="latin1").splitlines(True)
        idx = lines[0].split("|").index("C0421")
        parts = lines[1].split("|")
        parts[idx] = "ABC"
        corrupted = "|".join(parts)
        out_lines = lines[0] + corrupted + "".join(lines[2:])
        z.writestr("DADOS/GRADUACAO_PRESENCIAL.CSV", out_lines.encode("latin1"))
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_instituicao_amostra.csv"), "DADOS/INSTITUICAO.CSV")
        
    with pytest.raises(ValueError, match="Valor não inteiro ou negativo"):
        censo_superior.ler_ano_antigo(pasta, 2000, valid_municipios)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        lines = (amostra_dir / "censo_superior_2000_instituicao_amostra.csv").read_bytes().splitlines(True)
        z.writestr("DADOS/INSTITUICAO.CSV", lines[0])
        
    with pytest.raises(ValueError, match="Curso de instituição que não está em INSTITUICAO.CSV"):
        muns = set()
        df = pl.read_csv((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
        df = df.rename({col: col.strip() for col in df.columns})
        df = df.select(pl.all().str.strip_chars())
        for val in df["CODMUNICCURSO"].drop_nulls().to_list():
            if len(val) == 12: val = val[:2] + val[7:12]
            muns.add(val)
        censo_superior.ler_ano_antigo(pasta, 2000, muns)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_instituicao_amostra.csv"), "DADOS/INSTITUICAO.CSV")
        
    with pytest.raises(ValueError, match="esperado exatamente 1 arquivo CSV de forme_presencial.csv no ZIP"):
        censo_superior.ler_ano_antigo(pasta, 2000, valid_municipios)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        lines = (amostra_dir / "censo_superior_2000_instituicao_amostra.csv").read_bytes().splitlines(True)
        corrupted = lines[1].replace(b"2000", b"2001")
        z.writestr("DADOS/INSTITUICAO.CSV", lines[0] + corrupted + b"".join(lines[2:]))
        
    with pytest.raises(ValueError, match="ANO diferente do ano do pacote"):
        censo_superior.ler_ano_antigo(pasta, 2000, valid_municipios)
        
    with zipfile.ZipFile(z_path, "w") as z:
        z.write((amostra_dir / "censo_superior_2000_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        lines = (amostra_dir / "censo_superior_2000_instituicao_amostra.csv").read_text(encoding="latin1").splitlines(True)
        idx = lines[0].split("|").index("I1111")
        parts = lines[1].split("|")
        parts[idx] = "999999"
        corrupted = "|".join(parts)
        z.writestr("DADOS/INSTITUICAO.CSV", (lines[0] + corrupted + "".join(lines[2:])).encode("latin1"))
        
    with pytest.raises(ValueError, match="Mais afastados que o total"):
        censo_superior.ler_ano_antigo(pasta, 2000, muns)

    # Negative in enrollment
    with zipfile.ZipFile(z_path, "w") as z:
        lines = (amostra_dir / "censo_superior_2000_graduacao_amostra.csv").read_text(encoding="latin1").splitlines(True)
        idx = lines[0].split("|").index("C0421")
        parts = lines[1].split("|")
        parts[idx] = "-4"
        corrupted = "|".join(parts)
        out_lines = lines[0] + corrupted + "".join(lines[2:])
        z.writestr("DADOS/GRADUACAO_PRESENCIAL.CSV", out_lines.encode("latin1"))
        z.write((amostra_dir / "censo_superior_2000_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2000_instituicao_amostra.csv"), "DADOS/INSTITUICAO.CSV")
    with pytest.raises(ValueError, match="Valor não inteiro ou negativo em C0421"):
        censo_superior.ler_ano_antigo(pasta, 2000, muns)

    # 2007 package without I44
    pasta2007 = create_mock_zip(tmp_path, 2007, amostra_dir)
    z_path_2007 = tmp_path / "censo-superior" / "censo-superior_2007.zip"
    with zipfile.ZipFile(z_path_2007, "w") as z:
        z.write((amostra_dir / "censo_superior_2007_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2007_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        
        lines = (amostra_dir / "censo_superior_2007_instituicao_amostra.csv").read_text(encoding="latin1").splitlines(True)
        headers = lines[0].split("|")
        new_headers = [h for h in headers if not h.startswith("I44")]
        idx_to_keep = [i for i, h in enumerate(headers) if not h.startswith("I44")]
        
        new_lines = []
        for line in lines:
            parts = line.split("|")
            new_lines.append("|".join([parts[i] for i in idx_to_keep]))
        z.writestr("DADOS/INSTITUICAO.CSV", "".join(new_lines).encode("latin1"))
        
    muns_2007 = set()
    for prefix in ["graduacao", "sequencial", "instituicao"]:
        df = pl.read_csv(amostra_dir / f"censo_superior_2007_{prefix}_amostra.csv", separator="|", infer_schema_length=0, encoding="utf8-lossy", quote_char=None)
        df = df.rename({col: col.strip() for col in df.columns})
        df = df.select(pl.all().str.strip_chars())
        for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
            if col in df.columns:
                for val in df[col].drop_nulls().to_list():
                    if len(val) == 12: val = val[:2] + val[7:12]
                    muns_2007.add(val)
    with pytest.raises(ValueError, match="Nenhuma coluna I44 encontrada"):
        censo_superior.ler_ano_antigo(pasta2007, 2007, muns_2007)

def test_antigo_caso_11_harmonizar_antigo_atual(tmp_path, monkeypatch, amostra_dir):
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [2008])
    monkeypatch.setattr(censo_superior, "ANOS_ATUAIS", [2023])
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [])
    
    pasta = tmp_path / "censo-superior"
    pasta.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(pasta / "censo-superior_2008.zip", "w") as z:
        z.write((amostra_dir / "censo_superior_2008_graduacao_amostra.csv"), "DADOS/GRADUACAO_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2008_sequencial_amostra.csv"), "DADOS/FORME_PRESENCIAL.CSV")
        z.write((amostra_dir / "censo_superior_2008_instituicao_amostra.csv"), "DADOS/INSTITUICAO.CSV")
        
    with zipfile.ZipFile(pasta / "censo-superior_2023.zip", "w") as z:
        z.write((amostra_dir / "censo_superior_cursos_2023_amostra.csv"), "DADOS/CADASTRO_CURSOS.CSV")
        z.write((amostra_dir / "censo_superior_ies_2023_amostra.csv"), "DADOS/MICRODADOS_ED_SUP_IES_2023.CSV")
        
    muns = set()
    for f in ["censo_superior_2008_graduacao_amostra.csv", "censo_superior_cursos_2023_amostra.csv", "censo_superior_ies_2023_amostra.csv", "censo_superior_2008_instituicao_amostra.csv"]:
        if "2023" in f:
            df = pl.read_csv(amostra_dir / f, separator=";", encoding="utf8-lossy", infer_schema_length=0)
            for c in ["CO_MUNICIPIO", "CO_MUNICIPIO_IES"]:
                if c in df.columns:
                    muns.update(df[c].drop_nulls().to_list())
        else:
            df = pl.read_csv(amostra_dir / f, separator="|", encoding="utf8-lossy", infer_schema_length=0)
            df = df.rename({col: col.strip() for col in df.columns})
            df = df.select(pl.all().str.strip_chars())
            for col in ["CODMUNICCURSO", "CODMUNIC_CURSO", "CODMUNIC"]:
                if col in df.columns:
                    for val in df[col].drop_nulls().to_list():
                        if len(val) == 12: val = val[:2] + val[7:12]
                        muns.add(val)
    
    municipios_df = pl.DataFrame({"cod_municipio": list(muns)})
    
    # harmonizar reads censo_superior.ANOS_ANTIGOS, which is why the constant is replaced here
    monkeypatch.setattr(censo_superior, "ANOS_ANTIGOS", [2008])
    
    df_final = censo_superior.harmonizar(tmp_path, municipios_df)
    
    assert len(df_final.filter(pl.col("ano") == 2008)) == 6
    assert df_final.equals(df_final.sort(["cod_municipio", "ano", "categoria"]))
    assert df_final.shape[0] == df_final.select(["cod_municipio", "ano", "categoria"]).n_unique()
    
    df_2023_alone = censo_superior.agregar(*censo_superior.ler_ano_atual(tmp_path, 2023, muns), 2023)
    df_2023_in_final = df_final.filter(pl.col("ano") == 2023)
    
    df_2023_alone = df_2023_alone.sort(["cod_municipio", "ano", "categoria"]).select(df_final.columns)
    assert df_2023_in_final.equals(df_2023_alone)


def test_baixar_usa_a_sessao_do_inep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chamadas: list[dict] = []

    def mock_baixar_lote(reqs, pasta, **opcoes):
        chamadas.append(opcoes)

    monkeypatch.setattr(censo_superior, "baixar_lote", mock_baixar_lote)

    from brmunipanel.inep import conexao
    import requests

    # Case 1: without sessao provided
    censo_superior.baixar(tmp_path)
    assert len(chamadas) == 1
    sessao_padrao = chamadas[0].get("sessao")
    assert isinstance(sessao_padrao, requests.Session)
    assert sessao_padrao.verify == str(conexao.autoridades())

    # Case 2: with explicit sessao
    objeto_sessao = requests.Session()
    censo_superior.baixar(tmp_path, sessao=objeto_sessao)
    assert len(chamadas) == 2
    sessao_custom = chamadas[1].get("sessao")
    assert sessao_custom is objeto_sessao

