"""Tests for network-disaggregated quality audit checks and control totals."""

import polars as pl
from brmunipanel.metadata.audit import QualityAuditor


def test_control_totals_pass_rates():
    auditor = QualityAuditor(None)
    data = {
        "municipality_code": ["3550308", "1100015"],
        "year": pl.Series([2023, 2023], dtype=pl.Int16),
        "location": ["total", "total"],
        "network": ["total", "state"],
        "pass_rate_final_years": [97.5, 80.0],
        "failure_rate_final_years": [1.6, 10.0],
        "dropout_rate_final_years": [0.9, 5.0],
        "pass_rate_secondary": [91.0, None],
        "failure_rate_secondary": [5.6, None],
        "dropout_rate_secondary": [3.4, None],
    }
    df = pl.DataFrame(data)
    auditor.audit_control_totals(df, "[processed] pass_rates")
    checks = {c["rule"]: c for c in auditor.checks}
    assert checks["pass_rates final years rates add up to 100"]["status"] == "FAIL"
    assert checks["pass_rates final years rates add up to 100"]["observed"] == "1"
    assert checks["pass_rates secondary rates add up to 100"]["status"] == "OK"
    assert checks["pass_rates secondary rates add up to 100"]["observed"] == "0"
    assert checks["pass_rates rates within 0-100"]["status"] == "OK"
    assert checks["pass_rates SP 2023 pass rate final years"]["status"] == "OK"
    assert checks["pass_rates SP 2023 pass rate secondary"]["status"] == "OK"


def test_control_totals_ideb_network():
    auditor = QualityAuditor(None)
    data = {
        "municipality_code": ["3550308", "3550308", "3550308", "1100015"],
        "year": pl.Series([2023, 2023, 2023, 2023], dtype=pl.Int16),
        "network": ["state", "municipal", "public", "state"],
        "ideb_final_years": [4.9, 4.8, 4.8, 11.0],
    }
    df = pl.DataFrame(data)
    auditor.audit_control_totals(df, "[processed] ideb_final_years_network")
    checks = {c["rule"]: c for c in auditor.checks}
    assert checks["ideb_final_years_network values within 0-10"]["status"] == "FAIL"
    assert checks["ideb_final_years_network values within 0-10"]["observed"] == "1"
    assert checks["ideb_final_years_network not null"]["status"] == "FAIL"
    assert checks["ideb_final_years_network not null"]["observed"] == "4"
    assert checks["ideb_final_years_network SP 2023 state"]["status"] == "OK"


def test_education_by_network_consistent():
    auditor = QualityAuditor(None)
    education = pl.DataFrame({
        "municipality_code": ["1100015"],
        "year": pl.Series([2011], dtype=pl.Int16),
        "enroll_secondary": [30],
        "ideb_final_years_public": [4.5],
    })
    enrollment_network = pl.DataFrame({
        "municipality_code": ["1100015"] * 5,
        "year": pl.Series([2011] * 5, dtype=pl.Int16),
        "network": ["federal_network", "federal_other", "state", "municipal", "private"],
        "secondary_schools": [1, 0, 2, 0, 0],
        "enroll_secondary": [10, 0, 20, 0, 0],
        "enroll_elementary_final_years": [0, 0, 40, 15, 0],
        "enroll_vocational_technical": [5, 0, 0, 0, 0],
    })
    federal_schools = pl.DataFrame({
        "school_code": ["1"],
        "year": pl.Series([2011], dtype=pl.Int16),
        "municipality_code": ["1100015"],
        "school_name": ["IFRO - CAMPUS X"],
        "school_class": ["federal_network"],
        "operating_status": ["active"],
        "enroll_basic_edu": [10],
        "enroll_secondary": [10],
        "enroll_vocational": [5],
        "enroll_vocational_technical": [5],
        "enroll_eja_secondary": [0],
    })
    ideb_network = pl.DataFrame({
        "municipality_code": ["1100015", "1100015"],
        "year": pl.Series([2011, 2011], dtype=pl.Int16),
        "network": ["public", "state"],
        "ideb_final_years": [4.5, 4.0],
    })
    auditor.audit_education_by_network(education, enrollment_network, federal_schools, ideb_network)
    checks = {c["rule"]: c for c in auditor.checks}
    assert checks["secondary enrolment by network equals education"]["status"] == "OK"
    assert checks["secondary enrolment by network equals education"]["observed"] == "0"
    assert checks["federal enrolment equals federal_schools"]["status"] == "OK"
    assert checks["federal enrolment equals federal_schools"]["observed"] == "0"
    assert checks["IDEB public by network equals education"]["status"] == "OK"
    assert checks["IDEB public by network equals education"]["observed"] == "0"
    assert auditor.has_critical_failure is False


def test_education_by_network_mismatch():
    auditor = QualityAuditor(None)
    education = pl.DataFrame({
        "municipality_code": ["1100015"],
        "year": pl.Series([2011], dtype=pl.Int16),
        "enroll_secondary": [30],
        "ideb_final_years_public": [4.5],
    })
    enrollment_network = pl.DataFrame({
        "municipality_code": ["1100015"] * 5,
        "year": pl.Series([2011] * 5, dtype=pl.Int16),
        "network": ["federal_network", "federal_other", "state", "municipal", "private"],
        "secondary_schools": [1, 0, 2, 0, 0],
        "enroll_secondary": [10, 0, 25, 0, 0],
        "enroll_elementary_final_years": [0, 0, 40, 15, 0],
        "enroll_vocational_technical": [5, 0, 0, 0, 0],
    })
    federal_schools = pl.DataFrame({
        "school_code": ["1"],
        "year": pl.Series([2011], dtype=pl.Int16),
        "municipality_code": ["1100015"],
        "school_name": ["IFRO - CAMPUS X"],
        "school_class": ["federal_network"],
        "operating_status": ["active"],
        "enroll_basic_edu": [10],
        "enroll_secondary": [10],
        "enroll_vocational": [5],
        "enroll_vocational_technical": [5],
        "enroll_eja_secondary": [0],
    })
    ideb_network = pl.DataFrame({
        "municipality_code": ["1100015", "1100015"],
        "year": pl.Series([2011, 2011], dtype=pl.Int16),
        "network": ["public", "state"],
        "ideb_final_years": [4.6, 4.0],
    })
    auditor.audit_education_by_network(education, enrollment_network, federal_schools, ideb_network)
    checks = {c["rule"]: c for c in auditor.checks}
    assert checks["secondary enrolment by network equals education"]["status"] == "FAIL"
    assert checks["secondary enrolment by network equals education"]["observed"] == "1"
    assert checks["IDEB public by network equals education"]["status"] == "FAIL"
    assert checks["IDEB public by network equals education"]["observed"] == "1"
    assert checks["federal enrolment equals federal_schools"]["status"] == "OK"
    assert auditor.has_critical_failure is True


def test_control_totals_municipalities_2011():
    auditor = QualityAuditor(None)
    data = {
        "municipality_code": ["3550308", "3509502", "5101837"],
        "mesoregion_2011_code": ["3515", "3507", None],
        "mesoregion_2011_name": ["Metropolitana de São Paulo", "Campinas", None],
        "microregion_2011_code": ["35061", "35032", None],
        "microregion_2011_name": ["São Paulo", "Campinas", None],
    }
    df = pl.DataFrame(data)
    auditor.audit_control_totals(df, "[processed] municipalities")
    checks = {c["rule"]: c for c in auditor.checks}
    assert checks["municipalities 2011 mesoregions"]["status"] == "FAIL"
    assert checks["municipalities 2011 mesoregions"]["observed"] == "2"
    assert checks["municipalities 2011 microregions"]["status"] == "FAIL"
    assert checks["municipalities 2011 microregions"]["observed"] == "2"
    assert checks["municipalities without 2011 regions"]["status"] == "FAIL"
    assert checks["municipalities without 2011 regions"]["observed"] == "1"
