"""ETL library for a harmonized panel of Brazilian municipal indicators (IBGE, Tesouro Nacional, IPEA Data, DATASUS, INEP)."""

from br_municipios_panel import datasus, ibge, inep, ipea, tesouro

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "datasus",
    "ibge",
    "inep",
    "ipea",
    "tesouro",
]
