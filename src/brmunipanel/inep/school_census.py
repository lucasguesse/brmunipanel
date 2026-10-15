"""
Censo Escolar - INEP

Source: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (INEP)
Source unit: school
Key: municipality, year, administrative dependency, location

Caveats:
- enroll_basic_edu is the total published by INEP (from 2007 onwards), not the sum of other stages, which overlap.
- The sum of teachers counts more than once those who work in more than one school in the municipality.
- Null means that no school in the group has data.
- In 2006, the layout is different: the reference date is March 29, 2006 (and from 2007 onwards it is the last Wednesday of May); blanks are zero; EJA includes blended courses in enrollments and not in classes; the normal track and integrated secondary education are within upper secondary education; fourteen columns are null; and the series changes method in 2007, when INEP began collecting the census per student.
- Teachers in 2006: these are practicing teachers at the school, and those at each level count the same teacher in more than one.
"""

from pathlib import Path
import zipfile
import tempfile
import polars as pl

from brmunipanel.inep.connection import create_session
from brmunipanel.core import Request, InvalidResponse, download_batch

CURRENT_YEARS = list(range(2007, 2024))
ALL_YEARS = list(range(2006, 2024))

STAGES = [
    ("BAS", "basic_edu"),
    ("INF", "early_childhood"),
    ("INF_CRE", "daycare"),
    ("INF_PRE", "preschool"),
    ("FUND", "elementary"),
    ("FUND_AI", "elementary_early_years"),
    ("FUND_AF", "elementary_final_years"),
    ("MED", "secondary"),
    ("PROF", "vocational"),
    ("PROF_TEC", "vocational_technical"),
    ("EJA", "eja"),
    ("EJA_FUND", "eja_elementary"),
    ("EJA_MED", "eja_secondary"),
    ("ESP", "inclusive_ed"),
    ("ESP_CC", "inclusive_ed_common_classes"),
    ("ESP_CE", "inclusive_ed_exclusive_classes"),
]

COUNT_COLUMNS = []
for orig, dest in STAGES:
    COUNT_COLUMNS.append((f"QT_MAT_{orig}", f"enroll_{dest}"))
for orig, dest in STAGES:
    COUNT_COLUMNS.append((f"QT_DOC_{orig}", f"teachers_{dest}"))
for orig, dest in STAGES:
    COUNT_COLUMNS.append((f"QT_TUR_{orig}", f"classes_{dest}"))

def validate_zip(content: bytes):
    """Raises `InvalidResponse` if `content` does not start with standard ZIP magic bytes."""
    if not content.startswith(b"PK\x03\x04"):
        raise InvalidResponse("The content is not a valid ZIP file")

def download(folder: Path | str, **options):
    """Downloads School Census microdata ZIP files (2006–2023) into `folder`."""
    folder = Path(folder)
    reqs = []
    for year in ALL_YEARS:
        reqs.append(
            Request(
                key=f"school-census/{year}",
                url=f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{year}.zip",
                file=f"school-census/school-census_{year}.zip",
                method="GET",
                compress=False
            )
        )
    session = options.pop("session", None) or create_session()
    download_batch(reqs, folder, session=session, validate=validate_zip, interval=1.0, **options)

def _get_dn(cols):
    res = []
    for c in cols:
        res.append(c)
        res.append('N' + c[1:])
    return res

def read_year_2006(folder: Path, valid_municipalities: set[str]) -> pl.DataFrame:
    """Reads 2006 School Census microdata from the annual ZIP file using the legacy layout.

    Extracts `CENSOESC_2006.CSV` and `EDUCPROF_2006.CSV`, mapping categories and aggregating
    school-level counts for valid municipalities.
    """
    zip_path = folder / "school-census/school-census_2006.zip"
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        census_cands = [info for info in z.infolist() if 'CENSOESC_2006.CSV' in info.filename.upper()]
        edu_cands = [info for info in z.infolist() if 'EDUCPROF_2006.CSV' in info.filename.upper()]
        
        if len(census_cands) != 1 or len(edu_cands) != 1:
            raise ValueError("Year 2006: CENSOESC_2006.CSV or EDUCPROF_2006.CSV missing from the ZIP")
            
        member_census = census_cands[0]
        member_edu = edu_cands[0]
        
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            z.extract(member_census, td_path)
            z.extract(member_edu, td_path)
            
            file_census = td_path / member_census.filename
            file_edu = td_path / member_edu.filename
            
            columns_all = set(pl.scan_csv(file_census, separator="|", encoding="utf8-lossy", infer_schema_length=0).collect_schema().names())
            
            # Variable mapping
            enrollments = {}
            enrollments['daycare'] = _get_dn(['DPE119'])
            enrollments['preschool'] = _get_dn(['DPE11D'])
            enrollments['early_childhood'] = enrollments['daycare'] + enrollments['preschool']
            enrollments['elementary_early_years'] = _get_dn(['DEF11C', 'DEF11D', 'DEF11E', 'DEF11F', 'DE9F11C', 'DE9F11D', 'DE9F11E', 'DE9F11F', 'DE9F11G'])
            enrollments['elementary_final_years'] = _get_dn(['DEF11G', 'DEF11H', 'DEF11I', 'DEF11J', 'DE9F11H', 'DE9F11I', 'DE9F11J', 'DE9F11N'])
            enrollments['elementary'] = enrollments['elementary_early_years'] + enrollments['elementary_final_years']
            enrollments['secondary'] = _get_dn(['DEM118', 'DEM119', 'DEM11A', 'DEM11B', 'DEM11C'])
            
            eja_fund = _get_dn(['DES101F', 'DES101G', 'DES101H', 'DES101I'])
            for x in list("23456789ABCD"):
                for y in ["3", "4"]:
                    eja_fund.append(f"VES12{x}{y}")
            enrollments['eja_elementary'] = eja_fund
            
            eja_secondary = _get_dn(['DES101A'])
            for x in list("23456789ABCD"):
                eja_secondary.append(f"VES12{x}2")
            enrollments['eja_secondary'] = eja_secondary
            enrollments['eja'] = enrollments['eja_elementary'] + enrollments['eja_secondary']
            
            enrollments['inclusive_ed_exclusive_classes'] = [c for c in columns_all if any(c.startswith(p) for p in ['VEE10', 'VEE11', 'VEE16', 'VEE17'])]
            enrollments['inclusive_ed_common_classes'] = [c for c in columns_all if any(c.startswith(p) for p in ['VEE12', 'VEE13', 'VEE18', 'VEE19'])]
            enrollments['inclusive_ed'] = enrollments['inclusive_ed_exclusive_classes'] + enrollments['inclusive_ed_common_classes']
            
            classes = {}
            classes['daycare'] = _get_dn(['DPE113'])
            classes['preschool'] = _get_dn(['DPE117'])
            classes['early_childhood'] = classes['daycare'] + classes['preschool'] + _get_dn(['DPE11F'])
            classes['elementary_early_years'] = _get_dn(['DEF113', 'DEF114', 'DEF115', 'DEF116', 'DE9F113', 'DE9F114', 'DE9F115', 'DE9F116', 'DE9F117'])
            classes['elementary_final_years'] = _get_dn(['DEF117', 'DEF118', 'DEF119', 'DEF11A', 'DE9F118', 'DE9F119', 'DE9F11A', 'DE9F11L'])
            classes['elementary'] = classes['elementary_early_years'] + classes['elementary_final_years'] + _get_dn(['DEF11B', 'DE9F11B', 'DEF11K', 'DE9F11K'])
            classes['secondary'] = _get_dn(['DEM113', 'DEM114', 'DEM115', 'DEM116', 'DEM117'])
            classes['eja_elementary'] = _get_dn(['DES101B', 'DES101C', 'DES101D', 'DES101E'])
            classes['eja_secondary'] = _get_dn(['DES1016'])
            classes['eja'] = classes['eja_elementary'] + classes['eja_secondary']
            
            teachers = {}
            teachers['basic_edu'] = ['PROFESS']
            teachers['daycare'] = ['VDG1CA']
            teachers['preschool'] = ['VDG1C1']
            teachers['elementary'] = ['VDG1C3']
            teachers['secondary'] = ['VDG1C4']
            teachers['inclusive_ed'] = ['VDG1C5']
            teachers['eja'] = ['VDG1C6']
            teachers['vocational_technical'] = ['VDG1C9']
            teachers['vocational'] = ['VDG1C9']
            
            edu_cols_to_sum = [f"EP31{i}" for i in range(1, 8)] + [f"EP32{i}" for i in range(1, 8)]
            
            columns_to_read = ["MASCARA", "CODMUNIC", "DEP", "LOC", "CODFUNC", "ANO"]
            for m in enrollments.values():
                columns_to_read.extend(m)
            for t in classes.values():
                columns_to_read.extend(t)
            for d in teachers.values():
                columns_to_read.extend(d)
            columns_to_read = list(set(columns_to_read))
            
            lf = pl.scan_csv(
                file_census,
                separator="|",
                encoding="utf8-lossy",
                infer_schema_length=0,
            ).select(columns_to_read)
            
            lf = lf.select([pl.col(c).str.strip_chars() for c in columns_to_read])
            lf = lf.filter(pl.col("CODFUNC") == "Ativo")
            
            dep_map = {"Federal": "federal", "Estadual": "state", "Municipal": "municipal", "Particular": "private"}
            loc_map = {"Urbana": "urban", "Rural": "rural"}
            
            lf = lf.with_columns(
                (pl.col("CODMUNIC").str.slice(0, 2) + pl.col("CODMUNIC").str.slice(-5)).alias("municipality_code")
            )
            
            # Lazy validations for value error
            columns_validate = list(set(columns_to_read) - {"MASCARA", "CODMUNIC", "DEP", "LOC", "CODFUNC", "ANO"})
            exprs_val = []
            for c in columns_validate:
                exprs_val.append(
                    (~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).any().alias(c)
                )
            # Run a one-off collect of the validations to stop before computing the aggregations
            res = lf.select(exprs_val).collect(engine="streaming").row(0)
            for i, c in enumerate(columns_validate):
                if res[i]:
                    # To fetch the first cases in the error
                    invalid = lf.filter(~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).select("MASCARA", c).head(3).collect()
                    raise ValueError(f"Year 2006: non-integer or negative values in column {c}. Example: {invalid}")
            
            exprs = []
            for k, v in enrollments.items():
                exprs.append(
                    pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in v]).alias(f"enroll_{k}")
                )
            for k, v in classes.items():
                exprs.append(
                    pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in v]).alias(f"classes_{k}")
                )
            for k, v in teachers.items():
                exprs.append(
                    pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in v]).alias(f"teachers_{k}")
                )
            
            lf = lf.with_columns(exprs)
            
            # EDUCPROF table in lazy plan
            lf_edu = pl.scan_csv(
                file_edu,
                separator="|",
                encoding="utf8-lossy",
                infer_schema_length=0,
            ).select(["MASCARA", "CODFUNC"] + edu_cols_to_sum)
            
            lf_edu = lf_edu.select([pl.col(c).str.strip_chars() for c in ["MASCARA", "CODFUNC"] + edu_cols_to_sum])
            lf_edu = lf_edu.filter(pl.col("CODFUNC") == "Ativo")
            
            exprs_val_edu = []
            for c in edu_cols_to_sum:
                exprs_val_edu.append(
                    (~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).any().alias(c)
                )
            res_edu = lf_edu.select(exprs_val_edu).collect(engine="streaming").row(0)
            for i, c in enumerate(edu_cols_to_sum):
                if res_edu[i]:
                    invalid = lf_edu.filter(~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).select("MASCARA", c).head(3).collect()
                    raise ValueError(f"Year 2006: non-integer or negative values in column {c} of EDUCPROF. Example: {invalid}")
            
            lf_edu = lf_edu.with_columns(
                pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in edu_cols_to_sum]).alias("enroll_vocational_technical")
            )
                
            lf_edu_agg = lf_edu.group_by("MASCARA").agg(pl.col("enroll_vocational_technical").sum())
            
            lf = lf.join(lf_edu_agg, on="MASCARA", how="left")
            lf = lf.with_columns(
                pl.col("enroll_vocational_technical").fill_null(0).alias("enroll_vocational_technical")
            )
            lf = lf.with_columns(
                pl.col("enroll_vocational_technical").alias("enroll_vocational")
            )
            
            # The fourteen null columns
            lf = lf.with_columns(
                pl.lit(None).cast(pl.Int64).alias("enroll_basic_edu"),
                pl.lit(None).cast(pl.Int64).alias("classes_basic_edu"),
                pl.lit(None).cast(pl.Int64).alias("teachers_early_childhood"),
                pl.lit(None).cast(pl.Int64).alias("teachers_elementary_early_years"),
                pl.lit(None).cast(pl.Int64).alias("teachers_elementary_final_years"),
                pl.lit(None).cast(pl.Int64).alias("teachers_eja_elementary"),
                pl.lit(None).cast(pl.Int64).alias("teachers_eja_secondary"),
                pl.lit(None).cast(pl.Int64).alias("teachers_inclusive_ed_common_classes"),
                pl.lit(None).cast(pl.Int64).alias("teachers_inclusive_ed_exclusive_classes"),
                pl.lit(None).cast(pl.Int64).alias("classes_vocational"),
                pl.lit(None).cast(pl.Int64).alias("classes_vocational_technical"),
                pl.lit(None).cast(pl.Int64).alias("classes_inclusive_ed"),
                pl.lit(None).cast(pl.Int64).alias("classes_inclusive_ed_common_classes"),
                pl.lit(None).cast(pl.Int64).alias("classes_inclusive_ed_exclusive_classes")
            )
            
            # Rename derived columns
            rename_map = {}
            for qt_col, metric_name in COUNT_COLUMNS:
                rename_map[metric_name] = qt_col
                
            lf = lf.rename(rename_map)
            lf = lf.with_columns(pl.lit(2006).cast(pl.Int16).alias("year"))
            
            # Define required columns before collection
            col_order = ["municipality_code", "year", "ANO", "CODMUNIC", "DEP", "LOC", "MASCARA"]
            for qt_col, _ in COUNT_COLUMNS:
                col_order.append(qt_col)
            
            df = lf.select(col_order).collect(engine="streaming")
            
            df = df.with_columns(
                pl.col("DEP").replace_strict(dep_map, default=pl.col("DEP")).alias("admin_dependency"),
                pl.col("LOC").replace_strict(loc_map, default=pl.col("LOC")).alias("location")
            )
            
            wrong_year = df.filter(pl.col("ANO") != "2006")
            if len(wrong_year) > 0:
                raise ValueError(f"Year 2006: there are records with ANO other than 2006. Example: {wrong_year.head(3)}")
                
            invalid_admin = df.filter(~pl.col("admin_dependency").is_in(dep_map.values()) | pl.col("admin_dependency").is_null())
            if len(invalid_admin) > 0:
                raise ValueError(f"Year 2006: invalid values in DEP. Example: {invalid_admin.head(3)}")
                
            invalid_loc = df.filter(~pl.col("location").is_in(loc_map.values()) | pl.col("location").is_null())
            if len(invalid_loc) > 0:
                raise ValueError(f"Year 2006: invalid values in LOC. Example: {invalid_loc.head(3)}")
            
            invalid_muni_len = df.filter((pl.col("CODMUNIC").str.len_chars() != 12) | pl.col("CODMUNIC").is_null())
            if len(invalid_muni_len) > 0:
                raise ValueError(f"Year 2006: CODMUNIC with length other than 12. Example: {invalid_muni_len.head(3)}")
            
            invalid_muni = df.filter(~pl.col("municipality_code").is_in(valid_municipalities))
            if len(invalid_muni) > 0:
                raise ValueError(f"Year 2006: invalid or null municipalities in CODMUNIC. Example: {invalid_muni.head(3)}")
                
            active_schools_masks = set(df["MASCARA"].to_list())
            df_edu_raw = lf_edu.collect()
            invalid_edu = df_edu_raw.filter(~pl.col("MASCARA").is_in(active_schools_masks))
            if len(invalid_edu) > 0:
                raise ValueError(f"Year 2006: active technical course of an inactive or missing school. Example: {invalid_edu.head(3)}")
            
            # Return removing temporary columns
            return df.drop(["ANO", "CODMUNIC", "DEP", "LOC", "MASCARA"])



def read_current_year(folder: Path, year: int, valid_municipalities: set[str]) -> pl.DataFrame:
    """Reads School Census microdata for `year` (2007–2023) from the annual ZIP file.

    Extracts `microdados_ed_basica`, filters active schools, and maps administrative dependency
    and location.
    """
    zip_path = folder / f"school-census/school-census_{year}.zip"
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        candidates = [info for info in z.infolist() if 'microdados_ed_basica' in info.filename.lower() and info.filename.lower().endswith('.csv')]
        if len(candidates) != 1:
            raise ValueError(f"Year {year}: expected exactly 1 CSV file of microdados_ed_basica in the ZIP, found {len(candidates)}")
        
        member = candidates[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extract(member, tmpdir)
            extracted_file = Path(tmpdir) / member.filename
            
            schema_header = pl.read_csv(extracted_file, separator=";", n_rows=1, encoding="utf8-lossy", infer_schema_length=0)
            columns_in_file = set(schema_header.columns)
            
            required_columns = ["CO_MUNICIPIO", "TP_DEPENDENCIA", "TP_LOCALIZACAO", "TP_SITUACAO_FUNCIONAMENTO"]
            for col_orig, _ in COUNT_COLUMNS:
                required_columns.append(col_orig)
            
            for col in required_columns:
                if col not in columns_in_file:
                    raise ValueError(f"Year {year}: required column {col} missing from the CSV")
            
            columns_to_read = list(required_columns)
            if "NU_ANO_CENSO" in columns_in_file:
                columns_to_read.append("NU_ANO_CENSO")
                
            df = pl.read_csv(
                extracted_file,
                separator=";",
                encoding="utf8-lossy",
                infer_schema_length=0,
                columns=columns_to_read
            )
            
            if "NU_ANO_CENSO" in df.columns:
                wrong = df.filter(pl.col("NU_ANO_CENSO") != str(year))
                if len(wrong) > 0:
                    raise ValueError(f"Year {year}: there are records with NU_ANO_CENSO other than {year}. Example: {wrong.head(3)}")
                df = df.drop("NU_ANO_CENSO")
            
            df = df.filter(pl.col("TP_SITUACAO_FUNCIONAMENTO") == "1")
            
            dep_map = {"1": "federal", "2": "state", "3": "municipal", "4": "private"}
            loc_map = {"1": "urban", "2": "rural"}
            
            invalid_admin = df.filter(~pl.col("TP_DEPENDENCIA").is_in(dep_map.keys()) | pl.col("TP_DEPENDENCIA").is_null())
            if len(invalid_admin) > 0:
                raise ValueError(f"Year {year}: invalid values in TP_DEPENDENCIA. Example: {invalid_admin.head(3)}")
                
            invalid_loc = df.filter(~pl.col("TP_LOCALIZACAO").is_in(loc_map.keys()) | pl.col("TP_LOCALIZACAO").is_null())
            if len(invalid_loc) > 0:
                raise ValueError(f"Year {year}: invalid values in TP_LOCALIZACAO. Example: {invalid_loc.head(3)}")
            
            df = df.with_columns(
                pl.col("TP_DEPENDENCIA").replace(dep_map).alias("admin_dependency"),
                pl.col("TP_LOCALIZACAO").replace(loc_map).alias("location")
            )
            
            invalid_muni = df.filter(~pl.col("CO_MUNICIPIO").is_in(valid_municipalities) | pl.col("CO_MUNICIPIO").is_null())
            if len(invalid_muni) > 0:
                raise ValueError(f"Year {year}: invalid or null municipalities in CO_MUNICIPIO. Example: {invalid_muni.head(3)}")
            
            df = df.rename({"CO_MUNICIPIO": "municipality_code"})
            
            exprs = []
            for orig, _ in COUNT_COLUMNS:
                invalid = df.filter(~pl.col(orig).is_null() & (pl.col(orig) != "") & ~pl.col(orig).str.contains(r"^\d+$"))
                if len(invalid) > 0:
                    raise ValueError(f"Year {year}: non-integer or negative values in column {orig}. Example: {invalid.head(3)}")
                
                exprs.append(
                    pl.when(pl.col(orig) == "").then(None).otherwise(pl.col(orig)).cast(pl.Int64).alias(orig)
                )
            
            df = df.with_columns(exprs)
            df = df.with_columns(pl.lit(year).cast(pl.Int16).alias("year"))
            
            return df

def harmonize(folder: Path | str, municipalities: pl.DataFrame) -> pl.DataFrame:
    """Harmonizes School Census microdata (2006–2023) across all covered years.

    Aggregates active schools, enrollments, teachers, and classes by `municipality_code`, `year`,
    `admin_dependency`, and `location`.
    """
    folder = Path(folder)
    valid_municipalities = set(municipalities["municipality_code"].to_list())
    
    dfs = []
    for year in ALL_YEARS:
        if year == 2006:
            df_year = read_year_2006(folder, valid_municipalities)
        else:
            df_year = read_current_year(folder, year, valid_municipalities)
        
        aggs = [pl.len().cast(pl.Int64).alias("schools")]
        for orig, dest in COUNT_COLUMNS:
            aggs.append(
                pl.when(pl.col(orig).is_null().all())
                .then(None)
                .otherwise(pl.col(orig).sum())
                .alias(dest)
            )
            
        df_agg = (
            df_year
            .group_by(["municipality_code", "year", "admin_dependency", "location"])
            .agg(aggs)
        )
        dfs.append(df_agg)
        
    df_final = pl.concat(dfs)
    df_final = df_final.sort(["municipality_code", "year", "admin_dependency", "location"])
    
    col_order = ["municipality_code", "year", "admin_dependency", "location", "schools"]
    for _, dest in COUNT_COLUMNS:
        col_order.append(dest)
        
    df_final = df_final.select(col_order)
    
    return df_final
