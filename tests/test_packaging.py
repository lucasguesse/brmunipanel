import json
import shutil
from pathlib import Path
from unittest import mock

import polars as pl
import pytest

from brmunipanel import packaging

@pytest.fixture
def fake_environment(tmp_path):
    data_dir = tmp_path / "data"
    processed_dir = data_dir / "processed"
    results_dir = tmp_path / "results"
    processed_dir.mkdir(parents=True)
    results_dir.mkdir(parents=True)

    tables = [
        "municipalities", "socioeconomic", "public_finance",
        "health", "neighboring_municipalities", "education"
    ]

    # Mock data slightly realistic to test CSV typing
    df = pl.DataFrame({"municipality_code": [1, 2], "year": [2020, 2021], "value": [10.5, 20.0], "text": ["x", "y"]})
    for t in tables:
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
        f.write('[{"id": "t1", "name": "T1", "period": "2020"}]')

    return data_dir, results_dir, dj

def test_packaging_failure_audit(fake_environment):
    data_dir, results_dir, dj = fake_environment
    qc = results_dir / "quality_checks.csv"
    with open(qc, "a", encoding="utf-8") as f:
        f.write("FAIL\n")

    with pytest.raises(RuntimeError, match="The critical audit did not fully pass"):
        packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)

def test_packaging_files_and_manifest(fake_environment):
    data_dir, results_dir, dj = fake_environment
    packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)

    final_dir = data_dir / "final"
    assert final_dir.exists()

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

    generated_files = set([p.name for p in final_dir.iterdir() if p.is_file()])
    assert generated_files == expected_files

    with open(final_dir / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["dataset_version"] == "1.0.0"
    assert manifest["generation_date"] == "2026-10-10"
    assert manifest["package_version"] == "0.1.0"
    assert manifest["git_package_commit"] == "hash1"
    assert manifest["git_project_commit"] == "hash2"
    assert len(manifest["files"]) == 16 # 6 parquet + 6 csv + 3 docs + 1 readme

    # Metadata per table in the manifest
    for item in manifest["files"]:
        if item["format"] in ("parquet", "csv.gz"):
            assert "time_window" in item
            assert "keys" in item

    # Test real determinism
    final2 = final_dir.parent / "final2"
    final_dir.rename(final2)
    packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)

    # All files identical byte-for-byte
    for f in expected_files:
        b1 = (final_dir / f).read_bytes()
        b2 = (final2 / f).read_bytes()
        assert b1 == b2, f"{f} is not deterministic"

    # Check Parquet == Processed, reread CSV == Parquet
    for t in [
        "municipalities", "socioeconomic", "public_finance",
        "health", "neighboring_municipalities", "education"
    ]:
        pq_final = final_dir / f"{t}.parquet"
        pq_processed = data_dir / "processed" / f"{t}.parquet"
        assert pq_final.read_bytes() == pq_processed.read_bytes()

        df_pq = pl.read_parquet(pq_final)
        df_csv = pl.read_csv(final_dir / f"{t}.csv.gz", schema_overrides=df_pq.schema)
        assert df_pq.equals(df_csv)

    # Check checksums
    checksum_file = final_dir / "checksums.sha256"
    assert checksum_file.exists()
    rows_chk = checksum_file.read_text("utf-8").strip().split("\n")
    assert len(rows_chk) == 17

    for line in rows_chk:
        h, name = line.split(" *")
        assert packaging.compute_sha256(final_dir / name) == h

    # Temporary removed
    assert not (data_dir / "final_temp").exists()


def test_atomic_failure(fake_environment):
    data_dir, results_dir, dj = fake_environment
    packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)

    final_dir = data_dir / "final"
    hash_before = packaging.compute_sha256(final_dir / "municipalities.parquet")

    # Simulate error during replacement by replacing shutil.move with something that creates partially and breaks halfway
    orig_move = shutil.move
    def move_mock(src, dst):
        if str(src).endswith("final_temp") and str(dst).endswith("final"):
            # Partial move
            Path(dst).mkdir(parents=True, exist_ok=True)
            raise OSError("Simulated error during the replacement")
        return orig_move(src, dst)

    with mock.patch("shutil.move", side_effect=move_mock):
        with pytest.raises(OSError, match="Simulated error during the replacement"):
            packaging.build_final_package("2.0.0", "2026-10-11", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)

    # The package was not corrupted; backup was restored
    assert final_dir.exists()
    assert packaging.compute_sha256(final_dir / "municipalities.parquet") == hash_before
    assert not (data_dir / "final_backup").exists()
    assert not (data_dir / "final_temp").exists()

def test_manifest_validation_rejects_changes(fake_environment):
    data_dir, results_dir, dj = fake_environment
    # Test validation by monkeypatching json.load right when it is called for the programmatic validation

    orig_json_load = json.load

    def json_load_mock(f, **kwargs):
        loaded_manifest = orig_json_load(f, **kwargs)
        if "files" in loaded_manifest:
            # Change sha256 to break validation
            loaded_manifest["files"][0]["sha256"] = "xxx"
        return loaded_manifest

    with mock.patch("json.load", side_effect=json_load_mock):
        with pytest.raises(RuntimeError, match="Manifest sha256 mismatch"):
            packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)


def test_packaging_license_doi_url(fake_environment):
    data_dir, results_dir, dj = fake_environment
    packaging.build_final_package(
        "1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj,
        dataset_license="CC-BY-4.0", doi="10.17632/abc.1", url="https://data.mendeley.com/datasets/abc/1",
    )
    final_dir = data_dir / "final"
    manifest = json.loads((final_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["license"] == "CC-BY-4.0"
    assert manifest["doi"] == "10.17632/abc.1"
    assert manifest["url"] == "https://data.mendeley.com/datasets/abc/1"
    readme = (final_dir / "README.md").read_text(encoding="utf-8")
    assert readme.endswith(
        "## Citation\nDOI: https://doi.org/10.17632/abc.1\nURL: https://data.mendeley.com/datasets/abc/1\nLicense: CC-BY-4.0\n"
    )
    assert "Pending" not in readme


def test_packaging_without_license_doi_url(fake_environment):
    data_dir, results_dir, dj = fake_environment
    packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)
    final_dir = data_dir / "final"
    manifest = json.loads((final_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["license"] is None
    assert manifest["doi"] is None
    assert manifest["url"] is None
    readme = (final_dir / "README.md").read_text(encoding="utf-8")
    assert readme.endswith("## Citation\nDOI: not assigned\nURL: not assigned\nLicense: not assigned\n")


def test_packaging_raw_sources_in_package(fake_environment):
    data_dir, results_dir, dj = fake_environment
    dj.write_text(
        '[{"id": "t1", "name": "T1", "period": "2020"},'
        ' {"id": "t2", "name": "T2", "period": "2021", "in_package": false},'
        ' {"id": "t3", "name": "T3", "period": "2022", "in_package": true}]',
        encoding="utf-8",
    )
    packaging.build_final_package("1.0.0", "2026-10-10", "0.1.0", "hash1", "hash2", data_dir, results_dir, dj)
    manifest = json.loads((data_dir / "final" / "manifest.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in manifest["raw_sources"]] == ["t1", "t3"]
    assert manifest["raw_sources"][1] == {"id": "t3", "name": "T3", "period": "2022"}


def test_citation_lines():
    assert packaging.citation_lines("CC-BY-4.0", "10.1/x", "https://u") == (
        "DOI: https://doi.org/10.1/x\nURL: https://u\nLicense: CC-BY-4.0\n"
    )
    assert packaging.citation_lines(None, None, None) == "DOI: not assigned\nURL: not assigned\nLicense: not assigned\n"
