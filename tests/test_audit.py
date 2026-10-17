import polars as pl
from brmunipanel.metadata.audit import QualityAuditor

def test_audit_schema_types():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"municipality_code": [123]}) # It should be Utf8
    contract = {"test": {"cols": {"municipality_code": pl.Utf8}}}
    auditor.audit_schema(df, "test", contract)
    
    checks = auditor.get_checks_df()
    fail_check = checks.filter(pl.col("rule") == "types match the contract")[0]
    assert fail_check["status"][0] == "FAIL"

def test_audit_schema_order_and_orphans():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"a": [1], "b": [2]})
    contract = {"test": {"cols": {"a": pl.Int64}}} # b is orphan
    auditor.audit_schema(df, "test", contract)
    
    checks = auditor.get_checks_df()
    fail_check = checks.filter(pl.col("rule") == "schema and column order")[0]
    assert fail_check["status"][0] == "FAIL"
    assert auditor.has_critical_failure

def test_audit_periods_counts():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"municipality_code": ["1", "2"], "year": [2010, 2020]})
    contract = {"test": {"period": (2006, 2023), "rows": 3, "municipalities": 3}}
    auditor.audit_period_and_counts(df, "test", contract)
    
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "years expected vs observed")["status"][0] == "FAIL"
    assert checks.filter(pl.col("rule") == "row count")["status"][0] == "FAIL"
    assert checks.filter(pl.col("rule") == "distinct municipalities")["status"][0] == "FAIL"
    assert auditor.has_critical_failure

def test_audit_totals_education():
    auditor = QualityAuditor(None)
    # mock dataframe with exact totals
    df = pl.DataFrame({
        "year": [2006, 2023, 2023],
        "municipality_code": ["0", "0", "3550308"],
        "basic_edu_schools": [203973, 180230 - 7252, 7252],
        "enroll_early_childhood": [7016095, 9461155 - 666498, 666498],
        "enroll_elementary": [33282663, 26108208 - 1338720, 1338720],
        "enroll_secondary": [8906820, 7676743 - 447010, 447010],
        "teachers_basic_edu": [2647414, 2934558 - 155496, 155496],
        "higher_edu_institutions": [0, 3800 - 155, 155],
        "enroll_higher_edu": [0, 5063936 - 493613, 493613],
        "ideb_early_years_public": [None, 5.9, 5.9],
        "ideb_final_years_public": [None, 4.8, 4.8],
        "ideb_secondary_public": [None, 4.2, 4.2],
    })
    
    # Control totals suffice to check that rules are created
    auditor.audit_control_totals(df, "education")
    checks = auditor.get_checks_df()
    
    assert checks.filter(pl.col("rule") == "basic education 2006 schools")["status"][0] == "OK"
    assert checks.filter(pl.col("rule") == "SP 2023 basic schools")["status"][0] == "OK"
    # The IDEB count fails on purpose because the test table is small
    assert checks.filter(pl.col("rule") == "IDEB public early not null")["status"][0] == "FAIL"

def test_geographic_audit_limits_noronha():
    auditor = QualityAuditor(pl.DataFrame({"municipality_code": ["2605459"]}))
    auditor.valid_codes = {"2605459"}
    # Fernando de Noronha: lon = -32.41, lat = -3.84
    df = pl.DataFrame({
        "municipality_code": ["2605459"],
        "area_km2": [26.0],
        "latitude": [-3.84],
        "longitude": [-32.41]
    })
    auditor.audit_geographic_domains(df, "ibge_municipalities")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "geographic domains")["status"][0] == "OK"

def test_audit_length_limit():
    auditor = QualityAuditor(pl.DataFrame({"municipality_code": ["1", "2"]}))
    auditor.valid_codes = {"1", "2"}
    df_ok = pl.DataFrame({"municipality_code": ["1"], "neighbor_municipality_code": ["2"], "border_length_km": [0.0]})
    auditor.audit_geographic_domains(df_ok, "neighboring_municipalities")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "non-negative lengths")["status"][0] == "OK"

    df_fail = pl.DataFrame({"municipality_code": ["1"], "neighbor_municipality_code": ["2"], "border_length_km": [-1.0]})
    auditor = QualityAuditor(pl.DataFrame({"municipality_code": ["1", "2"]}))
    auditor.valid_codes = {"1", "2"}
    auditor.audit_geographic_domains(df_fail, "neighboring_municipalities")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "non-negative lengths")["status"][0] == "FAIL"

def test_audit_negative_values_skips_money_columns():
    auditor = QualityAuditor(None)
    df = pl.DataFrame({"exp_10_health": [-1.0], "rev_current_deductions": [-2.0], "rev_itbi": [-3.0]})
    auditor.audit_negative_values(df, "test")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "non-negative values")["status"][0] == "OK"

    auditor = QualityAuditor(None)
    auditor.audit_negative_values(pl.DataFrame({"enroll_elementary": [-1]}), "test")
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "non-negative values")["status"][0] == "FAIL"

def test_missing_file():
    auditor = QualityAuditor(None)
    contract = {"test": {}}
    auditor.audit_expected_files("intermediate", [], contract)
    checks = auditor.get_checks_df()
    assert checks.filter(pl.col("rule") == "file exists and opens")["status"][0] == "FAIL"
    assert auditor.has_critical_failure
