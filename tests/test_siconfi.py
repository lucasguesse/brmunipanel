import gzip
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from brmunipanel import core
from brmunipanel.tesouro import expenditure_by_function, siconfi
from brmunipanel.tesouro.expenditure_by_function import SCHEMA
from brmunipanel.tesouro.finbra import process_table

def test_read_header(tmp_path):
    z1 = tmp_path / "test.zip"
    with zipfile.ZipFile(z1, "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    
    hdr = siconfi.read_header(z1)
    assert hdr == {"fiscal_year": 2013, "scope": "Municípios", "table": "Despesas por Função (Anexo I-E)"}
    
    # Wrong scope
    with zipfile.ZipFile(tmp_path / "t2.zip", "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Estados/DF\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    with pytest.raises(ValueError, match="Estados/DF"):
        siconfi.read_header(tmp_path / "t2.zip")
        
    # Other table
    with zipfile.ZipFile(tmp_path / "t3.zip", "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Outra Tabela\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    with pytest.raises(ValueError, match="Outra Tabela"):
        siconfi.read_header(tmp_path / "t3.zip")
        
    # 4th line header
    with zipfile.ZipFile(tmp_path / "t4.zip", "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Valor\n".encode("latin-1"))
    with pytest.raises(ValueError, match="invalid header"):
        siconfi.read_header(tmp_path / "t4.zip")
        
    # Two CSV files
    with zipfile.ZipFile(tmp_path / "t5.zip", "w") as zf:
        zf.writestr("f1.csv", "")
        zf.writestr("f2.csv", "")
    with pytest.raises(ValueError, match="found 2"):
        siconfi.read_header(tmp_path / "t5.zip")

def test_download(tmp_path):
    for year in siconfi.YEARS:
        with zipfile.ZipFile(tmp_path / f"arq_{year}.zip", "w") as zf:
            zf.writestr("f.csv", f"Exercício: {year}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            
    # List and register
    records = siconfi.download(tmp_path)
    assert len(records) == len(siconfi.YEARS)
    for r in records:
        assert r["method"] == "MANUAL"
        
    # Second call does not create a new record
    records2 = siconfi.download(tmp_path)
    assert records == records2

def test_download_missing_year(tmp_path):
    with zipfile.ZipFile(tmp_path / "any.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    
    with pytest.raises(FileNotFoundError, match="2020"):
        siconfi.download(tmp_path)
        
def test_download_different_name(tmp_path):
    with zipfile.ZipFile(tmp_path / "any.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
        
    with pytest.raises(FileNotFoundError):
        siconfi.download(tmp_path)
    manifest = core.read_manifest(tmp_path)
    assert "annual_accounts_2015" in manifest
    assert manifest["annual_accounts_2015"]["file"] == "any.zip"

def test_download_two_files(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
        
    with pytest.raises(ValueError, match="Two files with the same fiscal year 2015"):
        siconfi.download(tmp_path)

def test_read_file(tmp_path):
    sample = Path(__file__).parent / "data" / "siconfi_annual_accounts_2013_sample.csv"
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.write(sample, "finbra.csv")
        
    df = siconfi.read_file(tmp_path, "a.zip")
    assert df.width == 4
    assert df.schema["valor"] == pl.Float64
    assert df.schema["municipality_code"] == pl.String
    assert all(len(c) == 7 for c in df["municipality_code"].to_list())
    
    # Check São Paulo total explicitly
    sp_total = df.filter((pl.col("municipality_code") == "3550308") & (pl.col("coluna") == "Despesas Empenhadas") & (pl.col("conta") == "Despesas (Exceto Intra-Orçamentárias)"))["valor"][0]
    assert sp_total == 39136092195.15
    
    # Also verify number of lines is sample minus 4 initial
    with open(sample, "rb") as f:
        rows = len(f.read().splitlines())
    assert df.height == rows - 4
    
def test_process_statement_simple():
    items = [
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 100.0},
        {"coluna": "Despesas Empenhadas", "conta": "04.122 - Sub", "valor": 50.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 1000.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Intraorçamentárias)", "valor": 10.0},
    ]
    ret, av = siconfi.process_statement(items)
    assert ret["exp_04_administration"] == 100.0
    assert ret["exp_total_functions"] == 1000.0
    assert ret["exp_intra_budgetary"] == 10.0
    assert ret["declara_intraorcamentaria"] is True
    
    # Budget function only with subfunctions
    items2 = [
        {"coluna": "Despesas Empenhadas", "conta": "08.122 - Sub", "valor": 30.0},
        {"coluna": "Despesas Empenhadas", "conta": "08.123 - Sub", "valor": 20.0},
    ]
    ret2, av2 = siconfi.process_statement(items2)
    assert ret2["exp_08_social_assistance"] == 50.0
    assert "function_by_subfunctions:08" in av2
    assert ret2["exp_intra_budgetary"] == 0.0
    assert ret2["declara_intraorcamentaria"] is False
    
    # Budget function without any row counts as zero
    assert ret2["exp_10_health"] == 0.0

def test_process_statement_variants_total():
    variants = [
        ("Despesas (Exceto Intra-Orçamentárias)", "Despesas (Intra-Orçamentárias)"),
        ("Despesas (Exceto Intraorçamentárias)", "Despesas (Intraorçamentárias)"),
        ("Despesas Exceto Intraorçamentárias", "Despesas Intraorçamentárias")
    ]
    for tex, tin in variants:
        items = [
            {"coluna": "Despesas Empenhadas", "conta": tex, "valor": 500.0},
            {"coluna": "Despesas Empenhadas", "conta": tin, "valor": 5.0},
        ]
        ret, av = siconfi.process_statement(items)
        assert ret["exp_total_functions"] == 500.0
        assert ret["exp_intra_budgetary"] == 5.0

def test_process_statement_special_cases():
    # Without committed expenditure
    assert siconfi.process_statement([{"coluna": "Other", "conta": "04 - Administração", "valor": 1.0}]) == (None, [])
    
    # Two rows
    with pytest.raises(ValueError, match="Two function rows with the same code 04"):
        siconfi.process_statement([
            {"coluna": "Despesas Empenhadas", "conta": "04 - A", "valor": 1.0},
            {"coluna": "Despesas Empenhadas", "conta": "04 - B", "valor": 2.0},
        ])
        
    # Budget function with code 99 generates warning
    ret, av = siconfi.process_statement([
        {"coluna": "Despesas Empenhadas", "conta": "99 - Z", "valor": 1.0}
    ])
    assert "function_outside_classification:99" in av
    assert len(ret) == 31
    assert not any("99" in k for k in ret.keys())
    
    # Null value becomes zero
    ret, av = siconfi.process_statement([
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": None},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 0.0}
    ])
    assert ret["exp_04_administration"] == 0.0
    assert "null_value:04 - Administração" in av
    
    # Without total row
    ret, av = siconfi.process_statement([
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 10.0}
    ])
    assert ret["exp_total_functions"] is None
    assert "sem_total" in av
    
    # Other column of the same budget function does not enter
    ret, av = siconfi.process_statement([
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 10.0},
        {"coluna": "Despesas Liquidadas", "conta": "04 - Administração", "valor": 5.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 10.0}
    ])
    assert ret["exp_04_administration"] == 10.0
    
    # Budget function assembled by sum of subfunctions
    ret, av = siconfi.process_statement([
        {"coluna": "Despesas Empenhadas", "conta": "10.301 - Sub", "valor": 5.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 10.0}
    ])
    assert ret["exp_10_health"] == 5.0
    assert "function_by_subfunctions:10" in av
    
def test_process_statement_residue_without_code():
    items = [
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 10.0},
        {"coluna": "Despesas Empenhadas", "conta": "Demais Subfunções", "valor": 5.0},
        {"coluna": "Despesas Empenhadas", "conta": "Demais Subfunções", "valor": 2.0},
        {"coluna": "Despesas Empenhadas", "conta": "Demais Subfunções", "valor": 3.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 10.0}
    ]
    ret, av = siconfi.process_statement(items)
    assert ret["exp_04_administration"] == 10.0
    assert av.count("residue_without_code") == 1
    
def test_read_file_short_row(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.writestr("f.csv", "A\nB\nC\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n1;2;3\n".encode("latin-1"))
    with pytest.raises(ValueError, match="line 5 has a different number of fields than the header"):
        siconfi.read_file(tmp_path, "a.zip")

def test_read_file_long_row(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.writestr("f.csv", "A\nB\nC\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n1;2;3;4;5;6;7;8;9\n".encode("latin-1"))
    with pytest.raises(ValueError, match="line 5 has a different number of fields than the header"):
        siconfi.read_file(tmp_path, "a.zip")

def test_harmonize(tmp_path):
    municipalities = pl.DataFrame({"municipality_code": ["3550308", "1600279", "4126652"], "state_code": ["35", "16", "41"]})
    
    for year in siconfi.YEARS:
        with zipfile.ZipFile(tmp_path / f"a_{year}.zip", "w") as zf:
            zf.writestr("f.csv", f"Exercício: {year}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\nInst;3550308;SP;1;Despesas Empenhadas;04 - Administração;;10.0\nInst;1600279;AP;1;Despesas Empenhadas;08 - Assistência;;5.0\n".encode("latin-1"))
            
    siconfi.download(tmp_path)
    
    df = siconfi.harmonize(tmp_path, municipalities)
    assert df.columns == expenditure_by_function.PUBLISHED_COLUMNS
    assert df.schema["municipality_code"] == pl.String
    assert df.schema["year"] == pl.Int16
    for c in expenditure_by_function.PUBLISHED_COLUMNS[2:]:
        assert df.schema[c] == pl.Float64
    assert df.height == len(siconfi.YEARS) * 2
    assert df.is_sorted(["municipality_code", "year"])

def test_harmonize_real_samples(tmp_path):
    samples = [
        (2013, Path(__file__).parent / "data" / "siconfi_annual_accounts_2013_sample.csv"),
        (2022, Path(__file__).parent / "data" / "siconfi_annual_accounts_2022_sample.csv"),
    ]
    municipalities = pl.DataFrame({"municipality_code": ["3550308", "1600279", "4126652", "2905206"]})
    
    manifest = {}
    for year, p in samples:
        zip_path = tmp_path / f"a_{year}.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(p, "f.csv")
        manifest[f"annual_accounts_{year}"] = {"file": zip_path.name}
    
    for year in siconfi.YEARS:
        if f"annual_accounts_{year}" not in manifest:
            zip_path = tmp_path / f"a_{year}.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("f.csv", f"Exercício: {year}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            manifest[f"annual_accounts_{year}"] = {"file": zip_path.name}
            
    core._write_manifest(tmp_path, manifest)
    
    report = []
    df = siconfi.harmonize(tmp_path, municipalities, report=report)
    
    sp_2013 = df.filter((pl.col("year") == 2013) & (pl.col("municipality_code") == "3550308"))
    assert sp_2013.height == 1
    sum_sp = sum(sp_2013[0, col] for _, _, col in expenditure_by_function.FUNCTIONS)
    
    df_raw_2013 = siconfi.read_file(tmp_path, manifest["annual_accounts_2013"]["file"])
    items_2013 = df_raw_2013.filter(pl.col("municipality_code") == "3550308").to_dicts()
    ret_2013, _ = siconfi.process_statement(items_2013)
    assert abs(sum_sp - ret_2013["exp_total_functions"]) < 0.01
    
    sp_2022 = df.filter((pl.col("year") == 2022) & (pl.col("municipality_code") == "3550308"))
    assert sp_2022.height == 1
    sum_sp2 = sum(sp_2022[0, col] for _, _, col in expenditure_by_function.FUNCTIONS)
    
    df_raw_2022 = siconfi.read_file(tmp_path, manifest["annual_accounts_2022"]["file"])
    items_2022 = df_raw_2022.filter(pl.col("municipality_code") == "3550308").to_dicts()
    ret_2022, _ = siconfi.process_statement(items_2022)
    assert abs(sum_sp2 - ret_2022["exp_total_functions"]) < 0.01
    
    lj_2013 = df.filter((pl.col("year") == 2013) & (pl.col("municipality_code") == "1600279"))
    assert lj_2013.height == 1
    assert lj_2013[0, "exp_10_health"] == 9360236.83
    
    assert any(r["municipality_code"] == "1600279" and r["year"] == 2013 and r["type"].startswith("function_by_subfunctions") for r in report)

def test_harmonize_discard(tmp_path):
    municipalities = pl.DataFrame({"municipality_code": ["1234567"]})
    with zipfile.ZipFile(tmp_path / "a_2013.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\nI;5300108;DF;1;Despesas Empenhadas;04 - A;;1\nI;9999999;XX;1;Despesas Empenhadas;04 - A;;1\n".encode("latin-1"))
        
    manifest = {}
    for year in siconfi.YEARS:
        if year == 2013:
            manifest[f"annual_accounts_{year}"] = {"file": "a_2013.zip"}
        else:
            zip_path = tmp_path / f"a_{year}.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("f.csv", f"Exercício: {year}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            manifest[f"annual_accounts_{year}"] = {"file": zip_path.name}
    core._write_manifest(tmp_path, manifest)
    
    report = []
    siconfi.harmonize(tmp_path, municipalities, report=report)
    assert any(r["municipality_code"] == "5300108" and r["type"] == "distrito_federal" for r in report)
    assert any(r["municipality_code"] == "9999999" and r["type"] == "outside_dtb" for r in report)
    
def test_finbra_equal_schema():
    sample = Path(__file__).parent / "data" / "finbra_dsubfuncao_2006_sample.json"
    with open(sample, encoding="utf-8") as f:
        table_2006 = json.load(f)

    real_munis = pl.DataFrame({
        "municipality_code_6": ["355030"],
        "municipality_code": ["3550308"],
    })
    
    df, _ = process_table(table_2006, 2006, real_munis)
    
    assert df.schema == SCHEMA


def test_api_requests():
    reqs_2013 = siconfi.api_requests(2013, ["1200013"])
    assert len(reqs_2013) == 1
    assert reqs_2013[0].key == "2013/1200013"
    assert reqs_2013[0].url.endswith("no_anexo=Anexo+I-E")

    reqs_2014 = siconfi.api_requests(2014, ["1200013"])
    assert len(reqs_2014) == 1
    assert reqs_2014[0].key == "2014/1200013"
    assert reqs_2014[0].url.endswith("no_anexo=DCA-Anexo+I-E")

    reqs_order = siconfi.api_requests(2015, ["3550308", "1100015", "1200013"])
    assert [r.key for r in reqs_order] == ["2015/1100015", "2015/1200013", "2015/3550308"]


def test_validate_api_response():
    siconfi.validate_api_response(b'{"items": [], "hasMore": false}')

    with pytest.raises(core.InvalidResponse):
        siconfi.validate_api_response(b"texto nao json")

    with pytest.raises(core.InvalidResponse):
        siconfi.validate_api_response(b'{"hasMore": false}')

    with pytest.raises(core.InvalidResponse):
        siconfi.validate_api_response(b'{"items": [], "hasMore": true}')


def test_download_api_skips_recorded_year_and_excludes_df(tmp_path, monkeypatch):
    calls = []

    def fake_download_at_rate(reqs, target, **kwargs):
        calls.append(list(reqs))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.compress(b'{"chave": "x"}\n', mtime=0))
        return {"rows": len(reqs), "pauses_429": 0}

    monkeypatch.setattr(core, "download_at_rate", fake_download_at_rate)

    municipalities = ["1200013", "5300108", "1100015"]
    years = [2013, 2014]

    siconfi.download_api(tmp_path, municipalities, years=years)
    assert len(calls) == 2
    for batch in calls:
        keys = [r.key for r in batch]
        assert not any("5300108" in c for c in keys)

    manifest = core.read_manifest(tmp_path)
    assert "dca_2013" in manifest
    assert "dca_2014" in manifest
    assert manifest["dca_2013"]["method"] == "GET"
    assert manifest["dca_2014"]["method"] == "GET"

    siconfi.download_api(tmp_path, municipalities, years=years)
    assert len(calls) == 2


def test_harmonize_api_equals_portal(tmp_path):
    folder_portal = tmp_path / "portal"
    folder_api = tmp_path / "api"
    folder_portal.mkdir()
    folder_api.mkdir()

    samples = [
        (2013, Path(__file__).parent / "data" / "siconfi_annual_accounts_2013_sample.csv"),
        (2022, Path(__file__).parent / "data" / "siconfi_annual_accounts_2022_sample.csv"),
    ]
    municipalities = pl.DataFrame({"municipality_code": ["3550308", "1600279", "4126652", "2905206"]})

    manifest_portal = {}
    manifest_api = {}

    for year, p in samples:
        zip_path = folder_portal / f"a_{year}.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(p, "f.csv")
        manifest_portal[f"annual_accounts_{year}"] = {"file": zip_path.name}

        df_year = siconfi.read_file(folder_portal, zip_path.name)
        rows_jsonl = []
        for muni_code, group in df_year.group_by("municipality_code"):
            code_str = muni_code[0] if isinstance(muni_code, tuple) else muni_code
            items = []
            for row in group.iter_rows(named=True):
                items.append({
                    "cod_ibge": int(code_str),
                    "coluna": row["coluna"],
                    "conta": row["conta"],
                    "valor": row["valor"],
                })
            body = json.dumps({"items": items, "hasMore": False}, ensure_ascii=False)
            rows_jsonl.append(json.dumps({
                "key": f"{year}/{code_str}",
                "url": f"http://api/{year}/{code_str}",
                "http": 200,
                "body": body,
            }, ensure_ascii=False))

        file_api_year = siconfi.api_file(year)
        text_gz = gzip.compress("\n".join(rows_jsonl).encode("utf-8") + (b"\n" if rows_jsonl else b""), mtime=0)
        (folder_api / file_api_year).write_bytes(text_gz)
        manifest_api[f"dca_{year}"] = {"file": file_api_year}

    for year in siconfi.YEARS:
        if f"annual_accounts_{year}" not in manifest_portal:
            zip_path = folder_portal / f"a_{year}.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("f.csv", f"Exercício: {year}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            manifest_portal[f"annual_accounts_{year}"] = {"file": zip_path.name}

        if f"dca_{year}" not in manifest_api:
            file_api_year = siconfi.api_file(year)
            (folder_api / file_api_year).write_bytes(gzip.compress(b"", mtime=0))
            manifest_api[f"dca_{year}"] = {"file": file_api_year}

    core._write_manifest(folder_portal, manifest_portal)
    core._write_manifest(folder_api, manifest_api)

    df_portal = siconfi.harmonize(folder_portal, municipalities)
    df_api = siconfi.harmonize(folder_api, municipalities, source="api")

    assert df_api.equals(df_portal)

    with pytest.raises(ValueError, match="Unknown source"):
        siconfi.harmonize(folder_api, municipalities, source="other")


