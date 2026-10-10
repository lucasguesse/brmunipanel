import json
import os
import shutil
import tempfile
from pathlib import Path

import polars as pl
import pytest

from br_municipios_panel import empacotamento

@pytest.fixture
def fake_environment(tmp_path):
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    results_dir = tmp_path / "results"
    processed_dir.mkdir(parents=True)
    results_dir.mkdir(parents=True)
    
    # Create fake parquet files
    tabelas = [
        "municipios", "demografia_economia_social", "financas_publicas",
        "saude", "municipios_limitrofes", "educacao"
    ]
    
    # Mock data
    df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    for t in tabelas:
        df.write_parquet(processed_dir / f"{t}.parquet")
        
    # Mock results
    qc = results_dir / "quality_checks.csv"
    with open(qc, "w", encoding="utf-8") as f:
        f.write("status\nOK\nOK\n")
        
    qs = results_dir / "quality_summary.csv"
    with open(qs, "w", encoding="utf-8") as f:
        f.write("col\n1\n")
        
    d = processed_dir / "dictionary.csv"
    with open(d, "w", encoding="utf-8") as f:
        f.write("col\n1\n")
        
    # Mock datasets.json
    dj = tmp_path / "datasets.json"
    with open(dj, "w", encoding="utf-8") as f:
        f.write('[{"id": "t1", "nome": "T1", "periodo": "2020"}]')
        
    return data_dir, results_dir, dj

def test_empacotamento_falha_auditoria(fake_environment):
    data_dir, results_dir, dj = fake_environment
    # Injete FALHA
    qc = results_dir / "quality_checks.csv"
    with open(qc, "a", encoding="utf-8") as f:
        f.write("FALHA\n")
        
    with pytest.raises(RuntimeError, match="auditoria crítica não está integralmente aprovada"):
        empacotamento.montar_pacote_final("1.0", "2026", "abc", data_dir, results_dir, dj)

def test_empacotamento_arquivos_e_manifesto(fake_environment):
    data_dir, results_dir, dj = fake_environment
    empacotamento.montar_pacote_final("1.0", "2026-10-10", "abc", data_dir, results_dir, dj)
    
    final_dir = data_dir / "final"
    assert final_dir.exists()
    
    arquivos_esperados = set([
        "municipios.parquet", "municipios.csv.gz",
        "demografia_economia_social.parquet", "demografia_economia_social.csv.gz",
        "financas_publicas.parquet", "financas_publicas.csv.gz",
        "saude.parquet", "saude.csv.gz",
        "municipios_limitrofes.parquet", "municipios_limitrofes.csv.gz",
        "educacao.parquet", "educacao.csv.gz",
        "dictionary.csv", "quality_summary.csv", "quality_checks.csv",
        "manifest.json", "checksums.sha256", "README.md"
    ])
    
    arquivos_gerados = set([p.name for p in final_dir.iterdir() if p.is_file()])
    assert arquivos_gerados == arquivos_esperados
    
    # Valida manifesto
    with open(final_dir / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["versao"] == "1.0"
    assert manifest["data"] == "2026-10-10"
    assert len(manifest["arquivos"]) == 15 # 6 parquet + 6 csv + 3 docs
    
    # Validar hashes e determinismo
    # Vamos gerar novamente em outro lugar e comparar hashes
    empacotamento.montar_pacote_final("1.0", "2026-10-10", "abc", data_dir, results_dir, dj)
    with open(final_dir / "manifest.json", "r", encoding="utf-8") as f:
        manifest2 = json.load(f)
        
    assert manifest == manifest2
    
    # Checar Parquet == Processed
    p1 = final_dir / "municipios.parquet"
    p2 = data_dir / "processed" / "municipios.parquet"
    assert p1.read_bytes() == p2.read_bytes()

def test_falha_atomica(fake_environment):
    data_dir, results_dir, dj = fake_environment
    empacotamento.montar_pacote_final("1.0", "2026-10-10", "abc", data_dir, results_dir, dj)
    
    final_dir = data_dir / "final"
    marca = final_dir / "municipios.parquet"
    hash_antes = empacotamento.calcular_sha256(marca)
    
    # Remove um processado para falhar
    (data_dir / "processed" / "educacao.parquet").unlink()
    
    with pytest.raises(FileNotFoundError):
        empacotamento.montar_pacote_final("1.0", "2026-10-10", "abc", data_dir, results_dir, dj)
        
    # Pacote final não foi alterado
    assert empacotamento.calcular_sha256(marca) == hash_antes
    assert (final_dir / "educacao.parquet").exists()
