import polars as pl
from brmunipanel.metadata.auditoria import QualityAuditor

def test_auditoria_esquema_tipos():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"cod_municipio": [123]}) # It should be Utf8
    contrato = {"teste": {"cols": {"cod_municipio": pl.Utf8}}}
    auditor.auditar_esquema(df, "teste", contrato)
    
    checks = auditor.get_checks_df()
    fail_check = checks.filter(pl.col("regra") == "tipos correspondem ao contrato")[0]
    assert fail_check["status"][0] == "FALHA"

def test_auditoria_esquema_ordem_e_orfaos():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"a": [1], "b": [2]})
    contrato = {"teste": {"cols": {"a": pl.Int64}}} # b is orphan
    auditor.auditar_esquema(df, "teste", contrato)
    
    checks = auditor.get_checks_df()
    fail_check = checks.filter(pl.col("regra") == "esquema e ordem de colunas")[0]
    assert fail_check["status"][0] == "FALHA"
    assert auditor.has_critical_failure

def test_auditoria_periodos_contagens():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"cod_municipio": ["1", "2"], "ano": [2010, 2020]})
    contrato = {"teste": {"periodo": (2006, 2023), "linhas": 3, "municipios": 3}}
    auditor.auditar_periodo_e_contagens(df, "teste", contrato)
    
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("regra") == "anos esperado vs observado")["status"][0] == "FALHA"
    assert checks.filter(pl.col("regra") == "contagem de linhas")["status"][0] == "FALHA"
    assert checks.filter(pl.col("regra") == "municípios distintos")["status"][0] == "FALHA"
    assert auditor.has_critical_failure

def test_auditoria_totais_educacao():
    auditor = QualityAuditor(None)
    # mock dataframe with exact totals
    df = pl.DataFrame({
        "ano": [2006, 2023, 2023],
        "cod_municipio": ["0", "0", "3550308"],
        "instituicoes_basica": [203973, 180230 - 7252, 7252],
        "matriculas_infantil": [7016095, 9461155 - 666498, 666498],
        "matriculas_fundamental": [33282663, 26108208 - 1338720, 1338720],
        "matriculas_medio": [8906820, 7676743 - 447010, 447010],
        "docentes_basica": [2647414, 2934558 - 155496, 155496],
        "instituicoes_superior": [0, 3800 - 155, 155],
        "matriculas_superior": [0, 5063936 - 493613, 493613],
        "ideb_anos_iniciais_publica": [None, 5.9, 5.9],
        "ideb_anos_finais_publica": [None, 4.8, 4.8],
        "ideb_ensino_medio_publica": [None, 4.2, 4.2],
    })
    
    # Control totals suffice to check that rules are created
    auditor.auditar_totais_de_controle(df, "educacao")
    checks = auditor.get_checks_df()
    
    assert checks.filter(pl.col("regra") == "educacao basica 2006 institutos")["status"][0] == "OK"
    assert checks.filter(pl.col("regra") == "SP 2023 basica inst")["status"][0] == "OK"
    # The IDEB count fails on purpose because the test table is small
    assert checks.filter(pl.col("regra") == "IDEB pub ini nao nulo")["status"][0] == "FALHA"

def test_auditoria_geografica_limites_noronha():
    auditor = QualityAuditor(pl.DataFrame({"cod_municipio": ["2605459"]}))
    auditor.valid_cods = {"2605459"}
    # Fernando de Noronha: lon = -32.41, lat = -3.84
    df = pl.DataFrame({
        "cod_municipio": ["2605459"],
        "area_km2": [26.0],
        "latitude_sede": [-3.84],
        "longitude_sede": [-32.41]
    })
    auditor.auditar_dominios_geograficos(df, "ibge_municipios")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("regra") == "domínios geográficos")["status"][0] == "OK"

def test_auditoria_comprimento_limite():
    auditor = QualityAuditor(pl.DataFrame({"cod_municipio": ["1", "2"]}))
    auditor.valid_cods = {"1", "2"}
    df_ok = pl.DataFrame({"cod_municipio": ["1"], "cod_municipio_limitrofe": ["2"], "comprimento_km": [0.0]})
    auditor.auditar_dominios_geograficos(df_ok, "municipios_limitrofes")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("regra") == "comprimentos positivos")["status"][0] == "OK"

    df_fail = pl.DataFrame({"cod_municipio": ["1"], "cod_municipio_limitrofe": ["2"], "comprimento_km": [-1.0]})
    auditor = QualityAuditor(pl.DataFrame({"cod_municipio": ["1", "2"]}))
    auditor.valid_cods = {"1", "2"}
    auditor.auditar_dominios_geograficos(df_fail, "municipios_limitrofes")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("regra") == "comprimentos positivos")["status"][0] == "FALHA"

def test_arquivo_ausente():
    auditor = QualityAuditor(None)
    contrato = {"teste": {}}
    auditor.auditar_arquivos_esperados("intermediate", [], contrato)
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("regra") == "arquivo existe e abre")["status"][0] == "FALHA"
    assert auditor.has_critical_failure
