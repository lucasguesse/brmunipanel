"""Orchestration pipeline for downloading, harmonizing, consolidating, and packaging datasets."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
import subprocess
from typing import Any, Callable

import polars as pl

import brmunipanel
from brmunipanel.datasus import health, health_regions, tabnet
from brmunipanel.ibge import cempre, gdp, population, territory
from brmunipanel.inep import higher_education_census, ideb, school_census
from brmunipanel.ipea import cash_transf_program
from brmunipanel.metadata import document
from brmunipanel import packaging, panel
from brmunipanel.tesouro import finbra, siconfi, siconfi_revenue


@dataclass
class Paths:
    """Directory layout for raw and generated data artifacts."""

    raw_dir: Path
    output_dir: Path
    results_dir: Path | None = None
    _intermediate_dir: Path | None = None
    _processed_dir: Path | None = None
    _final_dir: Path | None = None

    @property
    def intermediate_dir(self) -> Path:
        return self._intermediate_dir if self._intermediate_dir is not None else self.output_dir / "intermediate"

    @property
    def processed_dir(self) -> Path:
        return self._processed_dir if self._processed_dir is not None else self.output_dir / "processed"

    @property
    def final_dir(self) -> Path:
        return self._final_dir if self._final_dir is not None else self.output_dir / "final"

    @property
    def results(self) -> Path:
        return self.results_dir if self.results_dir is not None else self.output_dir / "results"

    @property
    def territory(self) -> Path:
        return self.raw_dir / "ibge" / "territory"

    @property
    def health_regions(self) -> Path:
        return self.raw_dir / "datasus" / "health-regions"

    @property
    def tabnet(self) -> Path:
        return self.raw_dir / "datasus" / "tabnet"

    @property
    def sidra(self) -> Path:
        return self.raw_dir / "ibge" / "sidra"

    @property
    def cash_transf_program(self) -> Path:
        return self.raw_dir / "ipea" / "cash-transf-program"

    @property
    def finbra(self) -> Path:
        return self.raw_dir / "tesouro" / "finbra"

    @property
    def siconfi_api(self) -> Path:
        return self.raw_dir / "tesouro" / "siconfi-api"

    @property
    def siconfi_api_revenue(self) -> Path:
        return self.raw_dir / "tesouro" / "siconfi-api-revenue"

    @property
    def inep(self) -> Path:
        return self.raw_dir / "inep"

    @property
    def ideb(self) -> Path:
        return self.raw_dir / "inep" / "ideb"


def _write(table: pl.DataFrame, name: str, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.parquet"
    table.write_parquet(target)
    print(f"{target.name}: {table.height:,} rows, {table.width} columns")


def _call_step(func: Callable[..., Any], paths: Paths) -> None:
    try:
        sig = inspect.signature(func)
        if len(sig.parameters) == 0:
            func()
        else:
            func(paths)
    except (ValueError, TypeError):
        try:
            func(paths)
        except TypeError:
            func()


def _harmonize_territory(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    _write(municipalities, "ibge_municipalities", paths.intermediate_dir)
    _write(
        territory.harmonize_neighboring(paths.territory, municipalities["municipality_code"]),
        "ibge_neighboring_municipalities",
        paths.intermediate_dir,
    )


def _harmonize_health_regions(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    _write(health_regions.harmonize(paths.health_regions, municipalities), "ms_health_regions", paths.intermediate_dir)


def _harmonize_tabnet(paths: Paths) -> None:
    municipalities = pl.read_parquet(paths.intermediate_dir / "ibge_municipalities.parquet")
    population_df = pl.read_parquet(paths.intermediate_dir / "ibge_population.parquet")
    _write(health.harmonize(paths.tabnet, municipalities, population_df), "datasus_health", paths.intermediate_dir)


def _harmonize_finbra(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    _write(finbra.harmonize(paths.finbra, municipalities), "tesouro_expenditure_by_function_finbra", paths.intermediate_dir)
    _write(finbra.harmonize_revenue(paths.finbra, municipalities), "tesouro_revenue_finbra", paths.intermediate_dir)


def _download_siconfi_api(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    siconfi.download_api(paths.siconfi_api, municipalities["municipality_code"].to_list())


def _download_siconfi_api_revenue(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    siconfi.download_api(paths.siconfi_api_revenue, municipalities["municipality_code"].to_list(), annex="I-C")


def _harmonize_siconfi_api_revenue(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    _write(siconfi_revenue.harmonize(paths.siconfi_api_revenue, municipalities), "tesouro_revenue_siconfi", paths.intermediate_dir)


def _harmonize_siconfi_api(paths: Paths) -> None:
    municipalities = territory.harmonize_municipalities(paths.territory)
    _write(siconfi.harmonize(paths.siconfi_api, municipalities, source="api"), "tesouro_expenditure_by_function_siconfi", paths.intermediate_dir)


SOURCES: dict[str, tuple[Callable[..., Any], Callable[..., Any] | None]] = {
    "territory": (lambda paths: territory.download(paths.territory), _harmonize_territory),
    "school_census": (
        lambda paths: school_census.download(paths.inep),
        lambda paths: _write(
            school_census.harmonize(paths.inep, pl.read_parquet(paths.intermediate_dir / "ibge_municipalities.parquet")),
            "inep_school_census",
            paths.intermediate_dir,
        ),
    ),
    "higher_education_census": (
        lambda paths: higher_education_census.download(paths.inep),
        lambda paths: _write(
            higher_education_census.harmonize(paths.inep, pl.read_parquet(paths.intermediate_dir / "ibge_municipalities.parquet")),
            "inep_higher_education_census",
            paths.intermediate_dir,
        ),
    ),
    "health_regions": (lambda paths: health_regions.download(paths.health_regions), _harmonize_health_regions),
    "population": (
        lambda paths: population.download(paths.sidra),
        lambda paths: _write(population.harmonize(paths.sidra), "ibge_population", paths.intermediate_dir),
    ),
    "tabnet": (lambda paths: tabnet.download(paths.tabnet), _harmonize_tabnet),
    "gdp": (
        lambda paths: gdp.download(paths.sidra),
        lambda paths: _write(gdp.harmonize(paths.sidra), "ibge_gdp", paths.intermediate_dir),
    ),
    "cempre": (
        lambda paths: cempre.download(paths.sidra),
        lambda paths: _write(cempre.harmonize(paths.sidra), "ibge_cempre", paths.intermediate_dir),
    ),
    "cash_transf_program": (
        lambda paths: cash_transf_program.download(paths.cash_transf_program),
        lambda paths: _write(cash_transf_program.harmonize(paths.cash_transf_program), "ipea_cash_transf_program", paths.intermediate_dir),
    ),
    "finbra": (lambda paths: finbra.download(paths.finbra), _harmonize_finbra),
    "siconfi_api": (_download_siconfi_api, _harmonize_siconfi_api),
    "siconfi_api_revenue": (_download_siconfi_api_revenue, _harmonize_siconfi_api_revenue),
    "inep_ideb": (
        lambda paths: ideb.download(paths.ideb),
        lambda paths: _write(
            ideb.harmonize(paths.ideb, pl.read_parquet(paths.intermediate_dir / "ibge_municipalities.parquet")),
            "inep_ideb",
            paths.intermediate_dir,
        ),
    ),
}


def _consolidate(paths: Paths, dict_generator: Callable[..., bool] | None = None) -> None:
    files = {
        "municipalities": "ibge_municipalities.parquet",
        "neighboring": "ibge_neighboring_municipalities.parquet",
        "population": "ibge_population.parquet",
        "gdp": "ibge_gdp.parquet",
        "cempre": "ibge_cempre.parquet",
        "finbra": "tesouro_expenditure_by_function_finbra.parquet",
        "siconfi": "tesouro_expenditure_by_function_siconfi.parquet",
        "finbra_revenue": "tesouro_revenue_finbra.parquet",
        "siconfi_revenue": "tesouro_revenue_siconfi.parquet",
        "cash_transf_program": "ipea_cash_transf_program.parquet",
        "health": "datasus_health.parquet",
        "school_census": "inep_school_census.parquet",
        "higher_education_census": "inep_higher_education_census.parquet",
        "ideb": "inep_ideb.parquet",
    }

    tables = {}
    for name, file in files.items():
        path = paths.intermediate_dir / file
        if not path.exists():
            raise FileNotFoundError(f"Missing file {file}: it comes from the 'harmonize' stage")
        tables[name] = pl.read_parquet(path)

    municipalities = panel.build_municipalities(tables["municipalities"])
    _write(municipalities, "municipalities", paths.processed_dir)

    expenditure = panel.build_expenditure(tables["finbra"], tables["siconfi"])
    revenue = panel.build_revenue(tables["finbra_revenue"], tables["siconfi_revenue"])

    pop_without_source = tables["population"].drop("population_source")

    socioeconomic = panel.build_longitudinal_table(
        municipalities,
        [pop_without_source, tables["gdp"], tables["cempre"], tables["cash_transf_program"]],
        table_name="socioeconomic",
    )
    _write(socioeconomic, "socioeconomic", paths.processed_dir)

    public_finance = panel.build_longitudinal_table(
        municipalities,
        [expenditure, revenue],
        table_name="public_finance",
    )
    _write(public_finance, "public_finance", paths.processed_dir)

    health_df = panel.build_longitudinal_table(
        municipalities,
        [tables["health"]],
        table_name="health",
    )
    _write(health_df, "health", paths.processed_dir)

    neighboring = panel.build_neighboring(municipalities, tables["neighboring"])
    _write(neighboring, "neighboring_municipalities", paths.processed_dir)

    education = panel.consolidate_education(
        tables["school_census"],
        tables["higher_education_census"],
        tables["ideb"],
    )
    _write(education, "education", paths.processed_dir)

    gen = dict_generator or document.generate_dictionaries
    success = gen(paths.intermediate_dir, paths.processed_dir, paths.results)
    if not success:
        raise RuntimeError("Critical failure in the dictionary and audit generation")


def get_package_commit() -> str | None:
    """Returns the Git commit hash of the package if located inside a repository."""
    try:
        pkg_dir = Path(__file__).resolve().parent
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(pkg_dir),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return commit if commit else None
    except Exception:
        return None


def _finalize(
    paths: Paths,
    dataset_version: str,
    date: str,
    dataset_license: str | None = None,
    doi: str | None = None,
    url: str | None = None,
    project_commit: str | None = None,
) -> None:
    print("== finalize")
    package_commit = get_package_commit()

    packaging.build_final_package(
        dataset_version=dataset_version,
        generation_date=date,
        package_version=brmunipanel.__version__,
        package_commit=package_commit,
        project_commit=project_commit,
        data_dir=paths.output_dir,
        results_dir=paths.results,
        dataset_license=dataset_license,
        doi=doi,
        url=url,
    )


def run_data(
    raw_dir: Path | str,
    output_dir: Path | str,
    sources: list[str] | None = None,
    stage: str = "all",
    dataset_version: str | None = None,
    date: str | None = None,
    dataset_license: str | None = None,
    doi: str | None = None,
    url: str | None = None,
    results_dir: Path | str | None = None,
    project_commit: str | None = None,
    dict_generator: Callable[..., bool] | None = None,
) -> None:
    """Executes the data pipeline across download, harmonize, consolidate, and finalize stages."""
    raw_path = Path(raw_dir)
    output_path = Path(output_dir)
    results_path = Path(results_dir) if results_dir is not None else None
    paths = Paths(raw_dir=raw_path, output_dir=output_path, results_dir=results_path)

    selected_sources = list(SOURCES) if sources is None else sources

    if stage in ("download", "harmonize", "all"):
        for name in selected_sources:
            if name not in SOURCES:
                raise ValueError(f"Unknown source '{name}'. Available sources: {list(SOURCES)}")
            download, harmonize = SOURCES[name]
            if stage in ("download", "all"):
                print(f"== {name}: download")
                _call_step(download, paths)
            if stage in ("harmonize", "all") and harmonize is not None:
                print(f"== {name}: harmonize")
                _call_step(harmonize, paths)

    if stage in ("consolidate", "all"):
        print("== consolidate")
        _consolidate(paths, dict_generator=dict_generator)

    if stage in ("finalize", "all"):
        if not dataset_version or not date:
            raise ValueError("--dataset-version and --date are required for the finalize stage")
        _finalize(paths, dataset_version, date, dataset_license, doi, url, project_commit)
