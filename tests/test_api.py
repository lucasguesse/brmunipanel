"""Tests for the public interface of the brmunipanel library.

Validates version, __all__, source namespaces, and importability of functions
documented in the README without any network calls.
"""

from pathlib import Path
import subprocess
import sys
import types
import brmunipanel as bmp



def test_package_version():
    """Validate that __version__ is defined, is a string, and matches the distribution version."""
    assert hasattr(bmp, "__version__")
    assert isinstance(bmp.__version__, str)
    assert bmp.__version__ == "0.2.0"


def test_public_api_all():
    """Validate that __all__ declares the version and canonical source namespaces."""
    assert hasattr(bmp, "__all__")
    esperados = {"__version__", "datasus", "ibge", "inep", "ipea", "tesouro"}
    assert set(bmp.__all__) == esperados
    for nome in bmp.__all__:
        assert hasattr(bmp, nome), f"Símbolo {nome} declarado em __all__ não existe no módulo"


def test_source_namespaces():
    """Validate that source namespaces are modules directly accessible in bmp."""
    assert isinstance(bmp.datasus, types.ModuleType)
    assert isinstance(bmp.ibge, types.ModuleType)
    assert isinstance(bmp.inep, types.ModuleType)
    assert isinstance(bmp.ipea, types.ModuleType)
    assert isinstance(bmp.tesouro, types.ModuleType)


def test_readme_quickstart_imports_and_callables():
    """Validate that all imports and functions documented in the README Quick Start are valid and callable."""
    from brmunipanel.ibge import populacao, pib
    from brmunipanel.ipea import pbf
    from brmunipanel.inep import (
        harmonizar_censo_escolar,
        harmonizar_censo_superior,
        harmonizar_ideb,
    )
    from brmunipanel.tesouro import siconfi, finbra
    from brmunipanel.datasus import saude

    # Harmonization functions documented in the README
    assert callable(populacao.harmonizar)
    assert callable(pib.harmonizar)
    assert callable(pbf.harmonizar)
    assert callable(harmonizar_censo_escolar)
    assert callable(harmonizar_censo_superior)
    assert callable(harmonizar_ideb)
    assert callable(siconfi.harmonizar)
    assert callable(finbra.harmonizar)
    assert callable(saude.harmonizar)


def test_from_import_submodules():
    """Validate that 'from brmunipanel import <namespace>' imports submodules correctly."""
    from brmunipanel import datasus, ibge, inep, ipea, tesouro

    assert isinstance(datasus, types.ModuleType)
    assert isinstance(ibge, types.ModuleType)
    assert isinstance(inep, types.ModuleType)
    assert isinstance(ipea, types.ModuleType)
    assert isinstance(tesouro, types.ModuleType)


def test_lazy_imports_clean_subprocess():
    """Validate that 'import brmunipanel' in a clean process does not load polars, pandas, or heavy modules."""
    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    code = (
        "import sys\n"
        f"if {src_dir!r} not in sys.path: sys.path.insert(0, {src_dir!r})\n"
        "import brmunipanel\n"
        "heavy_modules = {'polars', 'pandas', 'brmunipanel.nucleo', "
        "'brmunipanel.inep.censo_escolar', "
        "'brmunipanel.inep.censo_superior', "
        "'brmunipanel.inep.ideb'}\n"
        "loaded_heavy = heavy_modules.intersection(sys.modules)\n"
        "if loaded_heavy:\n"
        "    print(f'Módulos carregados indevidamente: {sorted(loaded_heavy)}')\n"
        "    sys.exit(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Processo limpo falhou: stdout={result.stdout}, stderr={result.stderr}"

