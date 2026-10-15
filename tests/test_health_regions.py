"""Tests for the brmunipanel.datasus.health_regions module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from brmunipanel import core
from brmunipanel.datasus import health_regions
from brmunipanel.core import InvalidResponse

FOLDER_DATA = Path(__file__).resolve().parent / "data"


class FakeResponse:
    def __init__(self, data: dict):
        self.status_code = 200
        self.content = json.dumps(data).encode("utf-8")

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def __init__(self, pages: list[list[dict[str, Any]]]):
        self.pages = pages
        self.calls = 0

    def get(self, url: str, headers: dict | None = None, timeout: float | None = None) -> FakeResponse:
        if self.calls >= len(self.pages):
            raise RuntimeError(f"Unexpected call beyond the total number of pages ({self.calls})")
        data = {"macrorregiao_regiao_saude_municipios": self.pages[self.calls]}
        self.calls += 1
        return FakeResponse(data)


def test_validate() -> None:
    # Valid
    valid_content = json.dumps({"macrorregiao_regiao_saude_municipios": []}).encode("utf-8")
    health_regions.validate(valid_content)

    # Invalid: not JSON
    with pytest.raises(InvalidResponse, match="is not a JSON object|Invalid content"):
        health_regions.validate(b"<html>404 Not Found</html>")

    # Invalid: missing key
    with pytest.raises(InvalidResponse, match="is not a list"):
        health_regions.validate(json.dumps({"data": []}).encode("utf-8"))


def test_process_items() -> None:
    path_sample = FOLDER_DATA / "health_regions_sample.json"
    data = json.loads(path_sample.read_text(encoding="utf-8"))
    items = data["macrorregiao_regiao_saude_municipios"]

    # Add a mock item with code without match in DTB (e.g. 999999)
    items_with_invalid = list(items) + [
        {
            "codigo_municipio": "999999",
            "codigo_regiao_saude": "99999",
            "regiao_saude": "REGIAO INEXISTENTE",
            "codigo_macrorregiao_saude": "9901",
            "macrorregiao_saude": "MACRO INEXISTENTE",
        }
    ]

    # Mock DTB municipalities containing only the 5 valid sample municipalities
    municipalities = pl.DataFrame({
        "municipality_code": ["1200013", "1200054", "1200104", "1200138", "1200179"],
        "municipality_code_6": ["120001", "120005", "120010", "120013", "120017"],
    })

    df, discarded = health_regions.process_items(items_with_invalid, municipalities)

    # 1. Schema and types
    assert df.schema == {
        "municipality_code": pl.String,
        "health_region_code": pl.String,
        "health_region_name": pl.String,
        "health_macroregion_code": pl.String,
        "health_macroregion_name": pl.String,
    }

    # 2. Conversion from 6 to 7 digits and total valid
    assert df.height == 5
    assert set(df["municipality_code"]) == {"1200013", "1200054", "1200104", "1200138", "1200179"}

    # 3. Code without match is discarded
    assert len(discarded) == 1
    assert discarded[0]["codigo_municipio"] == "999999"

    # 4. Absence of duplicate primary key
    assert df["municipality_code"].n_unique() == df.height


def test_repeated_code_raises_error() -> None:
    items_with_duplicate = [
        {"codigo_municipio": "120001", "codigo_regiao_saude": "12001", "regiao_saude": "R1", "codigo_macrorregiao_saude": "1201", "macrorregiao_saude": "M1"},
        {"codigo_municipio": "120001", "codigo_regiao_saude": "12002", "regiao_saude": "R2", "codigo_macrorregiao_saude": "1201", "macrorregiao_saude": "M1"},
    ]
    municipalities = pl.DataFrame({"municipality_code": ["1200013"], "municipality_code_6": ["120001"]})
    with pytest.raises(ValueError, match="repeated"):
        health_regions.process_items(items_with_duplicate, municipalities)


def test_pagination_with_fake_session(tmp_path: Path) -> None:
    p1 = [{"codigo_municipio": f"11000{i}"} for i in range(1, 4)]
    p2 = [{"codigo_municipio": f"11000{i}"} for i in range(4, 7)]
    p3 = [{"codigo_municipio": f"11000{i}"} for i in range(7, 9)]
    p4 = []

    session = FakeSession([p1, p2, p3, p4])

    records = health_regions.download(tmp_path, session=session, interval=0.0)

    # 4 requests made on first run
    assert session.calls == 4
    assert [r["file"] for r in records] == [
        "health_regions_offset0000.json.gz",
        "health_regions_offset0003.json.gz",
        "health_regions_offset0006.json.gz",
        "health_regions_offset0008.json.gz",
    ]

    manifest = core.read_manifest(tmp_path)
    assert sorted(manifest.keys()) == ["offset0000", "offset0003", "offset0006", "offset0008"]

    # Second call on the same folder makes no requests
    records2 = health_regions.download(tmp_path, session=session, interval=0.0)
    assert session.calls == 4
    assert len(records2) == 4
