"""Municipal budget revenue in 2013–2023 (SICONFI, Tesouro Nacional, Annex I-C of the annual accounts).

Reads the Annex I-C declarations collected from the Tesouro API by `siconfi.download_api(..., annex="I-C")`, one
gzip JSON Lines file per year with one line per municipality, and returns the eight columns of `revenue.SCHEMA`.

Accounts are read by their code (`cod_conta`). The annex uses three account codings, from 2013 to 2017, from 2018 to
2021 and from 2022 on, and `ACCOUNTS` gives, for each coding, the accounts summed into each column. Revenue items are
read in the gross revenue column, "Receitas Realizadas" in 2013 and "Receitas Brutas Realizadas" from 2014 on. The
deductions are read in the row of the current revenue total: the "Deduções da Receita" column in 2013 and the sum of
the three deduction columns from 2014 on, with the sign declared by the municipality. From 2018 on, the tax accounts
include fines, interest and overdue tax collection, which the coding of 2013 to 2017 records in separate accounts
that are not read here.

A municipality whose response has no items does not generate a row. In a response with items, a missing revenue
account is zero, except the current revenue total, which stays null and is reported as `no_current_revenue`.
Intra-budgetary revenue (accounts starting with "RI") is not read. Distrito Federal and codes outside the territorial
division are reported and skipped. Nothing is imputed or corrected.
"""
import gzip
import json
from pathlib import Path

import polars as pl

from brmunipanel import core
from brmunipanel.tesouro import revenue, siconfi

ANNEX = "I-C"
YEARS = siconfi.YEARS

ACCOUNTS = {
    "2013-2017": {
        "rev_current_gross": ("RO1.0.0.0.00.00.00",),
        "rev_iptu": ("RO1.1.1.2.02.00.00",),
        "rev_iss": ("RO1.1.1.3.05.00.00",),
        "rev_itbi": ("RO1.1.1.2.08.00.00",),
        "rev_fees": ("RO1.1.2.0.00.00.00",),
        "rev_fpm": ("RO1.7.2.1.01.02.00", "RO1.7.2.1.01.03.00", "RO1.7.2.1.01.04.00"),
        "rev_icms_share": ("RO1.7.2.2.01.01.00",),
    },
    "2018-2021": {
        "rev_current_gross": ("RO1.0.0.0.00.0.0",),
        "rev_iptu": ("RO1.1.1.8.01.1.0",),
        "rev_iss": ("RO1.1.1.8.02.3.0",),
        "rev_itbi": ("RO1.1.1.8.01.4.0",),
        "rev_fees": ("RO1.1.2.0.00.0.0",),
        "rev_fpm": ("RO1.7.1.8.01.2.0", "RO1.7.1.8.01.3.0", "RO1.7.1.8.01.4.0"),
        "rev_icms_share": ("RO1.7.2.8.01.1.0",),
    },
    "2022-2023": {
        "rev_current_gross": ("RO1.0.0.0.00.0.0",),
        "rev_iptu": ("RO1.1.1.2.50.0.0",),
        "rev_iss": ("RO1.1.1.4.51.1.0",),
        "rev_itbi": ("RO1.1.1.2.53.0.0",),
        "rev_fees": ("RO1.1.2.0.00.0.0",),
        "rev_fpm": ("RO1.7.1.1.51.0.0",),
        "rev_icms_share": ("RO1.7.2.1.50.0.0",),
    },
}


def coding(year: int) -> str:
    """Returns the key of `ACCOUNTS` for the account coding used in `year`."""
    if year <= 2017:
        return "2013-2017"
    if year <= 2021:
        return "2018-2021"
    return "2022-2023"


def gross_column(year: int) -> str:
    """Returns the name of the gross revenue column in `year`."""
    return "Receitas Realizadas" if year == 2013 else "Receitas Brutas Realizadas"


def deduction_columns(year: int) -> tuple[str, ...]:
    """Returns the names of the deduction columns in `year`."""
    if year == 2013:
        return ("Deduções da Receita",)
    return ("Deduções - FUNDEB", "Deduções - Transferências Constitucionais", "Outras Deduções da Receita")


def process_revenue_statement(items: list[dict], year: int) -> tuple[dict, list[str]]:
    """Extracts the eight revenue columns from the Annex I-C items of one municipality in `year`."""
    gross = gross_column(year)
    deductions = deduction_columns(year)
    accounts = ACCOUNTS[coding(year)]
    warnings = []
    values = {}
    for item in items:
        key = (item["cod_conta"], item["coluna"])
        if key in values:
            raise ValueError(f"Two rows for account {item['cod_conta']} in column {item['coluna']}")
        value = item["valor"]
        if value is None:
            value = 0.0
            warnings.append(f"null_value:{item['cod_conta']}")
        values[key] = float(value)
        if item["coluna"] != gross and item["coluna"] not in deductions and f"unknown_column:{item['coluna']}" not in warnings:
            warnings.append(f"unknown_column:{item['coluna']}")

    ret = {}
    for column, codes in accounts.items():
        if column == "rev_current_gross" and not any((code, gross) in values for code in codes):
            ret[column] = None
            warnings.append("no_current_revenue")
            continue
        ret[column] = sum(values.get((code, gross), 0.0) for code in codes)

    total = accounts["rev_current_gross"][0]
    declared = [values[(total, column)] for column in deductions if (total, column) in values]
    ret["rev_current_deductions"] = sum(declared)
    if any(v > 0 for v in declared) and any(v < 0 for v in declared):
        warnings.append("mixed_deduction_signs")
    return ret, warnings


def harmonize(folder: Path, municipalities: pl.DataFrame, report: list[dict] | None = None) -> pl.DataFrame:
    """Harmonizes SICONFI municipal budget revenue for 2013–2023 from the Annex I-C files, sorted by municipality and year."""
    folder = Path(folder)
    manifest = core.read_manifest(folder)
    valid_codes = set(municipalities["municipality_code"].to_list())
    rows = []
    for year in YEARS:
        key = siconfi.api_manifest_key(year, ANNEX)
        if key not in manifest:
            raise FileNotFoundError(f"Key {key} not found in the manifest. Run the download first")
        n_harmonized = 0
        for line in gzip.decompress((folder / manifest[key]["file"]).read_bytes()).decode("utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            muni_code = record["key"].split("/")[1]
            if len(muni_code) != 7:
                problem = "invalid_code"
            elif muni_code.startswith("53"):
                problem = "distrito_federal"
            elif muni_code not in valid_codes:
                problem = "outside_dtb"
            else:
                problem = None
            items = json.loads(record["body"])["items"]
            if problem is None and not items:
                problem = "no_declaration"
            if problem is not None:
                if report is not None:
                    report.append({"municipality_code": muni_code, "year": year, "type": problem})
                continue

            ret, warnings = process_revenue_statement(items, year)
            if report is not None:
                for warning in warnings:
                    report.append({"municipality_code": muni_code, "year": year, "type": warning})
            ret["municipality_code"] = muni_code
            ret["year"] = year
            rows.append(ret)
            n_harmonized += 1
        print(f"SICONFI revenue {year}: {n_harmonized} municipalities harmonized")

    return pl.DataFrame(rows, schema=revenue.SCHEMA).sort(["municipality_code", "year"])
