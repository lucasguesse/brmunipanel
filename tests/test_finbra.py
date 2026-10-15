import io
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.core import InvalidResponse
from brmunipanel.tesouro import finbra
from brmunipanel.tesouro.expenditure_by_function import PUBLISHED_COLUMNS, FUNCTIONS
from brmunipanel.tesouro.finbra import (
    code_6,
    convert_currency,
    process_table,
    validate_zip,
)

DATA = Path(__file__).parent / "data"


def test_convert_currency():
    assert convert_currency(260931836000) == 26093183.6
    assert convert_currency(800) == 0.08
    assert convert_currency(-500) == -0.05
    assert convert_currency(0) == 0.0
    assert convert_currency(None) is None

    with pytest.raises(TypeError):
        convert_currency("26,093,183.60")

    with pytest.raises(TypeError):
        convert_currency(1.5)

    with pytest.raises(TypeError):
        convert_currency(True)


def test_code_6():
    assert code_6(35, 5030) == "355030"
    assert code_6(35.0, 5030.0) == "355030"
    assert code_6("35", "5030") == "355030"
    assert code_6(11, 15) == "110015"
    assert code_6(None, 15) is None


def create_zip(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name in names:
            zf.writestr(name, b"dummy")
    return buffer.getvalue()


def test_validate_zip():
    # Accepts zip with 1 .mdb
    validate_zip(create_zip(["x.MDB", "manifest.txt"]))

    with pytest.raises(InvalidResponse, match="is not a valid ZIP"):
        validate_zip(b"invalid bytes")

    with pytest.raises(InvalidResponse, match="ZIP must contain exactly 1"):
        validate_zip(create_zip(["x.txt"]))

    with pytest.raises(InvalidResponse, match="ZIP must contain exactly 1"):
        validate_zip(create_zip(["x.mdb", "y.mdb"]))


@pytest.fixture
def municipalities():
    return pl.DataFrame({
        "municipality_code_6": ["355030", "110015", "999999"],
        "municipality_code": ["3550308", "1100150", "9999999"],
    })


def test_process_table_2006(municipalities):
    table = {
        "UF": [35, 11],
        "Cod Mun": [5030, 15],
        "Despesas por Função": [20000, 10000],
        "Legislativa": [1000, -500],
        "Judiciária": [None, 0],
        "Essencial à Justiça": [0, 0],
        "Administração": [0, 0],
        "Defesa Nacional": [0, 0],
        "Segurança Pública": [0, 0],
        "Relações Exteriores": [0, 0],
        "Assistência Social": [0, 0],
        "Previdência Social": [0, 0],
        "Saúde": [0, 0],
        "Trabalho": [0, 0],
        "Educação": [0, 0],
        "Cultura": [0, 0],
        "Direitos da Cidadania": [0, 0],
        "Urbanismo": [0, 0],
        "Habitação": [0, 0],
        "Saneamento": [0, 0],
        "Gestão Ambiental": [0, 0],
        "Ciência e Tecnologia": [0, 0],
        "Agricultura": [0, 0],
        "Organização Agrária": [0, 0],
        "Indústria": [0, 0],
        "Comércio e Serviços": [0, 0],
        "Comunicações": [0, 0],
        "Energia": [0, 0],
        "Transporte": [0, 0],
        "Desporto e Lazer": [0, 0],
        "Encargos Especiais": [0, 0],
    }

    df, discarded = process_table(table, 2006, municipalities)
    assert not discarded

    assert df.height == 2
    assert df.columns == [
        "municipality_code", "year", "source",
        "exp_01_legislative", "exp_02_judiciary", "exp_03_essential_to_justice",
        "exp_04_administration", "exp_05_national_defense", "exp_06_public_security",
        "exp_07_foreign_affairs", "exp_08_social_assistance", "exp_09_social_security",
        "exp_10_health", "exp_11_labor", "exp_12_education",
        "exp_13_culture", "exp_14_citizenship_rights", "exp_15_urban_planning",
        "exp_16_housing", "exp_17_sanitation", "exp_18_environmental_management",
        "exp_19_science_technology", "exp_20_agriculture", "exp_21_agrarian_organization",
        "exp_22_industry", "exp_23_commerce_services", "exp_24_communications",
        "exp_25_energy", "exp_26_transport", "exp_27_sports_leisure",
        "exp_28_special_charges", "exp_total_functions", "exp_intra_budgetary",
        "declara_intraorcamentaria"
    ]
    
    assert df.schema["municipality_code"] == pl.String
    assert df.schema["source"] == pl.String
    assert df.schema["year"] == pl.Int16
    for c in df.columns:
        if c.startswith("exp_"):
            assert df.schema[c] == pl.Float64
    assert df.schema["declara_intraorcamentaria"] == pl.Boolean
    
    # Order of municipality_code
    assert df["municipality_code"].to_list() == ["1100150", "3550308"]
    assert df["year"].to_list() == [2006, 2006]
    assert df["source"].to_list() == ["finbra", "finbra"]
    assert df["exp_01_legislative"].to_list() == [-0.05, 0.1]
    assert df["exp_02_judiciary"].to_list() == [0.0, None]
    assert df["exp_intra_budgetary"].to_list() == [None, None]
    assert df["declara_intraorcamentaria"].to_list() == [None, None]
    assert df["exp_total_functions"].to_list() == [1.0, 2.0]


def test_process_table_2010(municipalities):
    table = {
        "UF": [35, 11, 99],
        "Cod Mun": [5030, 15, 9999],
        "Despesas por Função": [10000, 20000, 30000],
        "Legislativa": [0, 0, 0],
        "Judiciária": [0, 0, 0],
        "Essencial à Justiça": [0, 0, 0],
        "Administração": [0, 0, 0],
        "Defesa Nacional": [0, 0, 0],
        "Segurança Pública": [0, 0, 0],
        "Relações Exteriores": [0, 0, 0],
        "Assistência Social": [0, 0, 0],
        "Previdência Social": [0, 0, 0],
        "Saúde": [0, 0, 0],
        "Trabalho": [0, 0, 0],
        "Educação": [0, 0, 0],
        "Cultura": [0, 0, 0],
        "Direitos da Cidadania": [0, 0, 0],
        "Urbanismo": [0, 0, 0],
        "Habitação": [0, 0, 0],
        "Saneamento": [0, 0, 0],
        "Gestão Ambiental": [0, 0, 0],
        "Ciência e Tecnologia": [0, 0, 0],
        "Agricultura": [0, 0, 0],
        "Organização Agrária": [0, 0, 0],
        "Indústria": [0, 0, 0],
        "Comércio e Serviços": [0, 0, 0],
        "Comunicações": [0, 0, 0],
        "Energia": [0, 0, 0],
        "Transporte": [0, 0, 0],
        "Desporto e Lazer": [0, 0, 0],
        "Encargos Especiais": [0, 0, 0],
        "Desp por Função Intra-Orçamentária": [50000, 0, None],
        "0118": [1, 2, 3],
        "73424,011": [1, 2, 3],
    }

    df, discarded = process_table(table, 2010, municipalities)
    assert not discarded
    assert df.height == 3
    assert "0118" not in df.columns
    assert "73424,011" not in df.columns

    # 9999999 -> desp_intra None, declara False
    # 1100150 -> desp_intra 0, declara False
    # 3550308 -> desp_intra 5, declara True
    
    # Ordered by municipality_code
    assert df["municipality_code"].to_list() == ["1100150", "3550308", "9999999"]
    assert df["exp_intra_budgetary"].to_list() == [0.0, 5.0, None]
    assert df["declara_intraorcamentaria"].to_list() == [False, True, False]


def test_process_table_errors(municipalities):
    table = {
        "UF": [35],
        "Cod Mun": [5030],
        "Despesas por Função": [10000],
        "Legislativa": [0],
        "Judiciária": [0],
        "Essencial à Justiça": [0],
        "Administração": [0],
        "Defesa Nacional": [0],
        "Segurança Pública": [0],
        "Relações Exteriores": [0],
        "Assistência Social": [0],
        "Previdência Social": [0],
        "Saúde": [0],
        "Trabalho": [0],
        "Educação": [0],
        "Cultura": [0],
        "Direitos da Cidadania": [0],
        "Urbanismo": [0],
        "Habitação": [0],
        "Saneamento": [0],
        "Gestão Ambiental": [0],
        "Ciência e Tecnologia": [0],
        "Agricultura": [0],
        "Organização Agrária": [0],
        "Indústria": [0],
        "Comércio e Serviços": [0],
        "Comunicações": [0],
        "Energia": [0],
        "Transporte": [0],
        "Desporto e Lazer": [0],
    }

    # Missing Encargos Especiais
    with pytest.raises(ValueError, match="Missing columns.*Encargos Especiais"):
        process_table(table, 2006, municipalities)

    table["Encargos Especiais"] = [0]
    
    # Two intra
    table_intra = table.copy()
    table_intra["Intra 1"] = [0]
    table_intra["Intra 2"] = [0]
    with pytest.raises(ValueError, match="Multiple intra-budgetary columns"):
        process_table(table_intra, 2006, municipalities)
        
    # Repeated key
    table_rep = {k: v * 2 for k, v in table.items()}
    with pytest.raises(ValueError, match="Repeated keys.*355030"):
        process_table(table_rep, 2006, municipalities)


def test_discarded(municipalities):
    table = {
        "UF": [None, 35, 12],
        "Cod Mun": [5030, None, 15],
        "Despesas por Função": [10000, 10000, 10000],
        "Legislativa": [0, 0, 0],
        "Judiciária": [0, 0, 0],
        "Essencial à Justiça": [0, 0, 0],
        "Administração": [0, 0, 0],
        "Defesa Nacional": [0, 0, 0],
        "Segurança Pública": [0, 0, 0],
        "Relações Exteriores": [0, 0, 0],
        "Assistência Social": [0, 0, 0],
        "Previdência Social": [0, 0, 0],
        "Saúde": [0, 0, 0],
        "Trabalho": [0, 0, 0],
        "Educação": [0, 0, 0],
        "Cultura": [0, 0, 0],
        "Direitos da Cidadania": [0, 0, 0],
        "Urbanismo": [0, 0, 0],
        "Habitação": [0, 0, 0],
        "Saneamento": [0, 0, 0],
        "Gestão Ambiental": [0, 0, 0],
        "Ciência e Tecnologia": [0, 0, 0],
        "Agricultura": [0, 0, 0],
        "Organização Agrária": [0, 0, 0],
        "Indústria": [0, 0, 0],
        "Comércio e Serviços": [0, 0, 0],
        "Comunicações": [0, 0, 0],
        "Energia": [0, 0, 0],
        "Transporte": [0, 0, 0],
        "Desporto e Lazer": [0, 0, 0],
        "Encargos Especiais": [0, 0, 0],
    }

    df, discarded = process_table(table, 2006, municipalities)
    assert df.height == 0
    assert len(discarded) == 3
    assert discarded[0]["reason"] == "null key"
    assert discarded[1]["reason"] == "null key"
    assert discarded[2]["reason"] == "outside DTB"


def test_real_samples():
    with open(DATA / "finbra_dsubfuncao_2006_sample.json", encoding="utf-8") as f:
        table_2006 = json.load(f)
    
    with open(DATA / "finbra_dsubfuncao_2010_sample.json", encoding="utf-8") as f:
        table_2010 = json.load(f)

    real_munis = pl.DataFrame({
        "municipality_code_6": ["355030", "110009", "110013"],
        "municipality_code": ["3550308", "1100098", "1100130"],
    })
    
    df_2006, d_2006 = process_table(table_2006, 2006, real_munis)
    assert df_2006.height == 3
    
    df_2010, d_2010 = process_table(table_2010, 2010, real_munis)
    assert df_2010.height == 3
    
    # São Paulo total equals sample integer / 10000
    sp_2006_raw = table_2006["Despesas por Função"][table_2006["Cod Mun"].index(5030)]
    sp_2006_df = df_2006.filter(pl.col("municipality_code") == "3550308")["exp_total_functions"][0]
    assert sp_2006_df == sp_2006_raw / 10000.0
    
    sp_2010_raw = table_2010["Despesas por Função"][table_2010["Cod Mun"].index(5030)]
    sp_2010_df = df_2010.filter(pl.col("municipality_code") == "3550308")["exp_total_functions"][0]
    assert sp_2010_df == sp_2010_raw / 10000.0

    assert "0118" in table_2010
    assert "0118" not in df_2010.columns
    
    sp_2010_intra = df_2010.filter(pl.col("municipality_code") == "3550308")["exp_intra_budgetary"][0]
    assert sp_2010_intra == 10311896708400 / 10000.0
    
    assert df_2010.filter(pl.col("municipality_code") == "3550308")["declara_intraorcamentaria"][0] is True
    assert df_2010.filter(pl.col("municipality_code") == "1100098")["declara_intraorcamentaria"][0] is True
    assert df_2010.filter(pl.col("municipality_code") == "1100130")["declara_intraorcamentaria"][0] is False

    # Sum of budget functions within 0.1%
    functions_cols = [c for c in df_2006.columns if c.startswith("exp_") and c not in ("exp_total_functions", "exp_intra_budgetary")]
    
    def check_sum(df, df_name):
        for row in df.iter_rows(named=True):
            functions_sum = sum(row[c] for c in functions_cols if row[c] is not None)
            total = row["exp_total_functions"]
            if total > 0:
                diff = abs(functions_sum - total)
                rel_diff = diff / total
                if rel_diff >= 0.001:
                    assert False, f"[{df_name}] Municipality {row['municipality_code']} does not add up: sum={functions_sum}, total={total}, rel_diff={rel_diff}"
    
    check_sum(df_2006, "2006")
    check_sum(df_2010, "2010")


def test_published_columns():
    assert len(PUBLISHED_COLUMNS) == 30
    assert PUBLISHED_COLUMNS[0] == "municipality_code"
    assert PUBLISHED_COLUMNS[1] == "year"
    for i, (_, _, c_out) in enumerate(FUNCTIONS):
        assert PUBLISHED_COLUMNS[i + 2] == c_out


def test_harmonize(tmp_path, monkeypatch):
    
    with open(DATA / "finbra_dsubfuncao_2006_sample.json", encoding="utf-8") as f:
        table_2006 = json.load(f)
    with open(DATA / "finbra_dsubfuncao_2010_sample.json", encoding="utf-8") as f:
        table_2010 = json.load(f)
        
    def mock_read_dsubfuncao(folder, year):
        if year <= 2009:
            return table_2006
        else:
            return table_2010
            
    monkeypatch.setattr(finbra, "read_dsubfuncao", mock_read_dsubfuncao)
    
    municipalities = pl.DataFrame({
        "municipality_code_6": ["355030", "110009", "110013"],
        "municipality_code": ["3550308", "1100098", "1100130"],
    })
    
    df = finbra.harmonize(tmp_path, municipalities)
    
    assert df.columns == PUBLISHED_COLUMNS
    assert "source" not in df.columns
    assert "exp_total_functions" not in df.columns
    assert "exp_intra_budgetary" not in df.columns
    assert "declara_intraorcamentaria" not in df.columns
    
    assert df.is_sorted(["municipality_code", "year"])
    assert df.height == 3 * 7  # 3 municipalities, 7 years (2006-2012)
    assert df.schema["municipality_code"] == pl.String
    assert df.schema["year"] == pl.Int16
    for c in PUBLISHED_COLUMNS[2:]:
        assert df.schema[c] == pl.Float64
