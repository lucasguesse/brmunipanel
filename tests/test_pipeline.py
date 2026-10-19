"""Tests for the brmunipanel pipeline module."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

from brmunipanel import pipeline


def test_sources_stage_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests that download and harmonize stages call the expected functions in order."""
    calls: list[str] = []

    mock_sources = {
        "population": (
            lambda paths: calls.append("dl_pop"),
            lambda paths: calls.append("hm_pop"),
        ),
        "gdp": (
            lambda paths: calls.append("dl_gdp"),
            lambda paths: calls.append("hm_gdp"),
        ),
    }
    monkeypatch.setattr(pipeline, "SOURCES", mock_sources)

    pipeline.run_data(
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "out",
        sources=["population", "gdp"],
        stage="download",
    )
    assert calls == ["dl_pop", "dl_gdp"]

    calls.clear()
    pipeline.run_data(
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "out",
        sources=["population", "gdp"],
        stage="harmonize",
    )
    assert calls == ["hm_pop", "hm_gdp"]


def test_pipeline_paths_and_subfolders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests that source functions receive expected raw subfolders and intermediate output directory."""
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "out"

    received_paths: dict[str, Any] = {}

    from brmunipanel.ibge import population
    from brmunipanel.inep import ideb
    from brmunipanel.tesouro import siconfi_revenue
    import polars as pl

    dummy_df = pl.DataFrame({"x": [1]})
    monkeypatch.setattr(population, "harmonize", lambda sidra: received_paths.update({"sidra": sidra}) or dummy_df)
    monkeypatch.setattr(
        siconfi_revenue,
        "harmonize",
        lambda api_rev, muni: received_paths.update({"siconfi_api_revenue": api_rev}) or dummy_df,
    )
    monkeypatch.setattr(
        ideb,
        "harmonize",
        lambda ideb_dir, muni: received_paths.update({"ideb": ideb_dir}) or dummy_df,
    )

    from brmunipanel.ibge import territory
    monkeypatch.setattr(
        territory,
        "harmonize_municipalities",
        lambda t: pl.DataFrame({"municipality_code": ["1"]}),
    )

    # Put a dummy ibge_municipalities in intermediate
    inter = output_dir / "intermediate"
    inter.mkdir(parents=True, exist_ok=True)
    dummy_df.write_parquet(inter / "ibge_municipalities.parquet")

    pipeline.run_data(
        raw_dir=raw_dir,
        output_dir=output_dir,
        sources=["population", "siconfi_api_revenue", "inep_ideb"],
        stage="harmonize",
    )

    assert received_paths["sidra"] == raw_dir / "ibge" / "sidra"
    assert received_paths["siconfi_api_revenue"] == raw_dir / "tesouro" / "siconfi-api-revenue"
    assert received_paths["ideb"] == raw_dir / "inep" / "ideb"
    assert (output_dir / "intermediate" / "ibge_population.parquet").exists()
    assert (output_dir / "intermediate" / "tesouro_revenue_siconfi.parquet").exists()
    assert (output_dir / "intermediate" / "inep_ideb.parquet").exists()


def test_raw_sources_json_structure_and_ids() -> None:
    """Tests that raw_sources.json contains 18 sources with expected keys and unique IDs in order."""
    raw_sources_path = Path(__file__).resolve().parents[1] / "src" / "brmunipanel" / "metadata" / "raw_sources.json"
    assert raw_sources_path.exists()

    with open(raw_sources_path, "r", encoding="utf-8") as f:
        sources = json.load(f)

    assert len(sources) == 18

    expected_keys = {"id", "institution", "product", "access", "period", "raw_folder", "manifest_keys"}
    expected_ids = [
        "ibge_populacao_municipal",
        "ibge_pib_vab_municipal",
        "ibge_cempre_unidades_locais",
        "siconfi_despesas_por_funcao",
        "tesouro_finbra_despesas_por_funcao",
        "tesouro_finbra_receitas",
        "siconfi_receitas_anexo_ic",
        "ipea_bolsa_familia",
        "datasus_cnes_tabnet",
        "datasus_sim_tabnet",
        "datasus_sinasc_tabnet",
        "ibge_dtb_2025",
        "ibge_municipios_limitrofes_2024",
        "ibge_areas_territoriais_2025",
        "ibge_localidades_2022",
        "inep_censo_escolar",
        "inep_censo_superior",
        "inep_ideb_rede_publica",
    ]

    actual_ids = []
    for item in sources:
        assert set(item.keys()) == expected_keys
        actual_ids.append(item["id"])

    assert actual_ids == expected_ids
    assert len(set(actual_ids)) == 18


def test_manifest_keys_regexes_compile() -> None:
    """Tests that all 18 manifest_keys expressions compile with re.compile."""
    raw_sources_path = Path(__file__).resolve().parents[1] / "src" / "brmunipanel" / "metadata" / "raw_sources.json"
    with open(raw_sources_path, "r", encoding="utf-8") as f:
        sources = json.load(f)

    for item in sources:
        pattern = item["manifest_keys"]
        compiled = re.compile(pattern)
        assert compiled is not None


def test_source_order_and_dependency_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests that territory is first, population is before tabnet, and harmonize runs cleanly on empty output."""
    source_names = list(pipeline.SOURCES)
    assert source_names[0] == "territory"
    assert source_names.index("population") < source_names.index("tabnet")

    # Mock functions to create simulated parquet files when executed and verify dependencies
    mock_sources = {}
    for name in source_names:
        def make_harm(sname: str):
            def harm(paths: pipeline.Paths):
                inter = paths.intermediate_dir
                if sname in ("school_census", "higher_education_census", "inep_ideb", "tabnet"):
                    if not (inter / "ibge_municipalities.parquet").exists():
                        raise FileNotFoundError(f"ibge_municipalities missing for {sname}")
                if sname == "tabnet":
                    if not (inter / "ibge_population.parquet").exists():
                        raise FileNotFoundError(f"ibge_population missing for {sname}")

                inter.mkdir(parents=True, exist_ok=True)
                if sname == "territory":
                    (inter / "ibge_municipalities.parquet").touch()
                    (inter / "ibge_neighboring_municipalities.parquet").touch()
                elif sname == "population":
                    (inter / "ibge_population.parquet").touch()
                else:
                    (inter / f"{sname}.parquet").touch()
            return harm

        mock_sources[name] = (lambda paths: None, make_harm(name))

    monkeypatch.setattr(pipeline, "SOURCES", mock_sources)

    empty_out = tmp_path / "empty_out"
    pipeline.run_data(
        raw_dir=tmp_path / "raw",
        output_dir=empty_out,
        stage="harmonize",
    )

    assert (empty_out / "intermediate" / "ibge_municipalities.parquet").exists()
    assert (empty_out / "intermediate" / "ibge_population.parquet").exists()
