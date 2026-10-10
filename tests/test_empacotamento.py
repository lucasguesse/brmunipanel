import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

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
    
    tabelas = [
        "municipios", "demografia_economia_social", "financas_publicas",
        "saude", "municipios_limitrofes", "educacao"
    ]
    
    # Mock data slightly realistic to test CSV typing
    df = pl.DataFrame({"cod_municipio": [1, 2], "ano": [2020, 2021], "valor": [10.5, 20.0], "texto": ["x", "y"]})
    for t in tabelas:
        df.write_parquet(processed_dir / f"{t}.parquet")
        
    qc = results_dir / "quality_checks.csv"
    with open(qc, "w", encoding="utf-8") as f:
        f.write("status\nOK\nOK\n")
        
    qs = results_dir / "quality_summary.csv"
    with open(qs, "w", encoding="utf-8") as f:
        f.write("col\n1\n")
        
    d = processed_dir / "dictionary.csv"
    with open(d, "w", encoding="utf-8") as f:
        f.write("col\n1\n")
        
    dj = tmp_path / "datasets.json"
    with open(dj, "w", encoding="utf-8") as f:
        f.write('[{"id": "t1", "nome": "T1", "periodo": "2020"}]')
        
    return data_dir, results_dir, dj

def test_empacotamento_falha_auditoria(fake_environment):
    data_dir, results_dir, dj = fake_environment
    qc = results_dir / "quality_checks.csv"
    with open(qc, "a", encoding="utf-8") as f:
        f.write("FALHA\n")
        
    with pytest.raises(RuntimeError, match="A auditoria crítica não está integralmente aprovada"):
        empacotamento.montar_pacote_final("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)

def test_empacotamento_arquivos_e_manifesto(fake_environment):
    data_dir, results_dir, dj = fake_environment
    empacotamento.montar_pacote_final("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)
    
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
    
    with open(final_dir / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["versao_dataset"] == "1.0.0"
    assert manifest["data_geracao"] == "2026-10-10"
    assert manifest["pacote_versao"] == "0.1.0"
    assert manifest["git_commit_pacote"] == "hash1"
    assert manifest["git_commit_projeto"] == "hash2"
    assert len(manifest["arquivos"]) == 16 # 6 parquet + 6 csv + 3 docs + 1 readme
    
    # Metadata por tabela no manifesto
    for item in manifest["arquivos"]:
        if item["formato"] in ("parquet", "csv.gz"):
            assert "janela_temporal" in item
            assert "chaves" in item
    
    # Testar determinismo real
    final2 = final_dir.parent / "final2"
    final_dir.rename(final2)
    empacotamento.montar_pacote_final("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)
    
    # Todos os arquivos idênticos byte a byte
    for f in arquivos_esperados:
        b1 = (final_dir / f).read_bytes()
        b2 = (final2 / f).read_bytes()
        assert b1 == b2, f"{f} não é determinístico"

    # Checar Parquet == Processed, CSV relido == Parquet
    for t in [
        "municipios", "demografia_economia_social", "financas_publicas",
        "saude", "municipios_limitrofes", "educacao"
    ]:
        pq_final = final_dir / f"{t}.parquet"
        pq_processed = data_dir / "processed" / f"{t}.parquet"
        assert pq_final.read_bytes() == pq_processed.read_bytes()
        
        df_pq = pl.read_parquet(pq_final)
        df_csv = pl.read_csv(final_dir / f"{t}.csv.gz", schema_overrides=df_pq.schema)
        assert df_pq.equals(df_csv)

    # Checar checksums
    checksum_file = final_dir / "checksums.sha256"
    assert checksum_file.exists()
    linhas_chk = checksum_file.read_text("utf-8").strip().split("\n")
    assert len(linhas_chk) == 17
    
    for line in linhas_chk:
        h, name = line.split(" *")
        assert empacotamento.calcular_sha256(final_dir / name) == h

    # Temporário apagado
    assert not (data_dir / "final_temp").exists()


def test_falha_atomica(fake_environment):
    data_dir, results_dir, dj = fake_environment
    empacotamento.montar_pacote_final("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)
    
    final_dir = data_dir / "final"
    hash_antes = empacotamento.calcular_sha256(final_dir / "municipios.parquet")
    
    # Simula erro durante a troca substituindo shutil.move por algo que cria parcialmente e quebra no meio
    orig_move = shutil.move
    def move_mock(src, dst):
        if str(src).endswith("final_temp") and str(dst).endswith("final"):
            # Partial move
            Path(dst).mkdir(parents=True, exist_ok=True)
            raise OSError("Erro simulado durante a substituição")
        return orig_move(src, dst)
        
    with mock.patch("shutil.move", side_effect=move_mock):
        with pytest.raises(OSError, match="Erro simulado durante a substituição"):
            empacotamento.montar_pacote_final("2.0.0", "2026-10-11", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)
            
    # O pacote não foi corrompido; backup foi restaurado
    assert final_dir.exists()
    assert empacotamento.calcular_sha256(final_dir / "municipios.parquet") == hash_antes
    assert not (data_dir / "final_backup").exists()
    assert not (data_dir / "final_temp").exists()

def test_manifest_validation_rejects_changes(fake_environment):
    data_dir, results_dir, dj = fake_environment
    # Test validation by monkeypatching json.load right when it is called for the programmatic validation
    
    orig_json_load = json.load
    
    def json_load_mock(f, **kwargs):
        loaded_manifest = orig_json_load(f, **kwargs)
        if "arquivos" in loaded_manifest:
            # Change sha256 to break validation
            loaded_manifest["arquivos"][0]["sha256"] = "xxx"
        return loaded_manifest
        
    with mock.patch("json.load", side_effect=json_load_mock):
        with pytest.raises(RuntimeError, match="Manifest sha256 mismatch"):
            empacotamento.montar_pacote_final("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)