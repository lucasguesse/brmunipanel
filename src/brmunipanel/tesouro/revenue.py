"""Common schema of municipal budget revenue from Tesouro Nacional.

Eight columns: gross current revenue, its deductions, four own-source revenues (IPTU, ISS, ITBI and fees) and two
intergovernmental transfers (the FPM share and the ICMS share). Values are realized revenue in current reais. Revenue
items are gross, before deductions; the deductions keep the sign declared by the municipality.
"""
import polars as pl

REVENUE_COLUMNS = [
    "rev_current_gross",
    "rev_current_deductions",
    "rev_iptu",
    "rev_iss",
    "rev_itbi",
    "rev_fees",
    "rev_fpm",
    "rev_icms_share",
]

SCHEMA = {
    "municipality_code": pl.String,
    "year": pl.Int16,
    **{column: pl.Float64 for column in REVENUE_COLUMNS},
}
