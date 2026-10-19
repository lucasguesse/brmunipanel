"""Dictionary and quality audit reports generation for intermediate and processed stages."""

from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl

from brmunipanel.metadata import audit, contracts, dictionary

DEFAULT_VARIABLES_JSON = Path(__file__).resolve().parent / "variables.json"


def get_key_cols(table: str, stage_contracts: dict) -> list[str]:
    """Returns key columns for a given table from stage contract or defaults to municipality_code and year."""
    if table in stage_contracts and "keys" in stage_contracts[table]:
        return stage_contracts[table]["keys"]
    return ["municipality_code", "year"]


def generate_dictionaries(
    intermediate_dir: Path,
    processed_dir: Path,
    results_dir: Path,
    var_json: Path | None = None,
) -> bool:
    """Generates dictionary.csv in intermediate and processed directories, plus quality checks and summaries."""
    print("Generating dictionaries and quality reports...")
    results_dir.mkdir(parents=True, exist_ok=True)

    var_json_path = var_json or DEFAULT_VARIABLES_JSON
    with open(var_json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    try:
        municipalities_df = pl.read_parquet(processed_dir / "municipalities.parquet")
    except Exception:
        print("Warning: municipalities.parquet not found, the boundary check will be limited")
        municipalities_df = None

    auditor = audit.QualityAuditor(municipalities_df)

    global_summary = None

    for stage, stage_dir in [("intermediate", intermediate_dir), ("processed", processed_dir)]:
        if not stage_dir.exists():
            continue

        dict_rows = []
        quality_summary_rows = []

        stage_contract = contracts.CONTRACTS.get(stage, {})
        found_files = []
        for f in sorted(os.listdir(stage_dir)):
            if f.endswith(".parquet") and not f.startswith("dictionary"):
                found_files.append(f.replace(".parquet", ""))

        auditor.audit_expected_files(stage, found_files, stage_contract)

        for table_name in found_files:
            df = pl.read_parquet(stage_dir / f"{table_name}.parquet")
            auditor.add_check(f"[{stage}] {table_name}", "file exists and opens", "OK", "Yes", "Yes")

            key_cols = get_key_cols(table_name, stage_contract)

            # Metadata semantics checks
            if stage in meta and table_name in meta[stage]:
                table_meta = meta[stage][table_name]
                try:
                    dict_df = dictionary.build_table_dictionary(df, table_name, table_meta, key_cols)
                    dict_rows.append(dict_df)
                except ValueError as e:
                    print(f"Dictionary error ({table_name}): {e}")
                    auditor.add_check(
                        f"[{stage}] {table_name}",
                        "complete metadata",
                        "FAIL",
                        str(e),
                        "No error",
                        "Critical: orphan or missing metadata",
                    )
            else:
                auditor.add_check(
                    f"[{stage}] {table_name}",
                    "complete metadata",
                    "FAIL",
                    "Missing from the JSON",
                    "Present",
                    "Critical: whole table without JSON metadata",
                )

            auditor.audit_schema(df, f"[{stage}] {table_name}", stage_contract)
            auditor.audit_period_and_counts(df, f"[{stage}] {table_name}", stage_contract)
            auditor.audit_control_totals(df, f"[{stage}] {table_name}")

            summary = audit.audit_summary_table(df, table_name, key_cols)
            summary["stage"] = stage
            quality_summary_rows.append(summary)

            auditor.audit_keys(df, f"[{stage}] {table_name}", key_cols)
            if table_name != "municipalities" and table_name != "ibge_municipalities":
                auditor.audit_municipal_codes(df, f"[{stage}] {table_name}")
            auditor.audit_negative_values(df, f"[{stage}] {table_name}")
            auditor.audit_geographic_domains(df, f"[{stage}] {table_name}")

        if dict_rows:
            full_dict = pl.concat(dict_rows)
            full_dict.write_csv(stage_dir / "dictionary.csv")
            print(f"[{stage}] Dictionary written: {stage_dir / 'dictionary.csv'} ({full_dict.height} rows)")

        if quality_summary_rows:
            schema = {
                "stage": pl.String,
                "file": pl.String,
                "rows": pl.Int64,
                "columns": pl.Int64,
                "key": pl.String,
                "key_duplicates": pl.Int64,
                "min_year": pl.String,
                "max_year": pl.String,
                "distinct_municipalities": pl.Int64,
                "null_cells": pl.Int64,
                "null_cells_percentage": pl.Float64,
            }
            summary_df = pl.DataFrame(quality_summary_rows, schema=schema)
            if global_summary is None:
                global_summary = summary_df
            else:
                global_summary = pl.concat([global_summary, summary_df])

    if global_summary is not None:
        global_summary = global_summary.sort(["stage", "file"])
        global_summary.write_csv(results_dir / "quality_summary.csv")
        print(f"Quality summary written: {results_dir / 'quality_summary.csv'}")

    checks_df = auditor.get_checks_df()
    checks_df.write_csv(results_dir / "quality_checks.csv")
    print(f"Quality checks written: {results_dir / 'quality_checks.csv'}")

    if auditor.has_critical_failure:
        print("Critical failures were found")
        return False
    return True
