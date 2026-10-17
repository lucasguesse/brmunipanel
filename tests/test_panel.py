
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from brmunipanel.tesouro import revenue

from brmunipanel.panel import (
    build_municipalities,
    build_expenditure,
    build_revenue,
    build_longitudinal_table,
    build_neighboring,
    consolidate_education,
)

def test_build_municipalities():
    municipalities = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "municipality_name": ["A", "B"],
        "state_code": [1, 2],
        "state_abbr": ["UF", "UF"],
        "state_name": ["Estado", "Estado"],
        "intermediate_region_name": ["RI", "RI"],
        "immediate_region_name": ["RI", "RI"],
        "international_border": [0, 1],
        "coastal": [1, 0],
        "area_km2": [10.0, 20.0],
        "latitude": [-10.0, -20.0],
        "longitude": [-30.0, -40.0],
    })
    
    output = build_municipalities(municipalities)
    assert_frame_equal(output, municipalities)

def test_build_municipalities_errors():
    municipalities_dup = pl.DataFrame({"municipality_code": ["1", "1"]})
    with pytest.raises(ValueError, match="municipalities:.*repeated keys"):
        build_municipalities(municipalities_dup)
        
    municipalities_missing = pl.DataFrame({
        "municipality_code": ["1"],
        "municipality_name": ["A"],
    })
    with pytest.raises(ValueError, match="Missing column state_code in municipalities"):
        build_municipalities(municipalities_missing)

def test_build_expenditure():
    finbra = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "exp_01_legislative": [10.0],
        "exp_intra_budgetary": [5.0]
    })
    siconfi = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2013], dtype=pl.Int16),
        "exp_01_legislative": [12.0],
        "exp_intra_budgetary": [6.0]
    })
    
    output = build_expenditure(finbra, siconfi)
    
    expected = pl.DataFrame({
        "municipality_code": ["1", "1"],
        "year": pl.Series([2010, 2013], dtype=pl.Int16),
        "exp_legislative": [10.0, 12.0],
        "exp_intra_budgetary": [5.0, 6.0]
    })
    
    assert_frame_equal(output, expected)

def test_build_expenditure_errors():
    finbra = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "v": [10.0],
    })
    siconfi = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "v": [12.0],
    })
    with pytest.raises(ValueError, match="cases of the same municipality and year"):
        build_expenditure(finbra, siconfi)

def _revenue_rows(code, year, start):
    return pl.DataFrame(
        {"municipality_code": [code], "year": [year], **{c: [float(start + i)] for i, c in enumerate(revenue.REVENUE_COLUMNS)}},
        schema=revenue.SCHEMA,
    )

def test_build_revenue():
    finbra = pl.concat([_revenue_rows("2", 2010, 1), _revenue_rows("1", 2006, 10)])
    siconfi = _revenue_rows("1", 2013, 100)

    output = build_revenue(finbra, siconfi)

    assert output.schema == revenue.SCHEMA
    assert output.select(["municipality_code", "year"]).rows() == [("1", 2006), ("1", 2013), ("2", 2010)]
    assert output["rev_current_gross"].to_list() == [10.0, 100.0, 1.0]
    assert output["rev_icms_share"].to_list() == [17.0, 107.0, 8.0]

def test_build_revenue_errors():
    finbra = _revenue_rows("1", 2010, 1)
    with pytest.raises(ValueError, match="cases of the same municipality and year"):
        build_revenue(finbra, _revenue_rows("1", 2010, 5))
    with pytest.raises(ValueError, match="siconfi does not follow the revenue schema"):
        build_revenue(finbra, _revenue_rows("1", 2013, 5).drop("rev_fees"))
    with pytest.raises(ValueError, match="finbra does not follow the revenue schema"):
        build_revenue(finbra.with_columns(pl.col("year").cast(pl.Int32)), _revenue_rows("1", 2013, 5))

def test_build_longitudinal_table():
    municipalities = pl.DataFrame({"municipality_code": ["1", "2"]})
    years = range(2010, 2012)
    
    f1 = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "year": pl.Series([2010, 2011], dtype=pl.Int16),
        "v1": [1.0, 2.0],
    })
    f2 = pl.DataFrame({
        "municipality_code": ["2", "1", "1"],
        "year": pl.Series([2011, 2010, 2011], dtype=pl.Int16),
        "v2": ["A", "B", None],
    })
    
    output = build_longitudinal_table(municipalities, [f1, f2], years=years, table_name="test")
    
    assert output.columns == ["municipality_code", "year", "v1", "v2"]
    assert len(output) == 4
    
    expected = pl.DataFrame({
        "municipality_code": ["1", "1", "2", "2"],
        "year": pl.Series([2010, 2011, 2010, 2011], dtype=pl.Int16),
        "v1": [1.0, None, None, 2.0],
        "v2": ["B", None, None, "A"],
    })
    assert_frame_equal(output, expected)

    panel_f1 = output.join(f1.select(["municipality_code", "year"]), on=["municipality_code", "year"], how="inner").select(["municipality_code", "year", "v1"])
    assert_frame_equal(panel_f1.sort(["municipality_code", "year"]), f1.sort(["municipality_code", "year"]))

    panel_f2 = output.join(f2.select(["municipality_code", "year"]), on=["municipality_code", "year"], how="inner").select(["municipality_code", "year", "v2"])
    assert_frame_equal(panel_f2.sort(["municipality_code", "year"]), f2.sort(["municipality_code", "year"]))

def test_build_longitudinal_table_errors():
    municipalities = pl.DataFrame({"municipality_code": ["1"]})
    years = range(2010, 2012)
    
    f = pl.DataFrame({"municipality_code": ["2"], "year": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="test .*codes not in the"):
        build_longitudinal_table(municipalities, [f], years=years, table_name="test")
        
    f = pl.DataFrame({"municipality_code": ["1"], "year": pl.Series([2012], dtype=pl.Int16), "v": [1]})
    with pytest.raises(ValueError, match="test .*years outside the allowed window"):
        build_longitudinal_table(municipalities, [f], years=years, table_name="test")
        
    f = pl.DataFrame({"municipality_code": ["1", "1"], "year": pl.Series([2010, 2010], dtype=pl.Int16), "v": [1, 2]})
    with pytest.raises(ValueError, match="test .*repeated keys"):
        build_longitudinal_table(municipalities, [f], years=years, table_name="test")
        
    f1 = pl.DataFrame({"municipality_code": ["1"], "year": pl.Series([2010], dtype=pl.Int16), "v": [1]})
    f2 = pl.DataFrame({"municipality_code": ["1"], "year": pl.Series([2010], dtype=pl.Int16), "v": [2]})
    with pytest.raises(ValueError, match="test .*column with a name another source"):
        build_longitudinal_table(municipalities, [f1, f2], years=years, table_name="test")
        
def test_build_neighboring():
    municipalities = pl.DataFrame({"municipality_code": ["1", "2"]})
    lims = pl.DataFrame({
        "municipality_code": ["2", "1"],
        "neighbor_municipality_code": ["1", "2"],
    })
    output = build_neighboring(municipalities, lims)
    expected = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "neighbor_municipality_code": ["2", "1"],
    })
    assert_frame_equal(output, expected)

def test_build_neighboring_errors():
    municipalities = pl.DataFrame({"municipality_code": ["1", "2"]})
    lims = pl.DataFrame({"municipality_code": ["1", "1"], "neighbor_municipality_code": ["2", "2"]})
    with pytest.raises(ValueError, match="neighboring:.*repeated pairs"):
        build_neighboring(municipalities, lims)
    lims = pl.DataFrame({"municipality_code": ["3"], "neighbor_municipality_code": ["1"]})
    with pytest.raises(ValueError, match="neighboring:.*codes not in"):
        build_neighboring(municipalities, lims)

def test_consolidate_education():
    school_census = pl.DataFrame({
        "municipality_code": ["1", "1", "3", "5"],
        "year": pl.Series([2010, 2010, 2010, 2010], dtype=pl.Int16),
        "admin_dependency": ["Estadual", "Municipal", "Estadual", "Municipal"],
        "location": ["Urbana", "Rural", "Urbana", "Urbana"],
        "schools": [10, 20, None, 10],
        "enroll_early_childhood": [100, 200, None, 100],
        "enroll_elementary": [1000, 2000, None, 1000],
        "enroll_secondary": [100, 200, None, 100],
        "teachers_basic_edu": [50, 100, None, 50],
    })
    higher_education_census = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "year": pl.Series([2010, 2010], dtype=pl.Int16),
        "category": ["A", "A"],
        "institutions": [1, 2],
        "enrollments": [1000, 2000],
    })
    ideb = pl.DataFrame({
        "municipality_code": ["2", "4"],
        "year": pl.Series([2010, 2010], dtype=pl.Int16),
        "ideb_early_years_public": [5.5, None],
        "ideb_final_years_public": [4.5, None],
        "ideb_secondary_public": [3.5, None],
    })
    
    output = consolidate_education(school_census, higher_education_census, ideb)
    
    assert len(output) == 4
    assert output.columns == [
        "municipality_code", "year",
        "basic_edu_schools", "enroll_early_childhood", "enroll_elementary", "enroll_secondary", "teachers_basic_edu",
        "higher_edu_institutions", "enroll_higher_edu",
        "ideb_early_years_public", "ideb_final_years_public", "ideb_secondary_public"
    ]
    
    assert output.filter(pl.col("municipality_code") == "1")["basic_edu_schools"][0] == 30
    assert output.filter(pl.col("municipality_code") == "1")["higher_edu_institutions"][0] == 1
    
    assert output.filter(pl.col("municipality_code") == "2")["higher_edu_institutions"][0] == 2
    assert output.filter(pl.col("municipality_code") == "2")["basic_edu_schools"].is_null()[0]
    
    assert output.filter(pl.col("municipality_code") == "3")["basic_edu_schools"].is_null()[0]

    assert len(output.filter(pl.col("municipality_code") == "4")) == 0

    assert output.filter(pl.col("municipality_code") == "5")["basic_edu_schools"][0] == 10

def test_consolidate_education_errors():
    school_census = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "admin_dependency": ["Estadual"], "location": ["Urbana"],
        "schools": [10], "enroll_early_childhood": [100], "enroll_elementary": [1000], "enroll_secondary": [100], "teachers_basic_edu": [50]
    })
    higher_education_census = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "category": ["A"], "institutions": [1], "enrollments": [1000]
    })
    
    ideb = pl.DataFrame({
        "municipality_code": ["1"],
        "year": pl.Series([2010], dtype=pl.Int16),
        "ideb_early_years_public": [5.5], "ideb_final_years_public": [4.5], "ideb_secondary_public": [11.0]
    })
    with pytest.raises(ValueError, match="ideb: values outside"):
        consolidate_education(school_census, higher_education_census, ideb)

    ideb_dup = pl.DataFrame({
        "municipality_code": ["1", "1"],
        "year": pl.Series([2010, 2010], dtype=pl.Int16),
        "ideb_early_years_public": [5.5, 5.5], "ideb_final_years_public": [4.5, 4.5], "ideb_secondary_public": [3.5, 3.5]
    })
    with pytest.raises(ValueError, match="Duplicate keys in the ideb input"):
        consolidate_education(school_census, higher_education_census, ideb_dup)

    school_null = pl.DataFrame({
        "municipality_code": pl.Series([None], dtype=pl.String),
        "year": pl.Series([2010], dtype=pl.Int16),
        "admin_dependency": ["Estadual"], "location": ["Urbana"],
        "schools": [10], "enroll_early_childhood": [100], "enroll_elementary": [1000], "enroll_secondary": [100], "teachers_basic_edu": [50]
    })
    with pytest.raises(ValueError, match="Null keys in the school_census input"):
        consolidate_education(school_null, higher_education_census, ideb_dup)
        
    school_dup = pl.DataFrame({
        "municipality_code": ["1", "1"],
        "year": pl.Series([2010, 2010], dtype=pl.Int16),
        "admin_dependency": ["Estadual", "Estadual"], "location": ["Urbana", "Urbana"],
        "schools": [10, 20], "enroll_early_childhood": [100, 100], "enroll_elementary": [1000, 1000], "enroll_secondary": [100, 100], "teachers_basic_edu": [50, 50]
    })
    with pytest.raises(ValueError, match="school_census: duplicate dimension keys before aggregation"):
        consolidate_education(school_dup, higher_education_census, ideb)
        
    school_bad_type = pl.DataFrame({
        "municipality_code": [1],
        "year": pl.Series([2010], dtype=pl.Int16),
        "admin_dependency": ["Estadual"], "location": ["Urbana"],
        "schools": [10], "enroll_early_childhood": [100], "enroll_elementary": [1000], "enroll_secondary": [100], "teachers_basic_edu": [50]
    })
    with pytest.raises(ValueError, match="school_census: municipality_code must be String"):
        consolidate_education(school_bad_type, higher_education_census, ideb)
        
    school_bad_year = school_census.with_columns(pl.col("year").cast(pl.Int32))
    with pytest.raises(ValueError, match="school_census: year must be Int16"):
        consolidate_education(school_bad_year, higher_education_census, ideb)
        
    school_bad_measure = school_census.with_columns(pl.col("schools").cast(pl.Float64))
    with pytest.raises(ValueError, match="school_census: schools must be an integer"):
        consolidate_education(school_bad_measure, higher_education_census, ideb)
        
    higher_education_bad_year = higher_education_census.with_columns(pl.col("year").cast(pl.Int64))
    with pytest.raises(ValueError, match="higher_education_census: year must be Int16"):
        consolidate_education(school_census, higher_education_bad_year, ideb)
        
    higher_education_bad_measure = higher_education_census.with_columns(pl.col("institutions").cast(pl.String))
    with pytest.raises(ValueError, match="higher_education_census: institutions must be an integer"):
        consolidate_education(school_census, higher_education_bad_measure, ideb)
        
    ideb_bad_year = ideb.with_columns(pl.col("year").cast(pl.Int32))
    with pytest.raises(ValueError, match="ideb: year must be Int16"):
        consolidate_education(school_census, higher_education_census, ideb_bad_year)
        
    ideb_bad_measure = ideb.with_columns(pl.col("ideb_early_years_public").cast(pl.Int64))
    with pytest.raises(ValueError, match="ideb: ideb_early_years_public must be Float64"):
        consolidate_education(school_census, higher_education_census, ideb_bad_measure)


def test_consolidate_education_filters():
    school_census = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "year": pl.Series([2000, 2010], dtype=pl.Int16),
        "admin_dependency": ["Estadual", "Estadual"],
        "location": ["Urbana", "Urbana"],
        "schools": [10, 10],
        "enroll_early_childhood": [100, 100],
        "enroll_elementary": [1000, 1000],
        "enroll_secondary": [100, 100],
        "teachers_basic_edu": [50, 50],
    })
    higher_education_census = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "year": pl.Series([2000, 2010], dtype=pl.Int16),
        "category": ["A", "A"],
        "institutions": [1, 2],
        "enrollments": [1000, 2000],
    })
    ideb = pl.DataFrame({
        "municipality_code": ["1", "2"],
        "year": pl.Series([2000, 2010], dtype=pl.Int16),
        "ideb_early_years_public": [5.5, 6.0],
        "ideb_final_years_public": [4.5, 5.0],
        "ideb_secondary_public": [3.5, 4.0],
    })
    
    output = consolidate_education(school_census, higher_education_census, ideb)
    
    assert len(output.filter(pl.col("year") == 2000).drop_nulls(subset=["higher_edu_institutions"])) == 0
    assert len(output.filter(pl.col("year") == 2000).drop_nulls(subset=["ideb_early_years_public"])) == 0
    
    assert output.filter(pl.col("year") == 2010)["higher_edu_institutions"][0] == 2
    assert output.filter(pl.col("year") == 2010)["ideb_early_years_public"][0] == 6.0

def test_consolidate_education_aggregation_and_ideb():
    school_census = pl.DataFrame({
        "municipality_code": ["1", "1", "1", "2"],
        "year": pl.Series([2008, 2010, 2010, 2010], dtype=pl.Int16),
        "admin_dependency": ["M", "E", "M", "E"],
        "location": ["U", "U", "U", "U"],
        "schools": [10, 20, 30, 40],
        "enroll_early_childhood": [1, 2, 3, 4],
        "enroll_elementary": [1, 2, 3, 4],
        "enroll_secondary": [1, 2, 3, 4],
        "teachers_basic_edu": [1, 2, 3, 4],
    })
    
    # Censo higher_education has multiple categories for the same code/year
    higher_education_census = pl.DataFrame({
        "municipality_code": ["1", "1", "2"],
        "year": pl.Series([2010, 2010, 2010], dtype=pl.Int16),
        "category": ["Pública", "Privada", "Privada"],
        "institutions": [1, 2, 5],
        "enrollments": [1000, 2000, 5000],
    })
    
    # IDEB: 2008, even year, enters with all three stages null, and 2009 enters with value
    ideb = pl.DataFrame({
        "municipality_code": ["1", "1"],
        "year": pl.Series([2008, 2009], dtype=pl.Int16),
        "ideb_early_years_public": [None, 6.0],
        "ideb_final_years_public": [None, 5.0],
        "ideb_secondary_public": [None, 4.0],
    })
    
    output = consolidate_education(school_census, higher_education_census, ideb)
    
    # Assert aggregation for higher_education
    higher_muni1 = output.filter((pl.col("municipality_code") == "1") & (pl.col("year") == 2010))
    assert higher_muni1["higher_edu_institutions"][0] == 3
    assert higher_muni1["enroll_higher_edu"][0] == 3000
    
    # Assert even year null for IDEB (2008)
    muni1_2008 = output.filter((pl.col("municipality_code") == "1") & (pl.col("year") == 2008))
    assert muni1_2008["ideb_early_years_public"].is_null()[0]
    
    # Assert odd year IDEB separated correctly
    muni1_2009 = output.filter((pl.col("municipality_code") == "1") & (pl.col("year") == 2009))
    assert muni1_2009["ideb_early_years_public"][0] == 6.0
    assert muni1_2009["ideb_final_years_public"][0] == 5.0
    assert muni1_2009["ideb_secondary_public"][0] == 4.0

