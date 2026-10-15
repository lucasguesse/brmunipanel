"""
Censo da Educação Superior - INEP

Source: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (INEP)
Source tables: CADASTRO_CURSOS and CADASTRO_IES
Key: municipality, year, administrative category

Caveats:
- Only in-person education enters the columns. Distance-learning courses are not counted.
- Teachers are those of the entire institution, in the seat municipality, and include those working in distance-learning courses of an institution that also offers in-person courses.
- The 'special' category was created by INEP in 2012.
- The absence of a row in a covered year means that there is no institution with an in-person course or seat in the municipality for that category.
- From 2000 to 2008: the layout is different; enrollment is that of the first semester; teachers from 2000 to 2003 are the total minus those on leave, and those from 2004 to 2008 come from the practicing teachers variable; the old layout records offerings in more small municipalities than the new one (1,365 municipalities with courses in 2008 and 1,159 in 2009); teachers increase from 321 thousand in 2008 to 341 thousand in 2009, when INEP began collecting the census per teacher; and the sum of undergraduate enrollments is about 0.05% below the published total.
"""
from __future__ import annotations

from pathlib import Path
import zipfile
import tempfile
import polars as pl
import re

from brmunipanel.inep.connection import create_session
from brmunipanel.core import Request, InvalidResponse, download_batch

CURRENT_YEARS = list(range(2009, 2025))
LEGACY_YEARS = list(range(2000, 2009))
ALL_YEARS = list(range(2000, 2025))

def validate_zip(content: bytes):
    if not content.startswith(b"PK\x03\x04"):
        raise InvalidResponse("The content is not a valid ZIP file")

def download(folder: Path | str, **options):
    folder = Path(folder)
    reqs = []
    for year in ALL_YEARS:
        reqs.append(
            Request(
                key=f"higher-education-census/{year}",
                url=f"https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_{year}.zip",
                file=f"higher-education-census/higher-education-census_{year}.zip",
                method="GET",
                compress=False
            )
        )
    session = options.pop("session", None) or create_session()
    download_batch(reqs, folder, session=session, validate=validate_zip, interval=1.0, **options)

def read_legacy_year(folder: Path, year: int, valid_municipalities: set[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    zip_path = folder / f"higher-education-census/higher-education-census_{year}.zip"
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        cand_grad = [info for info in z.infolist() if info.filename.lower().endswith('/graduacao_presencial.csv')]
        if len(cand_grad) != 1:
            raise ValueError(f"Year {year}: expected exactly 1 CSV file of graduacao_presencial.csv in the ZIP, found {len(cand_grad)}")
        
        cand_seq = [info for info in z.infolist() if info.filename.lower().endswith('/forme_presencial.csv')]
        if len(cand_seq) != 1:
            raise ValueError(f"Year {year}: expected exactly 1 CSV file of forme_presencial.csv in the ZIP, found {len(cand_seq)}")
            
        cand_hei = [info for info in z.infolist() if info.filename.lower().endswith('/instituicao.csv')]
        if len(cand_hei) != 1:
            raise ValueError(f"Year {year}: expected exactly 1 CSV file of instituicao.csv in the ZIP, found {len(cand_hei)}")
        
        id_col = "IES" if year == 2008 else "MASCARA"
        
        def read_file(member, id_col, muni_col, required_prefixes, is_hei=False):
            with z.open(member.filename) as f:
                header_line = f.readline()
                header_df = pl.read_csv(header_line, separator="|", n_rows=0, encoding="utf8-lossy", quote_char=None)
            
            orig_cols = header_df.columns
            col_map = {c.strip(): c for c in orig_cols}
            
            used_clean = [id_col, muni_col]
            if is_hei:
                used_clean.append("CATEGADM")
            if "ANO" in col_map:
                used_clean.append("ANO")
                
            cols_val = []
            for prefix in required_prefixes:
                matched = [c for c in col_map if re.match(rf"^{prefix}\d+$", c)]
                if not matched and is_hei and prefix == "I07":
                    raise ValueError(f"Year {year}: no I07 column found")
                if not matched and is_hei and prefix == "I44" and 2004 <= year <= 2008:
                    raise ValueError(f"Year {year}: no I44 column found")
                if not matched and not is_hei:
                    raise ValueError(f"Year {year}: no enrollment column ({prefix}) found")
                cols_val.extend(matched)
                
            used_clean.extend(cols_val)
            used_clean = list(dict.fromkeys(used_clean))
            used_orig = [col_map[c] for c in used_clean if c in col_map]
            
            content = z.read(member.filename)
            df = pl.read_csv(
                content,
                separator="|",
                infer_schema_length=0,
                encoding="utf8-lossy",
                quote_char=None,
                columns=used_orig
            )
            df = df.rename({orig: clean for orig, clean in zip(used_orig, used_clean)})
            df = df.select(pl.all().str.strip_chars())
            
            if "ANO" in df.columns:
                invalid_year = df.filter(~pl.col("ANO").is_in([str(year)]))
                if len(invalid_year) > 0:
                    raise ValueError(f"Year {year}: ANO differs from the package year. Example: {invalid_year.head(3)}")
            
            invalid_flags = df.select([
                (pl.col(c).is_not_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).any().alias(c)
                for c in cols_val
            ]).to_dicts()[0]
            
            for c, is_invalid in invalid_flags.items():
                if is_invalid:
                    bad_row = df.filter(pl.col(c).is_not_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).row(0, named=True)
                    raise ValueError(f"Year {year}: non-integer or negative value in {c}. Example IES/MASCARA: {bad_row[id_col]}")
            
            exprs = [pl.col(c).fill_null("0").replace("", "0").cast(pl.Int64).alias(c) for c in cols_val]
            exprs.extend([pl.col(c) for c in df.columns if c not in cols_val])
            
            df_casted = df.select(exprs)
                        
            return df_casted, cols_val
            
        col_muni_course = "CODMUNIC_CURSO" if year in (2007, 2008) else "CODMUNICCURSO"
        
        df_grad, cols_grad = read_file(cand_grad[0], id_col, col_muni_course, ["C042"])
        df_seq, cols_seq = read_file(cand_seq[0], id_col, col_muni_course, ["C281"])
        
        if 2004 <= year <= 2008:
            df_hei, cols_hei = read_file(cand_hei[0], id_col, "CODMUNIC", ["I44"], is_hei=True)
        else:
            df_hei, cols_hei = read_file(cand_hei[0], id_col, "CODMUNIC", ["I07", "I11"], is_hei=True)
            
        df_hei = df_hei.with_columns(pl.col(id_col).str.replace(r"^0+", "", n=-1).alias("CO_IES"))
        
        hei_counts = df_hei.group_by("CO_IES").len()
        repeated_hei = hei_counts.filter(pl.col("len") > 1)
        if len(repeated_hei) > 0:
            raise ValueError(f"Year {year}: repeated identifier in INSTITUICAO.CSV. Example: {repeated_hei.head(3)}")
            
        cat_map = {
            "FEDERAL": "federal", 
            "ESTADUAL": "state", 
            "MUNICIPAL": "municipal", 
            "PRIVADA": "private"
        }
        
        invalid_cat = df_hei.filter(~pl.col("CATEGADM").is_in(cat_map.keys()) | pl.col("CATEGADM").is_null())
        if len(invalid_cat) > 0:
            raise ValueError(f"Year {year}: CATEGADM outside the list. Example: {invalid_cat.head(3)}")
            
        df_hei = df_hei.with_columns(pl.col("CATEGADM").replace(cat_map).alias("category"))
        
        if 2004 <= year <= 2008:
            df_hei = df_hei.with_columns(pl.sum_horizontal(cols_hei).alias("QT_DOC_EXE_CAST"))
        else:
            cols_07 = [c for c in cols_hei if c.startswith("I07")]
            cols_11 = [c for c in cols_hei if c.startswith("I11")]
            sum_07 = pl.sum_horizontal(cols_07) if cols_07 else pl.lit(0)
            sum_11 = pl.sum_horizontal(cols_11) if cols_11 else pl.lit(0)
            df_hei = df_hei.with_columns((sum_07 - sum_11).alias("QT_DOC_EXE_CAST"))
            
            invalid_doc = df_hei.filter(pl.col("QT_DOC_EXE_CAST") < 0)
            if len(invalid_doc) > 0:
                raise ValueError(f"Year {year}: more teachers on leave than the total. Example: {invalid_doc.head(3)}")
                
        df_hei = df_hei.with_columns(
            pl.when(pl.col("CODMUNIC").str.len_chars() == 12)
            .then(pl.col("CODMUNIC").str.slice(0, 2) + pl.col("CODMUNIC").str.slice(7, 5))
            .otherwise(pl.col("CODMUNIC"))
            .alias("CO_MUNICIPIO_IES")
        )
        
        df_grad = df_grad.with_columns(pl.col(id_col).str.replace(r"^0+", "", n=-1).alias("CO_IES"))
        df_grad = df_grad.with_columns(
            pl.when(pl.col(col_muni_course).str.len_chars() == 12)
            .then(pl.col(col_muni_course).str.slice(0, 2) + pl.col(col_muni_course).str.slice(7, 5))
            .otherwise(pl.col(col_muni_course))
            .alias("CO_MUNICIPIO")
        )
        df_grad = df_grad.with_columns(pl.sum_horizontal(cols_grad).alias("QT_MAT"))
        
        df_seq = df_seq.with_columns(pl.col(id_col).str.replace(r"^0+", "", n=-1).alias("CO_IES"))
        df_seq = df_seq.with_columns(
            pl.when(pl.col(col_muni_course).str.len_chars() == 12)
            .then(pl.col(col_muni_course).str.slice(0, 2) + pl.col(col_muni_course).str.slice(7, 5))
            .otherwise(pl.col(col_muni_course))
            .alias("CO_MUNICIPIO")
        )
        df_seq = df_seq.with_columns(pl.sum_horizontal(cols_seq).alias("QT_MAT"))
        
        df_courses = pl.concat([
            df_grad.select(["CO_MUNICIPIO", "CO_IES", "QT_MAT"]),
            df_seq.select(["CO_MUNICIPIO", "CO_IES", "QT_MAT"])
        ])
        
        df_courses = df_courses.join(df_hei.select(["CO_IES", "category"]), on="CO_IES", how="left")
        missing = df_courses.filter(pl.col("category").is_null())
        if len(missing) > 0:
            raise ValueError(f"Year {year}: course of an institution that is not in INSTITUICAO.CSV. Example: {missing.head(3)}")
            
        hei_with_courses = df_courses.select("CO_IES").unique()
        on_campus_hei_list = hei_with_courses["CO_IES"].to_list()
        df_hei = df_hei.filter(pl.col("CO_IES").is_in(on_campus_hei_list))
        
        invalid_muni_courses = df_courses.filter(~pl.col("CO_MUNICIPIO").is_in(valid_municipalities) | pl.col("CO_MUNICIPIO").is_null())
        if len(invalid_muni_courses) > 0:
             raise ValueError(f"Year {year}: invalid or null municipalities in the courses table. Example: {invalid_muni_courses.head(3)}")
             
        invalid_muni_hei = df_hei.filter(~pl.col("CO_MUNICIPIO_IES").is_in(valid_municipalities) | pl.col("CO_MUNICIPIO_IES").is_null())
        if len(invalid_muni_hei) > 0:
             raise ValueError(f"Year {year}: invalid or null municipalities in the HEI table. Example: {invalid_muni_hei.head(3)}")
             
        df_courses = df_courses.select(["CO_MUNICIPIO", "CO_IES", "category", "QT_MAT"])
        df_hei = df_hei.select(["CO_IES", "CO_MUNICIPIO_IES", "category", "QT_DOC_EXE_CAST"])
        
        return df_courses, df_hei

def read_current_year(folder: Path, year: int, valid_municipalities: set[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    zip_path = folder / f"higher-education-census/higher-education-census_{year}.zip"
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        cand_courses = [info for info in z.infolist() if 'cadastro_cursos' in info.filename.lower() and info.filename.lower().endswith('.csv')]
        if len(cand_courses) != 1:
            raise ValueError(f"Year {year}: expected exactly 1 CSV file of CADASTRO_CURSOS in the ZIP, found {len(cand_courses)}")
        
        cand_hei = [info for info in z.infolist() if '_ies_' in info.filename.lower() and info.filename.lower().endswith('.csv')]
        if len(cand_hei) != 1:
            raise ValueError(f"Year {year}: expected exactly 1 CSV file of HEI in the ZIP, found {len(cand_hei)}")
            
        member_courses = cand_courses[0]
        member_hei = cand_hei[0]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extract(member_courses, tmpdir)
            file_courses = Path(tmpdir) / member_courses.filename
            
            z.extract(member_hei, tmpdir)
            file_hei = Path(tmpdir) / member_hei.filename
            
            # Courses
            columns_courses = ["CO_MUNICIPIO", "CO_IES", "TP_MODALIDADE_ENSINO", "TP_CATEGORIA_ADMINISTRATIVA", "QT_MAT"]
            df_courses = pl.read_csv(
                file_courses,
                separator=";",
                encoding="utf8-lossy",
                infer_schema_length=0,
                columns=columns_courses,
                schema_overrides={"CO_MUNICIPIO": pl.Utf8, "CO_IES": pl.Utf8, "TP_MODALIDADE_ENSINO": pl.Utf8, "TP_CATEGORIA_ADMINISTRATIVA": pl.Utf8, "QT_MAT": pl.Utf8}
            )
            
            # IES
            col_teachers = "QT_DOCENTE_EXE" if year == 2009 else "QT_DOC_EXE"
            columns_hei = ["CO_IES", "CO_MUNICIPIO_IES", "TP_CATEGORIA_ADMINISTRATIVA", col_teachers]
            df_hei = pl.read_csv(
                file_hei,
                separator=";",
                encoding="utf8-lossy",
                infer_schema_length=0,
                columns=columns_hei,
                schema_overrides={"CO_IES": pl.Utf8, "CO_MUNICIPIO_IES": pl.Utf8, "TP_CATEGORIA_ADMINISTRATIVA": pl.Utf8, col_teachers: pl.Utf8}
            )
            
            # Filter in-person courses
            df_courses = df_courses.filter(pl.col("TP_MODALIDADE_ENSINO") == "1")
            
            # Category mapping
            cat_map = {
                "1": "federal", 
                "2": "state", 
                "3": "municipal", 
                "4": "private", 
                "5": "private", 
                "6": "private", 
                "8": "private", 
                "9": "private", 
                "7": "special"
            }
            
            for name, df, muni_col in [("courses", df_courses, "CO_MUNICIPIO"), ("IES", df_hei, "CO_MUNICIPIO_IES")]:
                invalid_cat = df.filter(~pl.col("TP_CATEGORIA_ADMINISTRATIVA").is_in(cat_map.keys()) | pl.col("TP_CATEGORIA_ADMINISTRATIVA").is_null())
                if len(invalid_cat) > 0:
                    raise ValueError(f"Year {year}: invalid values in TP_CATEGORIA_ADMINISTRATIVA in the {name} table. Example: {invalid_cat.head(3)}")
                
                if name == "courses":
                    invalid_muni = df.filter(~pl.col(muni_col).is_in(valid_municipalities) | pl.col(muni_col).is_null())
                    if len(invalid_muni) > 0:
                         raise ValueError(f"Year {year}: invalid or null municipalities in {muni_col} in the {name} table. Example: {invalid_muni.head(3)}")
            
            df_courses = df_courses.with_columns(
                pl.col("TP_CATEGORIA_ADMINISTRATIVA").replace(cat_map).alias("category")
            )
            df_hei = df_hei.with_columns(
                pl.col("TP_CATEGORIA_ADMINISTRATIVA").replace(cat_map).alias("category")
            )
            
            # Validate and convert qt_mat and qt_docentes
            for name, df, col_q in [("courses", df_courses, "QT_MAT"), ("IES", df_hei, col_teachers)]:
                invalid = df.filter(~pl.col(col_q).str.contains(r"^\d+$") | pl.col(col_q).is_null())
                if len(invalid) > 0:
                    raise ValueError(f"Year {year}: non-integer, negative or empty values in column {col_q} of the {name} table. Example: {invalid.head(3)}")
            
            df_courses = df_courses.with_columns(pl.col("QT_MAT").cast(pl.Int64))
            df_hei = df_hei.with_columns(pl.col(col_teachers).cast(pl.Int64).alias("QT_DOC_EXE_CAST"))
            
            # Verify integrity IES <-> Courses
            hei_with_courses = df_courses.select(["CO_IES", "category"]).unique()
            hei_registry = df_hei.select(["CO_IES", "category"]).unique()
            
            join_hei = hei_with_courses.join(hei_registry, on="CO_IES", how="left", suffix="_registry")
            
            missing = join_hei.filter(pl.col("category_registry").is_null())
            if len(missing) > 0:
                raise ValueError(f"Year {year}: institution with an on-campus course missing from the institutions table. Example: {missing.head(3)}")
                
            divergent = join_hei.filter(pl.col("category") != pl.col("category_registry"))
            if len(divergent) > 0:
                raise ValueError(f"Year {year}: institution with an on-campus course with a different category in the institutions table. Example: {divergent.head(3)}")
            
            # Filter only in-person IES
            on_campus_hei_list = hei_with_courses["CO_IES"].to_list()
            df_hei_on_campus = df_hei.filter(pl.col("CO_IES").is_in(on_campus_hei_list))
            
            # Validate IES municipality code here (only for in-person IES)
            invalid_muni_hei = df_hei_on_campus.filter(~pl.col("CO_MUNICIPIO_IES").is_in(valid_municipalities) | pl.col("CO_MUNICIPIO_IES").is_null())
            if len(invalid_muni_hei) > 0:
                 raise ValueError(f"Year {year}: invalid or null municipalities in CO_MUNICIPIO_IES in the HEI table. Example: {invalid_muni_hei.head(3)}")
            
            return df_courses, df_hei_on_campus

def aggregate(df_courses: pl.DataFrame, df_hei_on_campus: pl.DataFrame, year: int) -> pl.DataFrame:
    # Courses aggregation
    agg_courses = (
        df_courses
        .rename({"CO_MUNICIPIO": "municipality_code"})
        .group_by(["municipality_code", "category"])
        .agg([
            pl.col("CO_IES").n_unique().cast(pl.Int64).alias("institutions"),
            pl.col("QT_MAT").sum().cast(pl.Int64).alias("enrollments")
        ])
    )
    
    # IES aggregation
    agg_hei = (
        df_hei_on_campus
        .rename({"CO_MUNICIPIO_IES": "municipality_code"})
        .group_by(["municipality_code", "category"])
        .agg([
            pl.col("CO_IES").n_unique().cast(pl.Int64).alias("hq_institutions"),
            pl.col("QT_DOC_EXE_CAST").sum().cast(pl.Int64).alias("hq_teachers")
        ])
    )
    
    # Full outer join
    res = agg_courses.join(agg_hei, on=["municipality_code", "category"], how="full", coalesce=True)
    
    # Fill nulls with zero where applicable
    res = res.with_columns([
        pl.col("institutions").fill_null(0).cast(pl.Int64),
        pl.col("enrollments").fill_null(0).cast(pl.Int64),
        pl.col("hq_institutions").fill_null(0).cast(pl.Int64),
        pl.col("hq_teachers").fill_null(0).cast(pl.Int64),
    ])
    
    res = res.with_columns(pl.lit(year).cast(pl.Int16).alias("year"))
    
    return res

def harmonize(folder: Path | str, municipalities: pl.DataFrame) -> pl.DataFrame:
    folder = Path(folder)
    valid_municipalities = set(municipalities["municipality_code"].to_list())
    
    dfs = []
    for year in LEGACY_YEARS:
        df_courses, df_hei = read_legacy_year(folder, year, valid_municipalities)
        df_year = aggregate(df_courses, df_hei, year)
        dfs.append(df_year)
        
    for year in CURRENT_YEARS:
        df_courses, df_hei = read_current_year(folder, year, valid_municipalities)
        df_year = aggregate(df_courses, df_hei, year)
        dfs.append(df_year)
        
    df_final = pl.concat(dfs)
    df_final = df_final.sort(["municipality_code", "year", "category"])
    
    col_order = ["municipality_code", "year", "category", "institutions", "enrollments", "hq_institutions", "hq_teachers"]
    df_final = df_final.select(col_order)
    
    return df_final
