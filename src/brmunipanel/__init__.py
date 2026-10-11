"""ETL library for a harmonized panel of Brazilian municipal indicators (IBGE, Tesouro Nacional, IPEA Data, DATASUS, INEP)."""

import importlib
from typing import TYPE_CHECKING

__version__ = "0.1.0"

_SUBMODULES = {
    "datasus",
    "ibge",
    "inep",
    "ipea",
    "tesouro",
}

__all__ = [
    "__version__",
    "datasus",
    "ibge",
    "inep",
    "ipea",
    "tesouro",
]

if TYPE_CHECKING:
    from brmunipanel import datasus, ibge, inep, ipea, tesouro


def __getattr__(name: str):
    if name in _SUBMODULES:
        module = importlib.import_module(f"brmunipanel.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__():
    return __all__

