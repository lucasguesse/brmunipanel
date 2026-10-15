import pytest
import polars as pl
from brmunipanel.metadata import dictionary, audit

def test_compute_statistics_types_nulls_and_empty():
    df = pl.DataFrame({
        "num": [1, 2, None, 4],
        "txt": ["a", "b", "a", None],
        "bool_col": [True, False, None, True],
        "empty": [None, None, None, None]
    }, schema={
        "num": pl.Int64,
        "txt": pl.Utf8,
        "bool_col": pl.Boolean,
        "empty": pl.Float64
    })
    
    stats_num = dictionary.compute_statistics(df, "num")
    assert stats_num["nulls"] == 1
    assert stats_num["null_percentage"] == 25.0
    assert stats_num["min"] == "1"
    assert stats_num["max"] == "4"
    assert stats_num["domain"] == ""
    
    stats_txt = dictionary.compute_statistics(df, "txt")
    assert stats_txt["nulls"] == 1
    assert stats_txt["min"] == ""
    assert stats_txt["max"] == ""
    assert stats_txt["domain"] == "a, b"
    
    stats_bool = dictionary.compute_statistics(df, "bool_col")
    assert stats_bool["nulls"] == 1
    assert stats_bool["min"] == ""
    assert stats_bool["max"] == ""
    assert stats_bool["domain"] == "false, true"
    
    empty_stats = dictionary.compute_statistics(df, "empty")
    assert empty_stats["nulls"] == 4
    assert empty_stats["null_percentage"] == 100.0
    assert empty_stats["min"] == ""
    assert empty_stats["max"] == ""
    assert empty_stats["domain"] == ""

def test_domain_cardinality():
    # <= 35 should show, > 35 should hide
    df_small = pl.DataFrame({"txt": [str(i) for i in range(35)]}, schema={"txt": pl.Utf8})
    df_large = pl.DataFrame({"txt": [str(i) for i in range(36)]}, schema={"txt": pl.Utf8})
    
    stats_small = dictionary.compute_statistics(df_small, "txt")
    assert stats_small["domain"] != ""
    
    stats_large = dictionary.compute_statistics(df_large, "txt")
    assert stats_large["domain"] == ""

def test_build_dictionary():
    df = pl.DataFrame({
        "code": ["1", "2"],
        "val": [10, 20]
    }, schema={"code": pl.Utf8, "val": pl.Int64})
    
    meta = {
        "code": {"description_pt": "Codigo", "description_en": "Code", "unit": "ID", "source": "IBGE", "period": "2023", "methodological_note": ""},
        "val": {"description_pt": "Valor", "description_en": "Value", "unit": "R$", "source": "N/A", "period": "2023", "methodological_note": ""}
    }
    
    dict_df = dictionary.build_table_dictionary(df, "test", meta, ["code"])
    assert dict_df.height == 2
    assert dict_df["key"][0] == "Yes"
    assert dict_df["key"][1] == "No"
    
def test_missing_metadata_orphans():
    df = pl.DataFrame({"code": ["1"], "missing": [10]})
    meta = {"code": {}}
    
    with pytest.raises(ValueError, match="Missing metadata for column 'missing'"):
        dictionary.build_table_dictionary(df, "test", meta, ["code"])

def test_empty_table():
    df = pl.DataFrame(schema={"code": pl.Utf8, "val": pl.Int64})
    meta = {
        "code": {"description_pt": "Codigo"},
        "val": {"description_pt": "Valor"}
    }
    dict_df = dictionary.build_table_dictionary(df, "test", meta, ["code"])
    assert dict_df.height == 2
    assert dict_df["nulls"][0] == 0
    assert dict_df["null_percentage"][0] == 0.0

def test_audit_summary():
    df = pl.DataFrame({"code": ["1", "2", "2"], "val": [10, None, 20], "year": [2000, 2001, 2001]})
    res = audit.audit_summary_table(df, "test", ["code", "year"])
    assert res["rows"] == 3
    assert res["columns"] == 3
    assert res["key_duplicates"] == 1
    assert res["min_year"] == "2000"
    assert res["max_year"] == "2001"
    assert res["null_cells"] == 1
