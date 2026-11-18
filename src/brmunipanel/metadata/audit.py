import polars as pl
from typing import List

def audit_summary_table(df: pl.DataFrame, table_name: str, key_cols: List[str]) -> dict:
    """Computes summary audit metrics for `df`, returning a dictionary of statistics."""
    rows = df.height
    columns = df.width
    key = ", ".join(key_cols)
    
    key_duplicates = 0
    if rows > 0 and key_cols and all(c in df.columns for c in key_cols):
        key_duplicates = df.group_by(key_cols).len().filter(pl.col("len") > 1).height

    year_min = ""
    year_max = ""
    if "year" in df.columns and rows > 0 and df["year"].null_count() < rows:
        year_min = str(df["year"].min())
        year_max = str(df["year"].max())
        
    distinct_municipalities = 0
    if "municipality_code" in df.columns and rows > 0:
        distinct_municipalities = df["municipality_code"].n_unique()
        
    null_cells = sum(df[c].null_count() for c in df.columns)
    total_cells = rows * columns
    percentage_null_cells = round((null_cells / total_cells) * 100, 2) if total_cells > 0 else 0.0
    
    return {
        "file": table_name + ".parquet",
        "rows": rows,
        "columns": columns,
        "key": key,
        "key_duplicates": key_duplicates,
        "min_year": year_min,
        "max_year": year_max,
        "distinct_municipalities": distinct_municipalities,
        "null_cells": null_cells,
        "null_cells_percentage": percentage_null_cells
    }

class QualityAuditor:
    """Executes and records data quality validation checks across pipeline tables."""
    def __init__(self, municipalities_df: pl.DataFrame):
        self.municipalities_df = municipalities_df
        self.valid_codes = set()
        if municipalities_df is not None and "municipality_code" in municipalities_df.columns:
            self.valid_codes = set(municipalities_df["municipality_code"].drop_nulls().to_list())
        self.checks = []
        self.has_critical_failure = False
        
    def add_check(self, table: str, rule: str, status: str, observed: str, expected: str, detail: str = ""):
        """Records an audit check result, setting `has_critical_failure` if a critical check fails."""
        self.checks.append({
            "table": table,
            "rule": rule,
            "status": status,
            "observed": observed,
            "expected": expected,
            "detail": detail
        })
        if status == "FAIL" and "critical" in detail.lower():
            self.has_critical_failure = True

    def audit_expected_files(self, stage: str, found_files: List[str], contract: dict):
        """Validates that all expected files defined in `contract` exist in `found_files`."""
        expected = list(contract.keys())
        for f in expected:
            if f not in found_files:
                self.add_check(f"[{stage}] {f}", "file exists and opens", "FAIL", "Missing", "Present", "Critical: file missing from the project")

    def audit_schema(self, df: pl.DataFrame, table: str, contract: dict):
        """Audits column names, column order, and data types of `df` against `contract`."""
        clean_name = table.replace("[processed] ", "").replace("[intermediate] ", "")
        if clean_name not in contract:
            self.add_check(table, "schema and column order", "FAIL", "Missing contract", "Expected contract", "Critical: table without a contract")
            return
            
        expected_cols = list(contract[clean_name]["cols"].keys())
        expected_dtypes = contract[clean_name]["cols"]
        
        actual_cols = df.columns
        if actual_cols == expected_cols:
            self.add_check(table, "schema and column order", "OK", "Correct", "Correct")
        else:
            self.add_check(table, "schema and column order", "FAIL", str(actual_cols), str(expected_cols), "Critical: does not match the contract")
            
        types_ok = True
        observed = []
        for c in actual_cols:
            if c in expected_dtypes:
                dtype = df[c].dtype
                if dtype != expected_dtypes[c]:
                    types_ok = False
                    observed.append(f"{c}: {dtype}")
        if types_ok:
            self.add_check(table, "types match the contract", "OK", "Correct", "Correct")
        else:
            self.add_check(table, "types match the contract", "FAIL", str(observed), "Correct", "Critical: incompatible types")

    def audit_period_and_counts(self, df: pl.DataFrame, table: str, contract: dict):
        """Audits covered period, row count, and distinct municipalities in `df` against `contract`."""
        clean_name = table.replace("[processed] ", "").replace("[intermediate] ", "")
        if clean_name not in contract:
            return
            
        c = contract[clean_name]
        
        if c["period"]:
            min_year, max_year = c["period"]
            df_min = df["year"].min() if "year" in df.columns else None
            df_max = df["year"].max() if "year" in df.columns else None
            if df_min == min_year and df_max == max_year:
                self.add_check(table, "years expected vs observed", "OK", f"{df_min}-{df_max}", f"{min_year}-{max_year}")
            else:
                self.add_check(table, "years expected vs observed", "FAIL", f"{df_min}-{df_max}", f"{min_year}-{max_year}", "Critical: invalid period")
                
        if c.get("rows"):
            rows = df.height
            if rows == c["rows"]:
                self.add_check(table, "row count", "OK", str(rows), str(c["rows"]))
            else:
                self.add_check(table, "row count", "FAIL", str(rows), str(c["rows"]), "Critical: row count differs")
                
        if c.get("municipalities") and "municipality_code" in df.columns:
            munis = df["municipality_code"].n_unique()
            if munis == c["municipalities"]:
                self.add_check(table, "distinct municipalities", "OK", str(munis), str(c["municipalities"]))
            else:
                self.add_check(table, "distinct municipalities", "FAIL", str(munis), str(c["municipalities"]), "Critical: municipalities differ")

    def audit_control_totals(self, df: pl.DataFrame, table: str):
        """Validates national and state benchmark control totals for table columns."""
        clean_name = table.replace("[processed] ", "").replace("[intermediate] ", "")
        
        if clean_name == "education":
            # National control totals for basic and higher education, in 2006 and in 2023
            df_2006 = df.filter(pl.col("year") == 2006)
            df_2023 = df.filter(pl.col("year") == 2023)
            df_sp_2023 = df_2023.filter(pl.col("municipality_code") == "3550308")
            
            # 2006 totals
            basic_inst_2006 = df_2006["basic_edu_schools"].sum()
            mat_inf_2006 = df_2006["enroll_early_childhood"].sum()
            mat_fund_2006 = df_2006["enroll_elementary"].sum()
            mat_med_2006 = df_2006["enroll_secondary"].sum()
            teachers_2006 = df_2006["teachers_basic_edu"].sum()
            
            self.add_check(table, "basic education 2006 schools", "OK" if basic_inst_2006 == 203973 else "FAIL", str(basic_inst_2006), "203973")
            self.add_check(table, "basic education 2006 early childhood", "OK" if mat_inf_2006 == 7016095 else "FAIL", str(mat_inf_2006), "7016095")
            self.add_check(table, "basic education 2006 elementary", "OK" if mat_fund_2006 == 33282663 else "FAIL", str(mat_fund_2006), "33282663")
            self.add_check(table, "basic education 2006 secondary", "OK" if mat_med_2006 == 8906820 else "FAIL", str(mat_med_2006), "8906820")
            self.add_check(table, "basic education 2006 teachers", "OK" if teachers_2006 == 2647414 else "FAIL", str(teachers_2006), "2647414")
            
            # 2023 totals
            basic_inst_2023 = df_2023["basic_edu_schools"].sum()
            mat_inf_2023 = df_2023["enroll_early_childhood"].sum()
            mat_fund_2023 = df_2023["enroll_elementary"].sum()
            mat_med_2023 = df_2023["enroll_secondary"].sum()
            teachers_2023 = df_2023["teachers_basic_edu"].sum()
            inst_sup_2023 = df_2023["higher_edu_institutions"].sum()
            mat_sup_2023 = df_2023["enroll_higher_edu"].sum()
            
            self.add_check(table, "basic education 2023 schools", "OK" if basic_inst_2023 == 180230 else "FAIL", str(basic_inst_2023), "180230")
            self.add_check(table, "basic education 2023 early childhood", "OK" if mat_inf_2023 == 9461155 else "FAIL", str(mat_inf_2023), "9461155")
            self.add_check(table, "basic education 2023 elementary", "OK" if mat_fund_2023 == 26108208 else "FAIL", str(mat_fund_2023), "26108208")
            self.add_check(table, "basic education 2023 secondary", "OK" if mat_med_2023 == 7676743 else "FAIL", str(mat_med_2023), "7676743")
            self.add_check(table, "basic education 2023 teachers", "OK" if teachers_2023 == 2934558 else "FAIL", str(teachers_2023), "2934558")
            self.add_check(table, "higher education 2023 institutions", "OK" if inst_sup_2023 == 3800 else "FAIL", str(inst_sup_2023), "3800")
            self.add_check(table, "higher education 2023 enrollments", "OK" if mat_sup_2023 == 5063936 else "FAIL", str(mat_sup_2023), "5063936")
            
            # SP 2023 totals
            if df_sp_2023.height > 0:
                self.add_check(table, "SP 2023 basic schools", "OK" if df_sp_2023["basic_edu_schools"][0] == 7252 else "FAIL", str(df_sp_2023["basic_edu_schools"][0]), "7252")
                self.add_check(table, "SP 2023 basic early childhood", "OK" if df_sp_2023["enroll_early_childhood"][0] == 666498 else "FAIL", str(df_sp_2023["enroll_early_childhood"][0]), "666498")
                self.add_check(table, "SP 2023 basic elementary", "OK" if df_sp_2023["enroll_elementary"][0] == 1338720 else "FAIL", str(df_sp_2023["enroll_elementary"][0]), "1338720")
                self.add_check(table, "SP 2023 basic secondary", "OK" if df_sp_2023["enroll_secondary"][0] == 447010 else "FAIL", str(df_sp_2023["enroll_secondary"][0]), "447010")
                self.add_check(table, "SP 2023 basic teachers", "OK" if df_sp_2023["teachers_basic_edu"][0] == 155496 else "FAIL", str(df_sp_2023["teachers_basic_edu"][0]), "155496")
                self.add_check(table, "SP 2023 sup inst", "OK" if df_sp_2023["higher_edu_institutions"][0] == 155 else "FAIL", str(df_sp_2023["higher_edu_institutions"][0]), "155")
                self.add_check(table, "SP 2023 sup mat", "OK" if df_sp_2023["enroll_higher_edu"][0] == 493613 else "FAIL", str(df_sp_2023["enroll_higher_edu"][0]), "493613")
                self.add_check(table, "SP 2023 ideb public early", "OK" if abs(df_sp_2023["ideb_early_years_public"][0] - 5.9) < 0.01 else "FAIL", str(df_sp_2023["ideb_early_years_public"][0]), "5.9")
                self.add_check(table, "SP 2023 ideb public final", "OK" if abs(df_sp_2023["ideb_final_years_public"][0] - 4.8) < 0.01 else "FAIL", str(df_sp_2023["ideb_final_years_public"][0]), "4.8")
                self.add_check(table, "SP 2023 ideb public secondary", "OK" if abs(df_sp_2023["ideb_secondary_public"][0] - 4.2) < 0.01 else "FAIL", str(df_sp_2023["ideb_secondary_public"][0]), "4.2")

            # Count of non-null IDEB values in each stage, from 2006 to 2023
            nn_ini = df.filter((pl.col("year") >= 2006) & (pl.col("year") <= 2023))["ideb_early_years_public"].drop_nulls().len()
            nn_fin = df.filter((pl.col("year") >= 2006) & (pl.col("year") <= 2023))["ideb_final_years_public"].drop_nulls().len()
            nn_med = df.filter((pl.col("year") >= 2006) & (pl.col("year") <= 2023))["ideb_secondary_public"].drop_nulls().len()
            self.add_check(table, "IDEB public early not null", "OK" if nn_ini == 48097 else "FAIL", str(nn_ini), "48097")
            self.add_check(table, "IDEB public final not null", "OK" if nn_fin == 47897 else "FAIL", str(nn_fin), "47897")
            self.add_check(table, "IDEB public secondary not null", "OK" if nn_med == 18493 else "FAIL", str(nn_med), "18493")

        elif clean_name == "enrollment_network":
            df_2023 = df.filter(pl.col("year") == 2023)
            for net, expected in [
                ("federal_network", 220760),
                ("federal_other", 15387),
                ("state", 6415026),
                ("municipal", 39223),
                ("private", 986347),
            ]:
                obs = int(df_2023.filter(pl.col("network") == net)["enroll_secondary"].sum() or 0)
                self.add_check(
                    table,
                    f"enrollment_network 2023 secondary {net}",
                    "OK" if obs == expected else "FAIL",
                    str(obs),
                    str(expected),
                )

        elif clean_name == "federal_schools":
            df_2023_active_fed = df.filter(
                (pl.col("year") == 2023)
                & (pl.col("operating_status") == "active")
                & (pl.col("school_class") == "federal_network")
            )
            obs = df_2023_active_fed.height
            self.add_check(
                table,
                "federal_schools 2023 active federal_network schools",
                "OK" if obs == 627 else "FAIL",
                str(obs),
                "627",
            )

        elif clean_name == "pass_rates":
            df_fy = df.filter(
                pl.col("pass_rate_final_years").is_not_null()
                & pl.col("failure_rate_final_years").is_not_null()
                & pl.col("dropout_rate_final_years").is_not_null()
            )
            sum_fy = (
                pl.col("pass_rate_final_years")
                + pl.col("failure_rate_final_years")
                + pl.col("dropout_rate_final_years")
            )
            diff_fy = df_fy.filter((sum_fy - 100.0).abs() > 0.5).height
            self.add_check(
                table,
                "pass_rates final years rates add up to 100",
                "OK" if diff_fy == 0 else "FAIL",
                str(diff_fy),
                "0",
            )

            df_sec = df.filter(
                pl.col("pass_rate_secondary").is_not_null()
                & pl.col("failure_rate_secondary").is_not_null()
                & pl.col("dropout_rate_secondary").is_not_null()
            )
            sum_sec = (
                pl.col("pass_rate_secondary")
                + pl.col("failure_rate_secondary")
                + pl.col("dropout_rate_secondary")
            )
            diff_sec = df_sec.filter((sum_sec - 100.0).abs() > 0.5).height
            self.add_check(
                table,
                "pass_rates secondary rates add up to 100",
                "OK" if diff_sec == 0 else "FAIL",
                str(diff_sec),
                "0",
            )

            rate_cols = [
                "pass_rate_final_years",
                "failure_rate_final_years",
                "dropout_rate_final_years",
                "pass_rate_secondary",
                "failure_rate_secondary",
                "dropout_rate_secondary",
            ]
            cols_present = [c for c in rate_cols if c in df.columns]
            if cols_present:
                out_bounds = pl.any_horizontal(
                    [((pl.col(c) < 0.0) | (pl.col(c) > 100.0)).fill_null(False) for c in cols_present]
                )
                rates_invalid = df.filter(out_bounds).height
            else:
                rates_invalid = 0
            self.add_check(
                table,
                "pass_rates rates within 0-100",
                "OK" if rates_invalid == 0 else "FAIL",
                str(rates_invalid),
                "0",
            )

            df_sp_2023 = df.filter(
                (pl.col("municipality_code") == "3550308")
                & (pl.col("year") == 2023)
                & (pl.col("location") == "total")
                & (pl.col("network") == "total")
            )
            if df_sp_2023.height > 0:
                val_fy = df_sp_2023["pass_rate_final_years"][0]
                val_sec = df_sp_2023["pass_rate_secondary"][0]
                self.add_check(
                    table,
                    "pass_rates SP 2023 pass rate final years",
                    "OK" if val_fy is not None and abs(val_fy - 97.5) < 0.01 else "FAIL",
                    str(val_fy),
                    "97.5",
                )
                self.add_check(
                    table,
                    "pass_rates SP 2023 pass rate secondary",
                    "OK" if val_sec is not None and abs(val_sec - 91.0) < 0.01 else "FAIL",
                    str(val_sec),
                    "91.0",
                )

        elif clean_name == "ideb_final_years_network":
            nn_df = df.filter(pl.col("ideb_final_years").is_not_null())
            out_bounds = nn_df.filter(
                (pl.col("ideb_final_years") < 0.0) | (pl.col("ideb_final_years") > 10.0)
            ).height
            self.add_check(
                table,
                "ideb_final_years_network values within 0-10",
                "OK" if out_bounds == 0 else "FAIL",
                str(out_bounds),
                "0",
            )

            nn_count = nn_df.height
            self.add_check(
                table,
                "ideb_final_years_network not null",
                "OK" if nn_count == 136167 else "FAIL",
                str(nn_count),
                "136167",
            )

            df_sp_2023 = df.filter(
                (pl.col("municipality_code") == "3550308") & (pl.col("year") == 2023)
            )
            for net, exp_val, exp_str in [
                ("state", 4.9, "4.9"),
                ("municipal", 4.8, "4.8"),
                ("public", 4.8, "4.8"),
            ]:
                row = df_sp_2023.filter(pl.col("network") == net)
                if row.height > 0:
                    val = row["ideb_final_years"][0]
                    status = "OK" if val is not None and abs(val - exp_val) < 0.01 else "FAIL"
                    self.add_check(
                        table,
                        f"ideb_final_years_network SP 2023 {net}",
                        status,
                        str(val),
                        exp_str,
                    )

        elif clean_name == "municipalities":
            n_meso = (
                df["mesoregion_2011_code"].drop_nulls().n_unique()
                if "mesoregion_2011_code" in df.columns
                else 0
            )
            self.add_check(
                table,
                "municipalities 2011 mesoregions",
                "OK" if n_meso == 137 else "FAIL",
                str(n_meso),
                "137",
            )

            n_micro = (
                df["microregion_2011_code"].drop_nulls().n_unique()
                if "microregion_2011_code" in df.columns
                else 0
            )
            self.add_check(
                table,
                "municipalities 2011 microregions",
                "OK" if n_micro == 558 else "FAIL",
                str(n_micro),
                "558",
            )

            reg_cols = [
                "mesoregion_2011_code",
                "mesoregion_2011_name",
                "microregion_2011_code",
                "microregion_2011_name",
            ]
            if all(c in df.columns for c in reg_cols):
                without_2011 = df.filter(
                    pl.col("mesoregion_2011_code").is_null()
                    & pl.col("mesoregion_2011_name").is_null()
                    & pl.col("microregion_2011_code").is_null()
                    & pl.col("microregion_2011_name").is_null()
                ).height
            else:
                without_2011 = 0
            self.add_check(
                table,
                "municipalities without 2011 regions",
                "OK" if without_2011 == 6 else "FAIL",
                str(without_2011),
                "6",
            )
        
    def audit_keys(self, df: pl.DataFrame, table: str, key_cols: List[str]):
        """Audits that primary key columns `key_cols` have neither nulls nor duplicate rows."""
        if not key_cols:
            return
        
        has_nulls = False
        null_counts = []
        for c in key_cols:
            if c in df.columns:
                n = df[c].null_count()
                if n > 0:
                    has_nulls = True
                    null_counts.append(f"{c}: {n}")
        
        if not has_nulls:
            self.add_check(table, "key without nulls", "OK", "0", "0")
        else:
            self.add_check(table, "key without nulls", "FAIL", str(null_counts), "0", "Critical: keys must not be null")
            
        dups = df.group_by(key_cols).len().filter(pl.col("len") > 1).height
        if dups == 0:
            self.add_check(table, "key without duplicates", "OK", "0", "0")
        else:
            self.add_check(table, "key without duplicates", "FAIL", str(dups), "0", "Critical: keys must not be duplicated")

    def audit_municipal_codes(self, df: pl.DataFrame, table: str, col_name="municipality_code"):
        """Validates that all municipality codes in `col_name` belong to the valid municipal registry."""
        if col_name in df.columns and self.valid_codes:
            invalid_count = df.filter(~pl.col(col_name).is_in(self.valid_codes)).height
            if invalid_count == 0:
                self.add_check(table, f"municipality codes ({col_name})", "OK", "0 invalid", "0 invalid")
            else:
                self.add_check(table, f"municipality codes ({col_name})", "FAIL", f"{invalid_count} invalid", "0 invalid", "Critical: all must belong to municipalities.parquet")

    def audit_negative_values(self, df: pl.DataFrame, table: str):
        """Checks numeric metric columns in `df` to ensure none contain negative values."""
        numeric_cols = [c for c, dtype in zip(df.columns, df.dtypes) if dtype.is_numeric()]
        failures = []
        for c in numeric_cols:
            if c in ["latitude", "longitude", "gdp", "gdp_per_capita"] or c.startswith(("exp_", "rev_")):
                continue
            neg_count = df.filter(pl.col(c) < 0).height
            if neg_count > 0:
                failures.append(f"{c}: {neg_count}")
        if not failures:
            self.add_check(table, "non-negative values", "OK", "Nenhum", "Nenhum")
        else:
            self.add_check(table, "non-negative values", "FAIL", str(failures), "Nenhum", "Counts must not be negative")
            
    def audit_geographic_domains(self, df: pl.DataFrame, table: str):
        """Validates geographic bounding boxes, positive areas, and border lengths."""
        clean_name = table.replace("[processed] ", "").replace("[intermediate] ", "")
        if clean_name in ["municipalities", "ibge_municipalities"]:
            area_inv = df.filter(pl.col("area_km2") <= 0).height
            # Fernando de Noronha is -32 longitude (around -32.4)
            # latitude should be within -35 and 6
            # longitude should be within -75 and -30
            lat_inv = df.filter((pl.col("latitude") < -35) | (pl.col("latitude") > 6)).height
            lon_inv = df.filter((pl.col("longitude") < -75) | (pl.col("longitude") > -30)).height
            if area_inv == 0 and lat_inv == 0 and lon_inv == 0:
                self.add_check(table, "geographic domains", "OK", "Correct", "Correct")
            else:
                self.add_check(table, "geographic domains", "FAIL", f"area_inv={area_inv}, lat_inv={lat_inv}, lon_inv={lon_inv}", "0", "Brazil bounds")
        
        if clean_name in ["neighboring_municipalities", "ibge_neighboring_municipalities"]:
            if self.valid_codes:
                inv_code_lim = df.filter(~pl.col("neighbor_municipality_code").is_in(self.valid_codes)).height
                if inv_code_lim == 0:
                    self.add_check(table, "neighboring codes", "OK", "Correct", "Correct")
                else:
                    self.add_check(table, "neighboring codes", "FAIL", f"{inv_code_lim} invalid", "0", "Must belong to the registry")
            comp_inv = df.filter(pl.col("border_length_km") < 0).height # 0 is accepted
            if comp_inv == 0:
                self.add_check(table, "non-negative lengths", "OK", "Correct", "Correct")
            else:
                self.add_check(table, "non-negative lengths", "FAIL", f"{comp_inv} < 0", "0", "Length must be >= 0")

    def audit_education_by_network(
        self,
        education: pl.DataFrame,
        enrollment_network: pl.DataFrame,
        federal_schools: pl.DataFrame,
        ideb_network: pl.DataFrame,
    ) -> None:
        """Audits consistency between education table and network-disaggregated tables."""
        table = "[processed] education by network"

        # 1. secondary enrolment by network equals education
        en_sub = (
            enrollment_network.filter(
                (pl.col("year") >= 2007) & (pl.col("year") <= 2023)
            )
            .group_by(["municipality_code", "year"])
            .agg(pl.col("enroll_secondary").fill_null(0).sum().alias("en_sec"))
        )
        ed_sub = (
            education.filter((pl.col("year") >= 2007) & (pl.col("year") <= 2023))
            .select([
                "municipality_code",
                "year",
                pl.col("enroll_secondary").fill_null(0).alias("ed_sec"),
            ])
        )
        joined1 = en_sub.join(ed_sub, on=["municipality_code", "year"], how="full", coalesce=True)
        diff1 = joined1.filter(
            pl.col("en_sec").fill_null(0) != pl.col("ed_sec").fill_null(0)
        ).height

        rule1 = "secondary enrolment by network equals education"
        status1 = "OK" if diff1 == 0 else "FAIL"
        detail1 = "" if diff1 == 0 else "Critical: secondary enrolment by network does not equal education"
        self.add_check(table, rule1, status1, str(diff1), "0", detail1)

        # 2. federal enrolment equals federal_schools
        fs_active = federal_schools.filter(pl.col("operating_status") == "active")
        fs_grouped = fs_active.group_by(["municipality_code", "year"]).agg([
            pl.col("enroll_secondary").fill_null(0).sum().alias("fs_all_sec"),
            pl.col("enroll_vocational_technical").fill_null(0).sum().alias("fs_all_voc"),
            pl.when(pl.col("school_class") == "federal_network")
            .then(pl.col("enroll_secondary").fill_null(0))
            .otherwise(0)
            .sum()
            .alias("fs_fed_sec"),
            pl.when(pl.col("school_class") == "federal_network")
            .then(pl.col("enroll_vocational_technical").fill_null(0))
            .otherwise(0)
            .sum()
            .alias("fs_fed_voc"),
        ])

        en_fed = enrollment_network.filter(
            pl.col("network").is_in(["federal_network", "federal_other"])
        )
        en_fed_grouped = en_fed.group_by(["municipality_code", "year"]).agg([
            pl.col("enroll_secondary").fill_null(0).sum().alias("en_all_sec"),
            pl.col("enroll_vocational_technical").fill_null(0).sum().alias("en_all_voc"),
            pl.when(pl.col("network") == "federal_network")
            .then(pl.col("enroll_secondary").fill_null(0))
            .otherwise(0)
            .sum()
            .alias("en_fed_sec"),
            pl.when(pl.col("network") == "federal_network")
            .then(pl.col("enroll_vocational_technical").fill_null(0))
            .otherwise(0)
            .sum()
            .alias("en_fed_voc"),
        ])

        joined2 = fs_grouped.join(en_fed_grouped, on=["municipality_code", "year"], how="full", coalesce=True)
        diff2 = joined2.filter(
            (pl.col("fs_all_sec").fill_null(0) != pl.col("en_all_sec").fill_null(0))
            | (pl.col("fs_all_voc").fill_null(0) != pl.col("en_all_voc").fill_null(0))
            | (pl.col("fs_fed_sec").fill_null(0) != pl.col("en_fed_sec").fill_null(0))
            | (pl.col("fs_fed_voc").fill_null(0) != pl.col("en_fed_voc").fill_null(0))
        ).height

        rule2 = "federal enrolment equals federal_schools"
        status2 = "OK" if diff2 == 0 else "FAIL"
        detail2 = "" if diff2 == 0 else "Critical: federal enrolment does not equal federal_schools"
        self.add_check(table, rule2, status2, str(diff2), "0", detail2)

        # 3. IDEB public by network equals education
        id_sub = (
            ideb_network.filter(
                (pl.col("network") == "public")
                & (pl.col("year") >= 2007)
                & (pl.col("year") <= 2023)
                & pl.col("ideb_final_years").is_not_null()
            )
            .select([
                "municipality_code",
                "year",
                pl.col("ideb_final_years").alias("ideb_net"),
            ])
        )
        ed_ideb = (
            education.filter(
                (pl.col("year") >= 2007)
                & (pl.col("year") <= 2023)
                & pl.col("ideb_final_years_public").is_not_null()
            )
            .select([
                "municipality_code",
                "year",
                pl.col("ideb_final_years_public").alias("ideb_ed"),
            ])
        )
        joined3 = id_sub.join(ed_ideb, on=["municipality_code", "year"], how="full", coalesce=True)
        diff3 = joined3.filter(
            pl.col("ideb_net").is_null()
            | pl.col("ideb_ed").is_null()
            | ((pl.col("ideb_net") - pl.col("ideb_ed")).abs() > 1e-9)
        ).height

        rule3 = "IDEB public by network equals education"
        status3 = "OK" if diff3 == 0 else "FAIL"
        detail3 = "" if diff3 == 0 else "Critical: IDEB public by network does not equal education"
        self.add_check(table, rule3, status3, str(diff3), "0", detail3)

    def get_checks_df(self) -> pl.DataFrame:
        """Returns recorded check results as a Polars DataFrame with the audit schema."""
        schema = {
            "table": pl.String,
            "rule": pl.String,
            "status": pl.String,
            "observed": pl.String,
            "expected": pl.String,
            "detail": pl.String
        }
        return pl.DataFrame(self.checks, schema=schema)
