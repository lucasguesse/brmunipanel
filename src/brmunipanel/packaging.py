import csv
import gzip
import hashlib
import json
import shutil
from pathlib import Path

import polars as pl

METADATA_TABLES = {
    "municipalities": {"time_window": "DTB 2025, Area 2025, Coordinates 2022", "keys": ["municipality_code"]},
    "socioeconomic": {"time_window": "2006-2023", "keys": ["municipality_code", "year"]},
    "public_finance": {"time_window": "2006-2023", "keys": ["municipality_code", "year"]},
    "health": {"time_window": "2006-2023", "keys": ["municipality_code", "year"]},
    "neighboring_municipalities": {"time_window": "2024", "keys": ["municipality_code", "neighbor_municipality_code"]},
    "education": {"time_window": "2006-2023", "keys": ["municipality_code", "year"]},
}

def write_csv_gz(parquet_path: Path, csv_gz_path: Path) -> None:
    """Converts a Parquet file to a gzip-compressed CSV with deterministic mtime and maximum compression."""
    df = pl.read_parquet(parquet_path)
    csv_bytes = df.write_csv(null_value="").encode('utf-8')
    with open(csv_gz_path, "wb") as f_out:
        with gzip.GzipFile(fileobj=f_out, mode="wb", compresslevel=9, mtime=0, filename="") as gz_out:
            gz_out.write(csv_bytes)

def compute_sha256(path: Path) -> str:
    """Computes and returns the SHA-256 hexadecimal checksum of `path`."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def validate_critical_audit(quality_checks_path: Path) -> bool:
    """Returns True if the quality checks CSV exists and contains no FAIL records."""
    if not quality_checks_path.exists():
        return False
    with open(quality_checks_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["status"] == "FAIL":
                return False
    return True

def build_final_package(
    dataset_version: str,
    generation_date: str,
    package_version: str,
    package_commit: str,
    project_commit: str,
    data_dir: Path,
    results_dir: Path,
    datasets_json_path: Path
) -> None:
    """Builds the final public data package in `data/final` with Parquet, CSV, checksums, and metadata."""
    processed_dir = data_dir / "processed"
    final_dir = data_dir / "final"
    temp_dir = data_dir / "final_temp"
    backup_dir = data_dir / "final_backup"

    quality_checks_path = results_dir / "quality_checks.csv"
    quality_summary_path = results_dir / "quality_summary.csv"

    if not validate_critical_audit(quality_checks_path):
        raise RuntimeError("The critical audit did not fully pass.")

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        expected_tables = [
            "municipalities", "socioeconomic", "public_finance",
            "health", "neighboring_municipalities", "education"
        ]

        files_manifest = []

        for table in expected_tables:
            parquet_name = f"{table}.parquet"
            csv_name = f"{table}.csv.gz"

            source = processed_dir / parquet_name
            if not source.exists():
                raise FileNotFoundError(f"Expected file not found: {source}")

            target_parquet = temp_dir / parquet_name
            shutil.copy2(source, target_parquet)

            target_csv = temp_dir / csv_name
            write_csv_gz(source, target_csv)

            df = pl.read_parquet(target_parquet)

            if compute_sha256(source) != compute_sha256(target_parquet):
                raise RuntimeError(f"Copy failed: {parquet_name} is not byte-identical to the original")

            schema_overrides = df.schema
            df_csv = pl.read_csv(target_csv, null_values=[""], schema_overrides=schema_overrides)
            if not df.equals(df_csv, null_equal=True):
                raise RuntimeError(f"CSV reread failed: {csv_name} differs from the original Parquet")

            files_manifest.append({
                "name": parquet_name,
                "format": "parquet",
                "time_window": METADATA_TABLES[table]["time_window"],
                "keys": METADATA_TABLES[table]["keys"],
                "size_bytes": target_parquet.stat().st_size,
                "rows": df.height,
                "columns": df.width,
                "sha256": compute_sha256(target_parquet)
            })

            files_manifest.append({
                "name": csv_name,
                "format": "csv.gz",
                "time_window": METADATA_TABLES[table]["time_window"],
                "keys": METADATA_TABLES[table]["keys"],
                "size_bytes": target_csv.stat().st_size,
                "rows": df.height,
                "columns": df.width,
                "sha256": compute_sha256(target_csv)
            })

        dict_source = processed_dir / "dictionary.csv"
        dict_target = temp_dir / "dictionary.csv"
        shutil.copy2(dict_source, dict_target)
        files_manifest.append({
            "name": "dictionary.csv",
            "format": "csv",
            "size_bytes": dict_target.stat().st_size,
            "sha256": compute_sha256(dict_target)
        })

        qsum_target = temp_dir / "quality_summary.csv"
        shutil.copy2(quality_summary_path, qsum_target)
        files_manifest.append({
            "name": "quality_summary.csv",
            "format": "csv",
            "size_bytes": qsum_target.stat().st_size,
            "sha256": compute_sha256(qsum_target)
        })

        qchk_target = temp_dir / "quality_checks.csv"
        shutil.copy2(quality_checks_path, qchk_target)
        files_manifest.append({
            "name": "quality_checks.csv",
            "format": "csv",
            "size_bytes": qchk_target.stat().st_size,
            "sha256": compute_sha256(qchk_target)
        })

        readme_content = """# Brazilian Municipal Data Panel (2006-2023)

## Overview
This dataset provides a harmonized panel of Brazilian municipalities, covering the period from 2006 to 2023. It integrates data from various official sources to provide demographic, economic, social, public finance, health, and education indicators at the municipal level.

## Files and Formats
The dataset includes 6 canonical tables, provided in both Parquet (canonical) and compressed CSV (gzip) formats:
- `municipalities`: Territorial base and coordinates (Keys: municipality_code; Period: DTB 2025, Area 2025, Coordinates 2022).
- `socioeconomic`: Population, GDP, formal employment, and Bolsa Família beneficiaries (Keys: municipality_code, year; Period: 2006-2023).
- `public_finance`: Municipal budgetary expenses by function (Keys: municipality_code, year; Period: 2006-2023).
- `health`: Installed health capacity and basic mortality indicators (Keys: municipality_code, year; Period: 2006-2023).
- `education`: Basic and higher education aggregates, including IDEB (Keys: municipality_code, year; Period: 2006-2023).
- `neighboring_municipalities`: Geographic adjacency matrix between municipalities (Keys: municipality_code, neighbor_municipality_code; Period: 2024 adjacency).

Lines and Columns (Parquet/CSV):
- `municipalities`: 5,571 lines, 12 columns
- `socioeconomic`: 100,278 lines, 11 columns
- `public_finance`: 100,278 lines, 30 columns
- `health`: 100,278 lines, 11 columns
- `education`: 100,222 lines, 12 columns
- `neighboring_municipalities`: 32,952 lines, 3 columns

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
        readme_target = temp_dir / "README.md"
        with open(readme_target, "w", encoding="utf-8", newline="\n") as f:
            f.write(readme_content)
        files_manifest.append({
            "name": "README.md",
            "format": "md",
            "size_bytes": readme_target.stat().st_size,
            "sha256": compute_sha256(readme_target)
        })

        with open(datasets_json_path, "r", encoding="utf-8") as f:
            datasets = json.load(f)
        sources = [{"id": ds["id"], "name": ds["name"], "period": ds["period"]} for ds in datasets]

        manifest = {
            "dataset_version": dataset_version,
            "generation_date": generation_date,
            "package_version": package_version,
            "git_package_commit": package_commit,
            "git_project_commit": project_commit,
            "license": None,
            "doi": None,
            "url": None,
            "files": files_manifest,
            "raw_sources": sources
        }

        manifest_target = temp_dir / "manifest.json"
        with open(manifest_target, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.write("\n")

        checksums_target = temp_dir / "checksums.sha256"
        with open(checksums_target, "w", encoding="utf-8", newline="\n") as f:
            for am in sorted(files_manifest + [{"name": "manifest.json", "sha256": compute_sha256(manifest_target)}], key=lambda x: x["name"]):
                f.write(f"{am['sha256']} *{am['name']}\n")

        # Programmatic manifest validation
        with open(manifest_target, "r", encoding="utf-8") as f:
            loaded_manifest = json.load(f)

        for am in loaded_manifest["files"]:
            file_path = temp_dir / am["name"]
            if not file_path.exists():
                raise RuntimeError(f"Manifest claims {am['name']} but it does not exist.")
            if am["size_bytes"] != file_path.stat().st_size:
                raise RuntimeError(f"Manifest size mismatch for {am['name']}.")
            if am["sha256"] != compute_sha256(file_path):
                raise RuntimeError(f"Manifest sha256 mismatch for {am['name']}.")
            if am["format"] not in ["parquet", "csv.gz", "csv", "md"]:
                raise RuntimeError(f"Manifest unexpected format {am['format']} for {am['name']}.")
            if "time_window" in am:
                table = am["name"].split(".")[0]
                if am["time_window"] != METADATA_TABLES[table]["time_window"]:
                    raise RuntimeError(f"Manifest janela_temporal mismatch for {am['name']}.")
                if set(am["keys"]) != set(METADATA_TABLES[table]["keys"]):
                    raise RuntimeError(f"Manifest keys mismatch for {am['name']}")

                # Check lines and columns
                df = pl.read_parquet(temp_dir / f"{table}.parquet")
                if am["rows"] != df.height:
                    raise RuntimeError(f"Manifest rows mismatch for {am['name']}")
                if am["columns"] != df.width:
                    raise RuntimeError(f"Manifest columns mismatch for {am['name']}")

        expected_files = set([
            "municipalities.parquet", "municipalities.csv.gz",
            "socioeconomic.parquet", "socioeconomic.csv.gz",
            "public_finance.parquet", "public_finance.csv.gz",
            "health.parquet", "health.csv.gz",
            "neighboring_municipalities.parquet", "neighboring_municipalities.csv.gz",
            "education.parquet", "education.csv.gz",
            "dictionary.csv", "quality_summary.csv", "quality_checks.csv",
            "manifest.json", "checksums.sha256", "README.md"
        ])
        files_temp = set([p.name for p in temp_dir.iterdir() if p.is_file()])

        if expected_files != files_temp:
            raise RuntimeError(f"Invalid temporary folder. Missing: {expected_files - files_temp}. Extra: {files_temp - expected_files}")

        with open(checksums_target, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                h_expected, fname = line.strip().split(" *")
                if compute_sha256(temp_dir / fname) != h_expected:
                    raise RuntimeError(f"Checksum mismatch for {fname}")

        # Atomicity in replacement
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
