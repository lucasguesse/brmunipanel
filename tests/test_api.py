"""Testes da interface pública da biblioteca br-municipios-panel.

Valida versão, __all__, namespaces de fontes e importabilidade de funções
documentadas no README sem qualquer chamada de rede.
"""

import types
import pytest
import br_municipios_panel as bmp


def test_package_version():
    """Valida que __version__ está definida, é string e coincide com a versão da distribuição."""
    assert hasattr(bmp, "__version__")
    assert isinstance(bmp.__version__, str)
    assert bmp.__version__ == "0.1.0"


def test_public_api_all():
    """Valida que __all__ declara a versão e os namespaces de fontes canônicos."""
    assert hasattr(bmp, "__all__")
    esperados = {"__version__", "datasus", "ibge", "inep", "ipea", "tesouro"}
    assert set(bmp.__all__) == esperados
    for nome in bmp.__all__:
        assert hasattr(bmp, nome), f"Símbolo {nome} declarado em __all__ não existe no módulo"


def test_source_namespaces():
    """Valida que os namespaces de fontes são módulos acessíveis diretamente em bmp."""
    assert isinstance(bmp.datasus, types.ModuleType)
    assert isinstance(bmp.ibge, types.ModuleType)
    assert isinstance(bmp.inep, types.ModuleType)
    assert isinstance(bmp.ipea, types.ModuleType)
    assert isinstance(bmp.tesouro, types.ModuleType)


def test_readme_quickstart_imports_and_callables():
    """Valida que todas as importações e funções documentadas no Quick Start do README são válidas e invocáveis."""
    from br_municipios_panel.ibge import populacao, pib
    from br_municipios_panel.ipea import pbf
    from br_municipios_panel.inep import (
        harmonizar_censo_escolar,
        harmonizar_censo_superior,
        harmonizar_ideb,
    )
    from br_municipios_panel.tesouro import siconfi, finbra
    from br_municipios_panel.datasus import saude

    # Funções de harmonização documentadas no README
    assert callable(populacao.harmonizar)
    assert callable(pib.harmonizar)
    assert callable(pbf.harmonizar)
    assert callable(harmonizar_censo_escolar)
    assert callable(harmonizar_censo_superior)
    assert callable(harmonizar_ideb)
    assert callable(siconfi.harmonizar)
    assert callable(finbra.harmonizar)
    assert callable(saude.harmonizar)
