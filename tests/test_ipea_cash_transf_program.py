"""Tests for the brmunipanel.ipea.cash_transf_program module."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import polars as pl
import pytest

from brmunipanel.ipea import cash_transf_program
from brmunipanel.core import InvalidResponse

FOLDER_DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture
def raw_folder_sample(tmp_path: Path) -> Path:
    """Prepare a mock raw data folder with real samples compressed in gzip."""
    sample_fam = FOLDER_DATA / "ipea_FAM_PBF_sample.json"
    sample_val = FOLDER_DATA / "ipea_VAL_PBF_sample.json"

    content_fam = sample_fam.read_bytes()
    content_val = sample_val.read_bytes()

    (tmp_path / "FAM_PBF.json.gz").write_bytes(gzip.compress(content_fam, mtime=0))
    (tmp_path / "VAL_PBF.json.gz").write_bytes(gzip.compress(content_val, mtime=0))

    meta_val = json.dumps({"value": [{"SERCODIGO": "VAL_PBF", "UNINOME": "R$ (mil)"}]}).encode("utf-8")
    (tmp_path / "VAL_PBF_metadata.json.gz").write_bytes(gzip.compress(meta_val, mtime=0))

    return tmp_path


def test_harmonize_sample(raw_folder_sample: Path) -> None:
    df = cash_transf_program.harmonize(raw_folder_sample)

    # 1. Expected schema and types
    assert df.schema == {
        "municipality_code": pl.String,
        "year": pl.Int16,
        "cash_transf_benefits": pl.Int64,
        "cash_transf_value_thousand_brl": pl.Float64,
    }

    # 2. Window strictly 2006–2023
    assert df["year"].min() >= 2006
    assert df["year"].max() <= 2023

    # 3. Municipal rows only (7 digits, no state or Brazil code)
    codes = df["municipality_code"].unique().to_list()
    assert all(len(c) == 7 and c.isdigit() for c in codes)
    assert "0" not in codes
    assert "35" not in codes
    assert "12" not in codes

    # 4. Key (municipality_code, year) does not repeat
    duplicates = df.group_by(["municipality_code", "year"]).agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    assert duplicates.height == 0

    # 5. Municipality present only in FAM_PBF (1100015)
    rows_1100015 = df.filter(pl.col("municipality_code") == "1100015")
    assert rows_1100015.height > 0
    assert rows_1100015["cash_transf_benefits"].is_not_null().all()
    assert rows_1100015["cash_transf_value_thousand_brl"].is_null().all()

    # 6. Municipality created in 2013 (4212650) only enters the series from 2014 onwards
    rows_4212650 = df.filter(pl.col("municipality_code") == "4212650")
    assert rows_4212650["year"].min() == 2014
    assert rows_4212650["year"].max() == 2023

    # 7. No output column has 'razao' in its name
    assert not any("razao" in col for col in df.columns)


def test_validate_values() -> None:
    # Valid: more than 100 thousand items
    valid_content = json.dumps({"value": [1] * 100_001}).encode("utf-8")
    cash_transf_program.validate_values(valid_content)

    # Invalid: not JSON
    with pytest.raises(InvalidResponse, match="is not JSON"):
        cash_transf_program.validate_values(b"<html>erro</html>")

    # Invalid: without 'value'
    with pytest.raises(InvalidResponse, match="without the 'value' key"):
        cash_transf_program.validate_values(json.dumps({"data": []}).encode("utf-8"))

    # Invalid: 100 thousand items or fewer
    with pytest.raises(InvalidResponse, match="expected > 100,000"):
        cash_transf_program.validate_values(json.dumps({"value": [1] * 100_000}).encode("utf-8"))


def test_validate_metadata() -> None:
    # Valid: exactly 1 item
    valid_content = json.dumps({"value": [{"SERCODIGO": "FAM_PBF"}]}).encode("utf-8")
    cash_transf_program.validate_metadata(valid_content)

    # Invalid: empty
    with pytest.raises(InvalidResponse, match="expected exactly 1"):
        cash_transf_program.validate_metadata(json.dumps({"value": []}).encode("utf-8"))

    # Invalid: more than 1 item
    with pytest.raises(InvalidResponse, match="expected exactly 1"):
        cash_transf_program.validate_metadata(json.dumps({"value": [1, 2]}).encode("utf-8"))


def test_discard_invalid_codes(tmp_path: Path) -> None:
    """Codes with invalid format (e.g. 6 digits or alphanumeric) must be discarded."""
    data_fam = {
        "value": [
            {"NIVNOME": "Municípios", "TERCODIGO": "123456", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 10},
            {"NIVNOME": "Municípios", "TERCODIGO": "ABCDEFG", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 20},
            {"NIVNOME": "Municípios", "TERCODIGO": "3550308", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 30},
        ]
    }
    data_val = {
        "value": [
            {"NIVNOME": "Municípios", "TERCODIGO": "3550308", "VALDATA": "2020-12-01T00:00:00", "VALVALOR": 150.0},
        ]
    }
    (tmp_path / "FAM_PBF.json.gz").write_bytes(gzip.compress(json.dumps(data_fam).encode("utf-8"), mtime=0))
    (tmp_path / "VAL_PBF.json.gz").write_bytes(gzip.compress(json.dumps(data_val).encode("utf-8"), mtime=0))

    df = cash_transf_program.harmonize(tmp_path)
    assert df.height == 1
    assert df["municipality_code"].to_list() == ["3550308"]
    assert df["cash_transf_benefits"][0] == 30
    assert df["cash_transf_value_thousand_brl"][0] == 150.0


def test_check_unit(tmp_path: Path) -> None:
    # File does not exist
    assert cash_transf_program.check_unit(tmp_path) == ""

    # File exists
    meta = json.dumps({"value": [{"SERCODIGO": "VAL_PBF", "UNINOME": "R$ (mil)"}]}).encode("utf-8")
    (tmp_path / "VAL_PBF_metadata.json.gz").write_bytes(gzip.compress(meta, mtime=0))
    assert cash_transf_program.check_unit(tmp_path) == "R$ (mil)"


def test_requests() -> None:
    req_fam = cash_transf_program.series_request("FAM_PBF")
    assert req_fam.key == "FAM_PBF"
    assert req_fam.file == "FAM_PBF.json.gz"
    assert "FAM_PBF" in req_fam.url

    req_meta = cash_transf_program.metadata_request("VAL_PBF")
    assert req_meta.key == "VAL_PBF/metadata"
    assert req_meta.file == "VAL_PBF_metadata.json.gz"
    assert "Metadados('VAL_PBF')" in req_meta.url
