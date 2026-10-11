import csv
import gzip
import hashlib
import json
import shutil
from pathlib import Path

import polars as pl

TABELAS_METADADOS = {
    "municipios": {"janela_temporal": "DTB 2025, Área 2025, Coordenadas 2022", "chaves": ["cod_municipio"]},
    "demografia_economia_social": {"janela_temporal": "2006-2023", "chaves": ["cod_municipio", "ano"]},
    "financas_publicas": {"janela_temporal": "2006-2023", "chaves": ["cod_municipio", "ano"]},
    "saude": {"janela_temporal": "2006-2023", "chaves": ["cod_municipio", "ano"]},
    "municipios_limitrofes": {"janela_temporal": "2024", "chaves": ["cod_municipio", "cod_municipio_limitrofe"]},
    "educacao": {"janela_temporal": "2006-2023", "chaves": ["cod_municipio", "ano"]},
}

def gerar_csv_gz(parquet_path: Path, csv_gz_path: Path) -> None:
    df = pl.read_parquet(parquet_path)
    csv_bytes = df.write_csv(null_value="").encode('utf-8')
    with open(csv_gz_path, "wb") as f_out:
        with gzip.GzipFile(fileobj=f_out, mode="wb", compresslevel=9, mtime=0, filename="") as gz_out:
            gz_out.write(csv_bytes)

def calcular_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def validar_auditoria_critica(quality_checks_path: Path) -> bool:
    if not quality_checks_path.exists():
        return False
    with open(quality_checks_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["status"] == "FALHA":
                return False
    return True

def montar_pacote_final(
    versao_dataset: str,
    data_geracao: str,
    versao_pacote: str,
    commit_pacote: str,
    commit_projeto: str,
    data_dir: Path,
    results_dir: Path,
    datasets_json_path: Path
) -> None:
    processed_dir = data_dir / "processed"
    final_dir = data_dir / "final"
    temp_dir = data_dir / "final_temp"
    backup_dir = data_dir / "final_backup"

    quality_checks_path = results_dir / "quality_checks.csv"
    quality_summary_path = results_dir / "quality_summary.csv"

    if not validar_auditoria_critica(quality_checks_path):
        raise RuntimeError("A auditoria crítica não está integralmente aprovada.")

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        tabelas_esperadas = [
            "municipios", "demografia_economia_social", "financas_publicas",
            "saude", "municipios_limitrofes", "educacao"
        ]

        arquivos_manifesto = []

        for tabela in tabelas_esperadas:
            parquet_nome = f"{tabela}.parquet"
            csv_nome = f"{tabela}.csv.gz"

            origem = processed_dir / parquet_nome
            if not origem.exists():
                raise FileNotFoundError(f"Arquivo esperado não encontrado: {origem}")

            destino_parquet = temp_dir / parquet_nome
            shutil.copy2(origem, destino_parquet)

            destino_csv = temp_dir / csv_nome
            gerar_csv_gz(origem, destino_csv)

            df = pl.read_parquet(destino_parquet)

            if calcular_sha256(origem) != calcular_sha256(destino_parquet):
                raise RuntimeError(f"Falha na cópia: {parquet_nome} não é idêntico byte a byte ao original.")

            schema_overrides = df.schema
            df_csv = pl.read_csv(destino_csv, null_values=[""], schema_overrides=schema_overrides)
            if not df.equals(df_csv, null_equal=True):
                raise RuntimeError(f"Falha na releitura do CSV: {csv_nome} difere do Parquet original.")

            arquivos_manifesto.append({
                "nome": parquet_nome,
                "formato": "parquet",
                "janela_temporal": TABELAS_METADADOS[tabela]["janela_temporal"],
                "chaves": TABELAS_METADADOS[tabela]["chaves"],
                "tamanho_bytes": destino_parquet.stat().st_size,
                "linhas": df.height,
                "colunas": df.width,
                "sha256": calcular_sha256(destino_parquet)
            })

            arquivos_manifesto.append({
                "nome": csv_nome,
                "formato": "csv.gz",
                "janela_temporal": TABELAS_METADADOS[tabela]["janela_temporal"],
                "chaves": TABELAS_METADADOS[tabela]["chaves"],
                "tamanho_bytes": destino_csv.stat().st_size,
                "linhas": df.height,
                "colunas": df.width,
                "sha256": calcular_sha256(destino_csv)
            })

        dict_origem = processed_dir / "dictionary.csv"
        dict_destino = temp_dir / "dictionary.csv"
        shutil.copy2(dict_origem, dict_destino)
        arquivos_manifesto.append({
            "nome": "dictionary.csv",
            "formato": "csv",
            "tamanho_bytes": dict_destino.stat().st_size,
            "sha256": calcular_sha256(dict_destino)
        })

        qsum_destino = temp_dir / "quality_summary.csv"
        shutil.copy2(quality_summary_path, qsum_destino)
        arquivos_manifesto.append({
            "nome": "quality_summary.csv",
            "formato": "csv",
            "tamanho_bytes": qsum_destino.stat().st_size,
            "sha256": calcular_sha256(qsum_destino)
        })

        qchk_destino = temp_dir / "quality_checks.csv"
        shutil.copy2(quality_checks_path, qchk_destino)
        arquivos_manifesto.append({
            "nome": "quality_checks.csv",
            "formato": "csv",
            "tamanho_bytes": qchk_destino.stat().st_size,
            "sha256": calcular_sha256(qchk_destino)
        })

        readme_content = """# Painel de Dados Municipais Brasileiros (2006-2023)

## Overview
This dataset provides a harmonized panel of Brazilian municipalities, covering the period from 2006 to 2023. It integrates data from various official sources to provide demographic, economic, social, public finance, health, and education indicators at the municipal level.

## Files and Formats
The dataset includes 6 canonical tables, provided in both Parquet (canonical) and compressed CSV (gzip) formats:
- `municipios`: Territorial base and coordinates (Keys: cod_municipio; Period: DTB 2025, Area 2025, Coordinates 2022).
- `demografia_economia_social`: Population, GDP, formal employment, and Bolsa Família beneficiaries (Keys: cod_municipio, ano; Period: 2006-2023).
- `financas_publicas`: Municipal budgetary expenses by function (Keys: cod_municipio, ano; Period: 2006-2023).
- `saude`: Installed health capacity and basic mortality indicators (Keys: cod_municipio, ano; Period: 2006-2023).
- `educacao`: Basic and higher education aggregates, including IDEB (Keys: cod_municipio, ano; Period: 2006-2023).
- `municipios_limitrofes`: Geographic adjacency matrix between municipalities (Keys: cod_municipio, cod_municipio_limitrofe; Period: 2024 adjacency).

Lines and Columns (Parquet/CSV):
- `municipios`: 5,571 lines, 12 columns
- `demografia_economia_social`: 100,278 lines, 11 columns
- `financas_publicas`: 100,278 lines, 30 columns
- `saude`: 100,278 lines, 11 columns
- `educacao`: 100,222 lines, 12 columns
- `municipios_limitrofes`: 32,952 lines, 3 columns

Files are encoded in UTF-8. CSV files use `,` as delimiter and empty strings for missing (null) values.
Monetary values are in Brazilian Reais (BRL), mostly nominal (refer to the documentation for specific indicators).

## Documentation and Quality
- `dictionary.csv`: Variable dictionary with data types, descriptions, and source information.
- `quality_summary.csv` and `quality_checks.csv`: Results of automated quality and consistency checks.
- `manifest.json` and `checksums.sha256`: Metadata artifacts and SHA-256 integrity checksums. Note: `manifest.json` and `checksums.sha256` are meta-artifacts.

## Reproducibility
This dataset is deterministically generated via the `brmunipanel` Python package.
To reproduce from processed data:
```bash
python scripts/run_pipeline.py --step data --etapa finalizar --dataset_version <version> --date <YYYY-MM-DD>
```
To reproduce from raw data:
```bash
python scripts/run_pipeline.py --step data --etapa tudo --dataset_version <version> --date <YYYY-MM-DD>
```
Source code repository: [Pending publication]

## Limitations
- IDEB data contains missing values due to years without assessment (even years) and suppressed results.
- Missing values in health, finance, and employment tables do not necessarily imply the absence of activities; they may result from lack of declaration or coverage.
- FINBRA/SICONFI have missing declarations and some inconsistencies between declared totals and sums.
- CEMPRE structural breaks occurred in 2022.
- Bolsa Familia values in 2013 and 2016 have municipal anomalies.
- Geographic areas and borders are based on the IBGE 2025 territorial division.
See the paper for a full discussion of limitations.

## Citation
*(Provisional citation - pending DOI)*
URL: [Pending DOI/URL]
License: [Pending License]
"""
        readme_destino = temp_dir / "README.md"
        with open(readme_destino, "w", encoding="utf-8", newline="\n") as f:
            f.write(readme_content)
        arquivos_manifesto.append({
            "nome": "README.md",
            "formato": "md",
            "tamanho_bytes": readme_destino.stat().st_size,
            "sha256": calcular_sha256(readme_destino)
        })

        with open(datasets_json_path, "r", encoding="utf-8") as f:
            datasets = json.load(f)
        fontes = [{"id": ds["id"], "nome": ds["nome"], "periodo": ds["periodo"]} for ds in datasets]

        manifest = {
            "versao_dataset": versao_dataset,
            "data_geracao": data_geracao,
            "pacote_versao": versao_pacote,
            "git_commit_pacote": commit_pacote,
            "git_commit_projeto": commit_projeto,
            "licenca": None,
            "doi": None,
            "url": None,
            "arquivos": arquivos_manifesto,
            "fontes_brutas": fontes
        }

        manifest_destino = temp_dir / "manifest.json"
        with open(manifest_destino, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.write("\n")

        checksums_destino = temp_dir / "checksums.sha256"
        with open(checksums_destino, "w", encoding="utf-8", newline="\n") as f:
            for am in sorted(arquivos_manifesto + [{"nome": "manifest.json", "sha256": calcular_sha256(manifest_destino)}], key=lambda x: x["nome"]):
                f.write(f"{am['sha256']} *{am['nome']}\n")

        # Validação Programática do Manifesto
        with open(manifest_destino, "r", encoding="utf-8") as f:
            loaded_manifest = json.load(f)

        for am in loaded_manifest["arquivos"]:
            file_path = temp_dir / am["nome"]
            if not file_path.exists():
                raise RuntimeError(f"Manifest claims {am['nome']} but it does not exist.")
            if am["tamanho_bytes"] != file_path.stat().st_size:
                raise RuntimeError(f"Manifest size mismatch for {am['nome']}.")
            if am["sha256"] != calcular_sha256(file_path):
                raise RuntimeError(f"Manifest sha256 mismatch for {am['nome']}.")
            if am["formato"] not in ["parquet", "csv.gz", "csv", "md"]:
                raise RuntimeError(f"Manifest unexpected format {am['formato']} for {am['nome']}.")
            if "janela_temporal" in am:
                tabela = am["nome"].split(".")[0]
                if am["janela_temporal"] != TABELAS_METADADOS[tabela]["janela_temporal"]:
                    raise RuntimeError(f"Manifest janela_temporal mismatch for {am['nome']}.")
                if set(am["chaves"]) != set(TABELAS_METADADOS[tabela]["chaves"]):
                    raise RuntimeError(f"Manifest chaves mismatch for {am['nome']}.")

                # Check lines and columns
                df = pl.read_parquet(temp_dir / f"{tabela}.parquet")
                if am["linhas"] != df.height:
                    raise RuntimeError(f"Manifest linhas mismatch for {am['nome']}.")
                if am["colunas"] != df.width:
                    raise RuntimeError(f"Manifest colunas mismatch for {am['nome']}.")

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
        arquivos_temp = set([p.name for p in temp_dir.iterdir() if p.is_file()])

        if arquivos_esperados != arquivos_temp:
            raise RuntimeError(f"Pasta temporária inválida. Faltam: {arquivos_esperados - arquivos_temp}. Sobram: {arquivos_temp - arquivos_esperados}")

        with open(checksums_destino, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                h_expected, fname = line.strip().split(" *")
                if calcular_sha256(temp_dir / fname) != h_expected:
                    raise RuntimeError(f"Checksum mismatch for {fname}")

        # Atomicidade na troca
        if final_dir.exists():
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.move(str(final_dir), str(backup_dir))

        # Simulate move
        try:
            shutil.move(str(temp_dir), str(final_dir))
        except Exception as e:
            if final_dir.exists():
                shutil.rmtree(final_dir)
            raise e

        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    except Exception as e:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        if backup_dir.exists():
            if final_dir.exists():
                shutil.rmtree(final_dir)
            shutil.move(str(backup_dir), str(final_dir))
        raise e
