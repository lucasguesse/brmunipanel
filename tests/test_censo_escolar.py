import os
from pathlib import Path
import io
import hashlib
import json
import zipfile
import tempfile
import polars as pl
import pytest

from brmunipanel.inep import censo_escolar
from brmunipanel.nucleo import RespostaInvalida, baixar_lote as baixar_lote_do_nucleo

DADOS = Path(__file__).parent / "dados"

@pytest.fixture
def pasta_bruto_2007(tmp_path):
    arquivo = tmp_path / "censo-escolar" / "censo-escolar_2007.zip"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo, "w") as z:
        z.write(DADOS / "censo_escolar_2007_amostra.csv", "microdados_ed_basica_2007.csv")
    return tmp_path

@pytest.fixture
def pasta_bruto_2023(tmp_path):
    arquivo = tmp_path / "censo-escolar" / "censo-escolar_2023.zip"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo, "w") as z:
        z.write(DADOS / "censo_escolar_2023_amostra.csv", "MICRODADOS_ED_BASICA_2023.CSV")
    return tmp_path

@pytest.fixture
def municipios_mock():
    df = pl.read_csv(DADOS / "censo_escolar_2007_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    mun_2007 = df["CO_MUNICIPIO"].unique().to_list()
    df2 = pl.read_csv(DADOS / "censo_escolar_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    mun_2023 = df2["CO_MUNICIPIO"].unique().to_list()
    df3 = pl.read_csv(DADOS / "censo_escolar_2006_amostra.csv", separator="|", encoding="utf8-lossy", infer_schema_length=0)
    mun_2006 = [(m[:2] + m[-5:]) for m in df3["CODMUNIC"].unique().to_list()]
    muns = list(set(mun_2007 + mun_2023 + mun_2006))
    return pl.DataFrame({"cod_municipio": muns})

def test_censo_escolar_esquema(pasta_bruto_2007, municipios_mock, monkeypatch):
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2007])
    df = censo_escolar.harmonizar(pasta_bruto_2007, municipios_mock)
    
    assert df.shape[1] == 53
    col_order = ["cod_municipio", "ano", "dependencia", "localizacao", "escolas"]
    for _, dest in censo_escolar.COLUNAS_QUANTIDADE:
        col_order.append(dest)
        
    assert df.columns == col_order
    assert df.schema["cod_municipio"] == pl.String
    assert df.schema["ano"] == pl.Int16
    assert df.schema["dependencia"] == pl.String
    assert df.schema["localizacao"] == pl.String
    assert df.schema["escolas"] == pl.Int64
    for c in col_order[5:]:
        assert df.schema[c] == pl.Int64

def test_censo_escolar_contagem_escolas_atividade(pasta_bruto_2023, municipios_mock, monkeypatch):
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2023])
    df = censo_escolar.harmonizar(pasta_bruto_2023, municipios_mock)
    
    raw = pl.read_csv(DADOS / "censo_escolar_2023_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    ativas = raw.filter(pl.col("TP_SITUACAO_FUNCIONAMENTO") == "1").shape[0]
    assert df["escolas"].sum() == ativas

def test_censo_escolar_agregacao_e_vazios(pasta_bruto_2007, municipios_mock, monkeypatch):
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2007])
    df = censo_escolar.harmonizar(pasta_bruto_2007, municipios_mock)
    
    # Conferir caso em que apenas parte das escolas tem valor vazio (soma das demais)
    # Grupo ('1100114', '3', '2') (municipal, rural) tem 2 escolas, uma com vazio e outra com 1
    row_m_r = df.filter(
        (pl.col("cod_municipio") == "1100114") &
        (pl.col("dependencia") == "municipal") &
        (pl.col("localizacao") == "rural")
    )
    assert row_m_r["escolas"][0] == 2
    assert row_m_r["matriculas_basica"][0] == 32
    assert row_m_r["docentes_basica"][0] == 1
    assert row_m_r["turmas_basica"][0] == 3
    
    # Conferir caso em que todas as escolas do grupo têm valor vazio (fica com nulo)
    # Grupo ('1100205', '4', '1') (privada, urbana) tem 1 escola com valor vazio
    row_p_u = df.filter(
        (pl.col("cod_municipio") == "1100205") &
        (pl.col("dependencia") == "privada") &
        (pl.col("localizacao") == "urbana")
    )
    assert row_p_u["escolas"][0] == 1
    assert row_p_u["matriculas_basica"][0] == 8
    assert row_p_u["docentes_basica"][0] is None
    assert row_p_u["turmas_basica"][0] == 1

def test_censo_escolar_ordenacao_e_chave_unica(pasta_bruto_2007, pasta_bruto_2023, tmp_path, municipios_mock, monkeypatch):
    arquivo23 = tmp_path / "censo-escolar" / "censo-escolar_2023.zip"
    arquivo23.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo23, "w") as z:
        z.write(DADOS / "censo_escolar_2023_amostra.csv", "MICRODADOS_ED_BASICA_2023.CSV")
        
    arquivo07 = tmp_path / "censo-escolar" / "censo-escolar_2007.zip"
    with zipfile.ZipFile(arquivo07, "w") as z:
        z.write(DADOS / "censo_escolar_2007_amostra.csv", "microdados_ed_basica_2007.csv")

    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2007, 2023])
    df = censo_escolar.harmonizar(tmp_path, municipios_mock)
    
    assert df.shape[0] == df.select(["cod_municipio", "ano", "dependencia", "localizacao"]).unique().shape[0]
    
    df_sorted = df.sort(["cod_municipio", "ano", "dependencia", "localizacao"])
    assert df.equals(df_sorted)

def test_censo_escolar_erros(pasta_bruto_2007, municipios_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2007])
    
    # Mun fora
    arquivo = tmp_path / "censo-escolar" / "censo-escolar_2007.zip"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    
    raw = pl.read_csv(DADOS / "censo_escolar_2007_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("9999999").alias("CO_MUNICIPIO"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "microdados_ed_basica.csv"
        raw.write_csv(tmpcsv, separator=";")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.write(tmpcsv, "microdados_ed_basica.csv")
    
    with pytest.raises(ValueError, match="Municípios inválidos"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)
        
    # Dep fora
    raw = pl.read_csv(DADOS / "censo_escolar_2007_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("9").alias("TP_DEPENDENCIA"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "microdados_ed_basica.csv"
        raw.write_csv(tmpcsv, separator=";")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.write(tmpcsv, "microdados_ed_basica.csv")
            
    with pytest.raises(ValueError, match="Valores inválidos em TP_DEPENDENCIA"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)

    # Int negativo
    raw = pl.read_csv(DADOS / "censo_escolar_2007_amostra.csv", separator=";", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("-1").alias("QT_MAT_BAS"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "microdados_ed_basica.csv"
        raw.write_csv(tmpcsv, separator=";")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.write(tmpcsv, "microdados_ed_basica.csv")
            
    with pytest.raises(ValueError, match="Valores não inteiros ou negativos na coluna QT_MAT_BAS"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)

    # pacote sem csv
    with zipfile.ZipFile(arquivo, "w") as z:
        z.write(DADOS / "censo_escolar_2007_amostra.csv", "outro.csv")
        
    with pytest.raises(ValueError, match="esperado exatamente 1 arquivo CSV"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)

def test_censo_escolar_baixar_mock(monkeypatch):
    chamadas = []
    def mock_baixar_lote(reqs, pasta, validar, intervalo, **opcoes):
        chamadas.extend(reqs)
        try:
            validar(b"PK\x03\x04...")
        except Exception:
            pytest.fail("Validação do zip falhou para conteudo valido")
        with pytest.raises(RespostaInvalida):
            validar(b"<html>...</html>")

    monkeypatch.setattr(censo_escolar, "baixar_lote", mock_baixar_lote)
    censo_escolar.baixar("dummy")
    assert len(chamadas) == 18
    anos = list(range(2006, 2024))
    for req, ano in zip(chamadas, anos):
        assert req.chave == f"censo-escolar/{ano}"
        assert req.arquivo == f"censo-escolar/censo-escolar_{ano}.zip"
        assert req.url == f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip"
        assert req.compactar is False

    # caso em que o manifesto já tem a chave e o arquivo existe
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2023])
    
    class SessaoFalha:
        def get(self, *args, **kwargs):
            raise RuntimeError("Não deveria chamar a rede")
        def post(self, *args, **kwargs):
            raise RuntimeError("Não deveria chamar a rede")
            
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pasta_inep = td / "censo-escolar"
        pasta_inep.mkdir(parents=True, exist_ok=True)
        
        manifesto = {}
        for ano in range(2006, 2024):
            arquivo = pasta_inep / f"censo-escolar_{ano}.zip"
            arquivo.write_bytes(b"PK\x03\x04" + b"X" * 10)
            manifesto[f"censo-escolar/{ano}"] = {
                "arquivo": f"censo-escolar_{ano}.zip",
                "url": f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip",
                "bytes": arquivo.stat().st_size,
                "sha256": hashlib.sha256(arquivo.read_bytes()).hexdigest()
            }
        with open(td / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifesto, f)
            
        monkeypatch.setattr(censo_escolar, "baixar_lote", baixar_lote_do_nucleo)
        
        censo_escolar.baixar(td, sessao=SessaoFalha())

@pytest.fixture
def pasta_bruto_2006(tmp_path):
    pasta_inep = tmp_path / "censo-escolar"
    pasta_inep.mkdir(parents=True, exist_ok=True)
    arquivo = pasta_inep / "censo-escolar_2006.zip"
    with zipfile.ZipFile(arquivo, "w") as z:
        z.write(os.path.join(os.path.dirname(__file__), "dados", "censo_escolar_2006_amostra.csv"), "CENSOESC_2006.CSV")
        z.write(os.path.join(os.path.dirname(__file__), "dados", "censo_escolar_2006_educprof_amostra.csv"), "EDUCPROF_2006.CSV")
        
    return tmp_path

def test_censo_escolar_2006_casos(pasta_bruto_2006, municipios_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2006])
    df = censo_escolar.harmonizar(pasta_bruto_2006, municipios_mock)
    
    # Caso 1: A saída de 2006 tem as 53 colunas, na ordem e com os tipos da tabela
    assert df.shape[1] == 53
    col_order = ["cod_municipio", "ano", "dependencia", "localizacao", "escolas"]
    for _, dest in censo_escolar.COLUNAS_QUANTIDADE:
        col_order.append(dest)
        
    assert df.columns == col_order
    assert df.schema["cod_municipio"] == pl.String
    assert df.schema["ano"] == pl.Int16
    assert df.schema["dependencia"] == pl.String
    assert df.schema["localizacao"] == pl.String
    assert df.schema["escolas"] == pl.Int64
    for c in col_order[5:]:
        assert df.schema[c] == pl.Int64
        
    # Caso 3: As catorze colunas sem informação são nulas em todas as linhas de 2006
    catorze = [
        "matriculas_basica", "turmas_basica", "docentes_infantil", "docentes_fund_anos_iniciais",
        "docentes_fund_anos_finais", "docentes_eja_fundamental", "docentes_eja_medio",
        "docentes_especial_inclusiva", "docentes_especial_exclusiva", "turmas_profissional",
        "turmas_prof_tecnica", "turmas_especial", "turmas_especial_inclusiva", "turmas_especial_exclusiva"
    ]
    for c in catorze:
        assert df.select(pl.col(c).is_null().all())[c][0] is True
        
    outras = [c for c in col_order if c not in catorze]
    for c in outras:
        assert df.select(pl.col(c).is_null().any())[c][0] is False
        
    # Caso 2: Os valores de um grupo (ex: cod_municipio, dependência e localização), calculados à mão a partir da amostra
    row = df.filter((pl.col("dependencia") == "federal") & (pl.col("cod_municipio") == "1100023")).to_dicts()[0]
    assert row["escolas"] == 1
    assert row["matriculas_fundamental"] == 0
    assert row["matriculas_medio"] == 0
    assert row["matriculas_profissional"] == 204
    assert row["docentes_basica"] == 16
    assert row["turmas_fundamental"] == 0
    
    # Municipal e rural de 1100205, com escolas igual a 1 (escola extinta não conta)
    row_mun_rural = df.filter((pl.col("dependencia") == "municipal") & (pl.col("cod_municipio") == "1100205") & (pl.col("localizacao") == "rural")).to_dicts()[0]
    assert row_mun_rural["escolas"] == 1
    # Conferir creche e fundamental 9 anos
    assert row_mun_rural["matriculas_fund_anos_iniciais"] == 28 # Tem DE9F11C a DE9F11G = 28 na escola 54264611
    
    # Escola paralisada não conta no grupo privada e urbana de 1100205
    row_priv_urb = df.filter((pl.col("dependencia") == "privada") & (pl.col("cod_municipio") == "1100205") & (pl.col("localizacao") == "urbana")).to_dicts()[0]
    assert row_priv_urb["escolas"] == 2 # 54261222 e 54262913 (54261227 paralisada não conta)
    assert row_priv_urb["matriculas_creche"] == 18 # Tem DPE119 = 18 na 54262913
    
    # Caso 4: O vazio vale zero: um grupo sem EJA tem matriculas_eja igual a zero, e não nulo
    row = df.filter((pl.col("dependencia") == "federal") & (pl.col("cod_municipio") == "1100023")).to_dicts()[0]
    assert row["matriculas_eja"] == 0
    
    # Caso 5: O curso normal não é somado ao ensino médio
    # ('1100205', 'estadual', 'urbana') tem a escola com curso normal (DCN)
    row = df.filter((pl.col("cod_municipio") == "1100205") & (pl.col("dependencia") == "estadual") & (pl.col("localizacao") == "urbana")).to_dicts()[0]
    assert row["matriculas_medio"] == 147
    
    # Caso 6: A EJA soma presencial e semipresencial, e turmas EJA contam presencial
    # ('1100338', 'estadual', 'urbana') tem EJA semipresencial (VES12A3)
    row = df.filter((pl.col("cod_municipio") == "1100338") & (pl.col("dependencia") == "estadual") & (pl.col("localizacao") == "urbana")).to_dicts()[0]
    assert row["matriculas_eja"] == 712
    assert row["turmas_eja"] == 8
    
    # Caso 7: A educação especial segue os prefixos
    # inclusiva: '1100205', privada, urbana
    row = df.filter((pl.col("cod_municipio") == "1100205") & (pl.col("dependencia") == "privada") & (pl.col("localizacao") == "urbana")).to_dicts()[0]
    assert row["matriculas_especial_inclusiva"] == 6
    assert row["matriculas_especial_exclusiva"] == 0
    # exclusiva: '1100205', estadual, urbana
    row = df.filter((pl.col("cod_municipio") == "1100205") & (pl.col("dependencia") == "estadual") & (pl.col("localizacao") == "urbana")).to_dicts()[0]
    assert row["matriculas_especial_inclusiva"] == 0
    assert row["matriculas_especial_exclusiva"] == 190
    
    # Caso 8: A educação profissional vem do arquivo de cursos, e o curso inativo não conta
    row = df.filter((pl.col("dependencia") == "privada") & (pl.col("localizacao") == "urbana") & (pl.col("cod_municipio") == "1100023")).to_dicts()[0]
    assert row["matriculas_profissional"] == 43
    
    # No caso 8, o curso fora de atividade é montado no teste
    arquivo_tmp = tmp_path / "censo-escolar_inativo" / "censo-escolar" / "censo-escolar_2006.zip"
    arquivo_tmp.parent.mkdir(parents=True, exist_ok=True)
    # Substituímos Ativo por Inativo no CSV EDUCPROF
    educ_csv = (DADOS / "censo_escolar_2006_educprof_amostra.csv").read_text(encoding="utf8")
    educ_csv = educ_csv.replace("|Ativo|", "|Inativo|")
    with zipfile.ZipFile(arquivo_tmp, "w") as z:
        z.write(DADOS / "censo_escolar_2006_amostra.csv", "CENSOESC_2006.CSV")
        z.writestr("EDUCPROF_2006.CSV", educ_csv)
    df_inativo = censo_escolar.harmonizar(tmp_path / "censo-escolar_inativo", municipios_mock)
    row_inativo = df_inativo.filter((pl.col("dependencia") == "privada") & (pl.col("localizacao") == "urbana") & (pl.col("cod_municipio") == "1100023")).to_dicts()[0]
    assert row_inativo["matriculas_profissional"] == 0

def test_censo_escolar_2006_erros(pasta_bruto_2006, municipios_mock, monkeypatch, tmp_path):
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2006])
    arquivo = tmp_path / "censo-escolar" / "censo-escolar_2006.zip"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    
    orig_path = pasta_bruto_2006 / "censo-escolar" / "censo-escolar_2006.zip"
    with zipfile.ZipFile(orig_path, 'r') as z:
        censo_csv = z.read("CENSOESC_2006.CSV")
        educ_csv = z.read("EDUCPROF_2006.CSV")
    
    # Erro 1: DEP fora da lista
    raw = pl.read_csv(io.BytesIO(censo_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("Fora").alias("DEP"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "CENSOESC_2006.CSV"
        raw.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.write(tmpcsv, "CENSOESC_2006.CSV")
            z.writestr("EDUCPROF_2006.CSV", educ_csv)
    with pytest.raises(ValueError, match="Valores inv.*lidos em DEP"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)
        
    # Erro 2: Município fora da tabela
    raw = pl.read_csv(io.BytesIO(censo_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("999999999999").alias("CODMUNIC"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "CENSOESC_2006.CSV"
        raw.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.write(tmpcsv, "CENSOESC_2006.CSV")
            z.writestr("EDUCPROF_2006.CSV", educ_csv)
    with pytest.raises(ValueError, match="Munic.*pios inv.*lidos ou nulos em CODMUNIC"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)
        
    # Erro 3: Valor não inteiro
    raw = pl.read_csv(io.BytesIO(censo_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw = raw.with_columns(pl.lit("-1").alias("DPE119"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "CENSOESC_2006.CSV"
        raw.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.write(tmpcsv, "CENSOESC_2006.CSV")
            z.writestr("EDUCPROF_2006.CSV", educ_csv)
    with pytest.raises(ValueError, match="Valores n.*o inteiros ou negativos na coluna DPE119"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)
        
    # Erro 4: curso técnico em atividade de escola não em atividade
    raw_educ = pl.read_csv(io.BytesIO(educ_csv), separator="|", encoding="utf8-lossy", infer_schema_length=0)
    raw_educ = raw_educ.with_columns(pl.lit("99999999").alias("MASCARA"))
    with tempfile.TemporaryDirectory() as td:
        tmpcsv = Path(td) / "EDUCPROF_2006.CSV"
        raw_educ.write_csv(tmpcsv, separator="|")
        with zipfile.ZipFile(arquivo, "w") as z:
            z.writestr("CENSOESC_2006.CSV", censo_csv)
            z.write(tmpcsv, "EDUCPROF_2006.CSV")
    with pytest.raises(ValueError, match="Curso t.*cnico ativo de escola inativa ou n.*o encontrada"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)
        
    # Erro 5: Pacote sem um dos dois CSV
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr("CENSOESC_2006.CSV", censo_csv)
    with pytest.raises(ValueError, match="faltando CENSOESC_2006.CSV ou EDUCPROF_2006.CSV no ZIP"):
        censo_escolar.harmonizar(tmp_path, municipios_mock)

def test_censo_escolar_2006_e_2007(pasta_bruto_2007, tmp_path, municipios_mock, monkeypatch):
    arquivo07 = tmp_path / "censo-escolar" / "censo-escolar_2007.zip"
    arquivo07.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo07, "w") as z:
        z.write(DADOS / "censo_escolar_2007_amostra.csv", "microdados_ed_basica_2007.csv")
        
    arquivo06 = tmp_path / "censo-escolar" / "censo-escolar_2006.zip"
    with zipfile.ZipFile(arquivo06, "w") as z:
        z.write(DADOS / "censo_escolar_2006_amostra.csv", "CENSOESC_2006.CSV")
        z.write(DADOS / "censo_escolar_2006_educprof_amostra.csv", "EDUCPROF_2006.CSV")

    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2006, 2007])
    df = censo_escolar.harmonizar(tmp_path, municipios_mock)
    
    assert df.shape[0] == df.select(["cod_municipio", "ano", "dependencia", "localizacao"]).unique().shape[0]
    
    df_sorted = df.sort(["cod_municipio", "ano", "dependencia", "localizacao"])
    assert df.equals(df_sorted)
    
    # As linhas de 2007 saem iguais
    monkeypatch.setattr(censo_escolar, "ANOS_TODOS", [2007])
    df_2007_only = censo_escolar.harmonizar(pasta_bruto_2007, municipios_mock)
    df_filtered = df.filter(pl.col("ano") == 2007)
    
    assert df_filtered.equals(df_2007_only)
