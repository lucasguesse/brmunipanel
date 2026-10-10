import os
import sys
from pathlib import Path
import tempfile
import polars as pl
import json
import pytest
import hashlib

# Fix path to import modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from br_municipios_panel.metadata.contratos import CONTRATOS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from generate_dictionaries import generate_dictionaries
import run_pipeline

def hash_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()

def test_geracao_csvs_determinismo_utf8():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        intermediario = tmp_path / "intermediate"
        processado = tmp_path / "processed"
        resultados = tmp_path / "results"
        var_json = tmp_path / "variaveis.json"
        
        intermediario.mkdir()
        processado.mkdir()
        
        # Write minimal metadata
        meta = {
            "intermediate": {"tabela_teste": {"colA": {"tipo": "id", "descricao": "desc", "fonte": "f", "unidade": "u", "periodo": "p"}}},
            "processed": {"tabela_proc": {"colA": {"tipo": "id", "descricao": "desc", "fonte": "f", "unidade": "u", "periodo": "p"}}}
        }
        with open(var_json, "w", encoding="utf-8") as f:
            json.dump(meta, f)
            
        # Write some parquets
        df = pl.DataFrame({"colA": [1, 2]})
        df.write_parquet(intermediario / "tabela_teste.parquet")
        df.write_parquet(processado / "tabela_proc.parquet")
        
        # Mock contratos temporarily
        CONTRATOS["intermediate"]["tabela_teste"] = {"cols": {"colA": pl.Int64}, "periodo": None, "chaves": ["colA"]}
        CONTRATOS["processed"]["tabela_proc"] = {"cols": {"colA": pl.Int64}, "periodo": None, "chaves": ["colA"]}
        
        # Generar os dicionarios pela primeira vez
        res1 = generate_dictionaries(intermediario, processado, resultados, var_json)
        
        # Ler hashes
        h1_int = hash_file(intermediario / "dictionary.csv")
        h1_proc = hash_file(processado / "dictionary.csv")
        h1_sum = hash_file(resultados / "quality_summary.csv")
        h1_chk = hash_file(resultados / "quality_checks.csv")
        
        # Verificar UTF-8 sem BOM
        for fpath in [intermediario / "dictionary.csv", processado / "dictionary.csv", resultados / "quality_summary.csv", resultados / "quality_checks.csv"]:
            with open(fpath, "rb") as f:
                bytes_read = f.read()
                assert not bytes_read.startswith(b"\xef\xbb\xbf"), f"Arquivo {fpath} contem BOM"
                
        # Segunda geração para verificar hashes
        res2 = generate_dictionaries(intermediario, processado, resultados, var_json)
        
        h2_int = hash_file(intermediario / "dictionary.csv")
        h2_proc = hash_file(processado / "dictionary.csv")
        h2_sum = hash_file(resultados / "quality_summary.csv")
        h2_chk = hash_file(resultados / "quality_checks.csv")
        
        assert h1_int == h2_int
        assert h1_proc == h2_proc
        assert h1_sum == h2_sum
        assert h1_chk == h2_chk
        
        # Restore contratos 
        del CONTRATOS["intermediate"]["tabela_teste"]
        del CONTRATOS["processed"]["tabela_proc"]


def test_falha_critica_grava_relatorios():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        intermediario = tmp_path / "intermediate"
        processado = tmp_path / "processed"
        resultados = tmp_path / "results"
        var_json = tmp_path / "variaveis.json"
        
        intermediario.mkdir()
        processado.mkdir()
        
        # Write one valid parquet so summary is not None
        df = pl.DataFrame({
            "cod_municipio": ["1"], 
            "ano": [2010],
            "area_km2": [10.0],
            "latitude_sede": [-10.0],
            "longitude_sede": [-40.0]
        })
        df.write_parquet(intermediario / "ibge_municipios.parquet")
        
        # Empty metadata
        meta = {}
        with open(var_json, "w", encoding="utf-8") as f:
            json.dump(meta, f)
            
        # We expect critical failure because it lacks contracts and JSON
        res = generate_dictionaries(intermediario, processado, resultados, var_json)
        
        assert res is False
        
        # Files should still exist
        assert (resultados / "quality_summary.csv").exists()
        assert (resultados / "quality_checks.csv").exists()


def test_run_pipeline_propaga_erro(monkeypatch):
    import generate_dictionaries
    # monkeypatch generate_dictionaries to return False
    def mock_generate(*args, **kwargs):
        return False
        
    monkeypatch.setattr(generate_dictionaries, "generate_dictionaries", mock_generate)
    
    with pytest.raises(RuntimeError, match="Falha crítica na geração de dicionários / auditoria."):
        import polars as pl
        monkeypatch.setattr(pl, "read_parquet", lambda *a, **k: pl.DataFrame({"cod_municipio": [1], "pop_origem": [0]}))
        monkeypatch.setattr(pl.DataFrame, "write_parquet", lambda *a, **k: None)
        
        from br_municipios_panel import painel
        monkeypatch.setattr(painel, "montar_municipios", lambda *a: pl.DataFrame())
        monkeypatch.setattr(painel, "montar_despesa", lambda *a, **k: pl.DataFrame())
        monkeypatch.setattr(painel, "montar_tabela_longitudinal", lambda *a, **k: pl.DataFrame())
        monkeypatch.setattr(painel, "montar_limitrofes", lambda *a, **k: pl.DataFrame())
        monkeypatch.setattr(painel, "consolidar_educacao", lambda *a, **k: pl.DataFrame())
        
        monkeypatch.setattr(Path, "exists", lambda self: True)
        monkeypatch.setattr(Path, "unlink", lambda self: None)
        monkeypatch.setattr(Path, "mkdir", lambda self, **k: None)
        
        run_pipeline._consolidar()
