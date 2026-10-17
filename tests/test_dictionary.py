import json
from pathlib import Path

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

def test_build_dictionary_bilingual_fields():
    df = pl.DataFrame({"code": ["1", "2"], "val": [10, None]}, schema={"code": pl.Utf8, "val": pl.Int64})
    meta = {
        "code": {
            "description_pt": "Código", "description_en": "Code", "unit_pt": "Código", "unit_en": "Code",
            "source_pt": "IBGE", "source_en": "IBGE", "period": "2023",
            "methodological_note_pt": "Código de 7 dígitos.", "methodological_note_en": "Seven-digit code.",
        },
        "val": {
            "description_pt": "Valor", "description_en": "Value", "unit_pt": "Mil Reais", "unit_en": "Thousand reais (BRL)",
            "source_pt": "Tesouro Nacional", "source_en": "National Treasury", "period": "2007-2023",
            "methodological_note_pt": "Só anos ímpares.", "methodological_note_en": "Odd years only.",
        },
    }
    dict_df = dictionary.build_table_dictionary(df, "test", meta, ["code"])
    assert dict_df.columns == [
        "table", "variable", "type", "description_en", "description_pt", "unit_en", "unit_pt", "source_en",
        "source_pt", "period", "key", "nulls", "null_percentage", "min", "max", "domain", "methodological_note_en",
        "methodological_note_pt",
    ]
    row = dict_df.row(1, named=True)
    assert row["unit_en"] == "Thousand reais (BRL)"
    assert row["unit_pt"] == "Mil Reais"
    assert row["source_en"] == "National Treasury"
    assert row["source_pt"] == "Tesouro Nacional"
    assert row["period"] == "2007-2023"
    assert row["methodological_note_en"] == "Odd years only."
    assert row["methodological_note_pt"] == "Só anos ímpares."
    assert row["nulls"] == 1
    assert row["null_percentage"] == 50.0

def test_variables_json_processed_is_bilingual():
    path = Path(dictionary.__file__).with_name("variables.json")
    meta = json.loads(path.read_text(encoding="utf-8"))
    fields = {
        "description_pt", "description_en", "unit_pt", "unit_en", "source_pt", "source_en", "period",
        "methodological_note_pt", "methodological_note_en",
    }
    count = 0
    for table, variables in meta["processed"].items():
        for name, variable_meta in variables.items():
            count += 1
            assert set(variable_meta) == fields, (table, name)
            for field in ("description_en", "unit_en", "source_en", "period"):
                assert variable_meta[field], (table, name, field)
            if variable_meta["methodological_note_pt"]:
                assert variable_meta["methodological_note_en"], (table, name)
    assert count == 87
    education = meta["processed"]["education"]
    assert education["ideb_early_years_public"]["period"] == "2007-2023"
    assert education["ideb_final_years_public"]["period"] == "2007-2023"
    assert education["ideb_secondary_public"]["period"] == "2017-2023"
    assert "2007, 2010, 2022" in meta["processed"]["socioeconomic"]["population"]["methodological_note_en"]
    assert "3544004" in education["higher_edu_institutions"]["methodological_note_en"]
    for stage in meta.values():
        for variables in stage.values():
            for variable_meta in variables.values():
                assert not {"unit", "source", "methodological_note"} & set(variable_meta)
