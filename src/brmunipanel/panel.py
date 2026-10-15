"""Consolidation of the dataset into six tables.

The consolidated dataset has six tables: the central municipalities table, three thematic
longitudinal tables (socioeconomic, public_finance, health), the 
neighboring_municipalities table, and the education table.
No function here fills nulls, removes rows, modifies values, or calculates derived columns.
"""

import re
from typing import Sequence
import polars as pl

PANEL_YEARS = tuple(range(2006, 2024))

def build_municipalities(municipalities: pl.DataFrame) -> pl.DataFrame:
    """Builds the canonical municipalities table, validating uniqueness and ordering by `municipality_code`."""
    if "municipality_code" not in municipalities.columns:
        raise ValueError("Missing municipality_code")
    
    dups_muni = municipalities.filter(municipalities["municipality_code"].is_duplicated())["municipality_code"]
    if not dups_muni.is_empty():
        raise ValueError(f"municipalities: {dups_muni.n_unique()} repeated keys. Examples: {dups_muni.head(3).to_list()}")
        
    cols = [
        "municipality_code", "municipality_name", "state_code", "state_abbr", "state_name",
        "intermediate_region_name", "immediate_region_name", "international_border",
        "coastal", "area_km2", "latitude", "longitude"
    ]
    for c in cols:
        if c not in municipalities.columns:
            raise ValueError(f"Missing column {c} in municipalities")
            
    return municipalities.select(cols).sort("municipality_code")


def build_expenditure(finbra: pl.DataFrame, siconfi: pl.DataFrame) -> pl.DataFrame:
    """Combines FINBRA and SICONFI expenditures, normalizes column names, and sorts by municipality and year."""
    if list(finbra.columns) != list(siconfi.columns):
        raise ValueError(f"Different columns or column order between finbra and siconfi. finbra: {finbra.columns}, siconfi: {siconfi.columns}")
        
    if dict(zip(finbra.columns, finbra.dtypes)) != dict(zip(siconfi.columns, siconfi.dtypes)):
        raise ValueError("Different types between finbra and siconfi")
        
    # Checks if the same municipality and year appear in both
    finbra_keys = set(finbra.select(["municipality_code", "year"]).iter_rows())
    siconfi_keys = set(siconfi.select(["municipality_code", "year"]).iter_rows())
    inter = finbra_keys & siconfi_keys
    if inter:
        raise ValueError(f"{len(inter)} cases of the same municipality and year in both tables. Examples: {list(inter)[:3]}")
        
    output = pl.concat([finbra, siconfi])
    
    # Rename exp_XX_name to exp_name
    rename_map = {}
    for c in output.columns:
        m = re.match(r"exp_\d{2}_(.*)", c)
        if m:
            rename_map[c] = f"exp_{m.group(1)}"
            
    return output.rename(rename_map).sort(["municipality_code", "year"])

def build_longitudinal_table(municipalities: pl.DataFrame, sources: list[pl.DataFrame], years: Sequence[int] = PANEL_YEARS, table_name: str = "longitudinal_table") -> pl.DataFrame:
    """Builds a longitudinal panel on a municipality-year grid by sequentially left-joining source tables."""
    valid_codes = set(municipalities["municipality_code"])
    
    # Grid of municipalities and years
    grade = municipalities.select(["municipality_code"]).join(
        pl.DataFrame({"year": list(years)}).with_columns(pl.col("year").cast(pl.Int16)),
        how="cross"
    )
    
    output = grade
    seen_columns = {"municipality_code", "year"}
    
    for i, source in enumerate(sources):
        if "year" not in source.columns or source["year"].dtype != pl.Int16:
            raise ValueError(f"{table_name} (source {i}): 'year' is not Int16 or is missing")
            
        dups = source.filter(source.select(["municipality_code", "year"]).is_duplicated())
        if not dups.is_empty():
            raise ValueError(f"{table_name} (source {i}): {dups.select(['municipality_code', 'year']).n_unique()} repeated keys. Examples: {dups.head(3).to_dicts()}")
            
        invalid = [c for c in set(source["municipality_code"]) if c not in valid_codes]
        if invalid:
            raise ValueError(f"{table_name} (source {i}): {len(invalid)} codes not in the municipalities table. Examples: {invalid[:3]}")
            
        invalid_years = [a for a in set(source["year"]) if a not in years]
        if invalid_years:
            raise ValueError(f"{table_name} (source {i}): {len(invalid_years)} years outside the allowed window. Examples: {invalid_years[:3]}")
            
        new = set(source.columns) - {"municipality_code", "year"}
        inter = new & seen_columns
        if inter:
            raise ValueError(f"{table_name} (source {i}): column with a name another source already brought: {inter}")
            
        output = output.join(source, on=["municipality_code", "year"], how="left")
        seen_columns.update(new)
        
    return output.sort(["municipality_code", "year"])

def build_neighboring(municipalities: pl.DataFrame, neighboring: pl.DataFrame) -> pl.DataFrame:
    """Validates and sorts the neighboring municipalities adjacency table."""
    dups = neighboring.filter(neighboring.select(["municipality_code", "neighbor_municipality_code"]).is_duplicated())
    if not dups.is_empty():
        raise ValueError(f"neighboring: {dups.select(['municipality_code', 'neighbor_municipality_code']).n_unique()} repeated pairs. Examples: {dups.head(3).to_dicts()}")
        
    valid_codes = set(municipalities["municipality_code"])
    invalid = [c for c in set(neighboring["municipality_code"]) | set(neighboring["neighbor_municipality_code"]) if c not in valid_codes]
    if invalid:
        raise ValueError(f"neighboring: {len(invalid)} codes not in the municipalities table. Examples: {invalid[:3]}")
        
    return neighboring.sort(["municipality_code", "neighbor_municipality_code"])

def consolidate_education(school_census: pl.DataFrame, higher_education_census: pl.DataFrame, ideb: pl.DataFrame) -> pl.DataFrame:
    """Consolidates School Census, Higher Education Census, and IDEB into the education panel table."""
    # Censo Escolar
    school_cols = ["municipality_code", "year", "admin_dependency", "location", "schools", "enroll_early_childhood", "enroll_elementary", "enroll_secondary", "teachers_basic_edu"]
    for c in school_cols:
        if c not in school_census.columns:
            raise ValueError(f"Missing column {c} in school_census")
            
    if school_census["municipality_code"].dtype != pl.String:
        raise ValueError("school_census: municipality_code must be String")
    if school_census["year"].dtype != pl.Int16:
        raise ValueError("school_census: year must be Int16")
    for c in ["schools", "enroll_early_childhood", "enroll_elementary", "enroll_secondary", "teachers_basic_edu"]:
        if not school_census[c].dtype.is_integer():
            raise ValueError(f"school_census: {c} must be an integer")

    if school_census.select(["municipality_code", "year", "admin_dependency", "location"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Null keys in the school_census input")
        
    school_dups = school_census.filter(school_census.select(["municipality_code", "year", "admin_dependency", "location"]).is_duplicated())
    if not school_dups.is_empty():
        raise ValueError("school_census: duplicate dimension keys before aggregation")

    school_aggs = [
        pl.when(pl.col(c).is_not_null().any()).then(pl.col(c).sum()).otherwise(None).alias(c)
        for c in ["schools", "enroll_early_childhood", "enroll_elementary", "enroll_secondary", "teachers_basic_edu"]
    ]
    school = school_census.select(school_cols).group_by(["municipality_code", "year"]).agg(school_aggs).rename({"schools": "basic_edu_schools"})
    for c in ["basic_edu_schools", "enroll_early_childhood", "enroll_elementary", "enroll_secondary", "teachers_basic_edu"]:
        school = school.with_columns(pl.col(c).cast(pl.Int64))
        
    # Censo Superior
    higher_education_cols = ["municipality_code", "year", "category", "institutions", "enrollments"]
    for c in higher_education_cols:
        if c not in higher_education_census.columns:
            raise ValueError(f"Missing column {c} in higher_education_census")
            
    if higher_education_census["municipality_code"].dtype != pl.String:
        raise ValueError("higher_education_census: municipality_code must be String")
    if higher_education_census["year"].dtype != pl.Int16:
        raise ValueError("higher_education_census: year must be Int16")
    for c in ["institutions", "enrollments"]:
        if not higher_education_census[c].dtype.is_integer():
            raise ValueError(f"higher_education_census: {c} must be an integer")

    if higher_education_census.select(["municipality_code", "year", "category"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Null keys in the higher_education_census input")
        
    higher_education_dups = higher_education_census.filter(higher_education_census.select(["municipality_code", "year", "category"]).is_duplicated())
    if not higher_education_dups.is_empty():
        raise ValueError("higher_education_census: duplicate dimension keys before aggregation")

    higher_education = higher_education_census.select(higher_education_cols).filter((pl.col("year") >= 2006) & (pl.col("year") <= 2023))
    higher_education_aggs = [
        pl.when(pl.col(c).is_not_null().any()).then(pl.col(c).sum()).otherwise(None).alias(c)
        for c in ["institutions", "enrollments"]
    ]
    higher_education = higher_education.group_by(["municipality_code", "year"]).agg(higher_education_aggs).rename({"institutions": "higher_edu_institutions", "enrollments": "enroll_higher_edu"})
    for c in ["higher_edu_institutions", "enroll_higher_edu"]:
        higher_education = higher_education.with_columns(pl.col(c).cast(pl.Int64))

    # IDEB
    ideb_cols = ["municipality_code", "year", "ideb_early_years_public", "ideb_final_years_public", "ideb_secondary_public"]
    for c in ideb_cols:
        if c not in ideb.columns:
            raise ValueError(f"Missing column {c} in ideb")
            
    if ideb["municipality_code"].dtype != pl.String:
        raise ValueError("ideb: municipality_code must be String")
    if ideb["year"].dtype != pl.Int16:
        raise ValueError("ideb: year must be Int16")
    for c in ["ideb_early_years_public", "ideb_final_years_public", "ideb_secondary_public"]:
        if ideb[c].dtype != pl.Float64:
            raise ValueError(f"ideb: {c} must be Float64")

    if ideb.select(["municipality_code", "year"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Null keys in the ideb input")
    if not ideb.filter(ideb.select(["municipality_code", "year"]).is_duplicated()).is_empty():
        raise ValueError("Duplicate keys in the ideb input")

    ideb_filtered = ideb.select(ideb_cols).filter((pl.col("year") >= 2006) & (pl.col("year") <= 2023))
    
    # Drop rows where all three IDEB measures are null
    ideb_filtered = ideb_filtered.filter(
        pl.col("ideb_early_years_public").is_not_null() |
        pl.col("ideb_final_years_public").is_not_null() |
        pl.col("ideb_secondary_public").is_not_null()
    )

    for c in ["ideb_early_years_public", "ideb_final_years_public", "ideb_secondary_public"]:
        nulls = ideb_filtered.filter((pl.col(c).is_not_null()) & ((pl.col(c) < 0.0) | (pl.col(c) > 10.0)))
        if not nulls.is_empty():
            raise ValueError(f"ideb: values outside 0-10 in {c}")

    # Join
    output = school.join(higher_education, on=["municipality_code", "year"], how="full", coalesce=True)
    output = output.join(ideb_filtered, on=["municipality_code", "year"], how="full", coalesce=True)
    
    # Validations
    if output.select(["municipality_code", "year"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Null keys in the consolidated education table")
    dups = output.filter(output.select(["municipality_code", "year"]).is_duplicated())
    if not dups.is_empty():
        raise ValueError("education: duplicate keys")
        
    order = [
        "municipality_code", "year",
        "basic_edu_schools", "enroll_early_childhood", "enroll_elementary", "enroll_secondary", "teachers_basic_edu",
        "higher_edu_institutions", "enroll_higher_edu",
        "ideb_early_years_public", "ideb_final_years_public", "ideb_secondary_public"
    ]
    return output.select(order).sort(["municipality_code", "year"])
