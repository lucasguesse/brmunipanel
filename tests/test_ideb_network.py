from pathlib import Path
import zipfile

import pandas as pd
import polars as pl
import pytest

from brmunipanel.inep.ideb import harmonize_final_years_network


def _create_package(folder: Path, rows: list[dict]) -> Path:
    df_rows = [
        {"bla": "info"},
        {
            "SG_UF": "SG_UF",
            "CO_MUNICIPIO": "CO_MUNICIPIO",
            "NO_MUNICIPIO": "NO_MUNICIPIO",
            "REDE": "REDE",
            "VL_OBSERVADO_2005": "VL_OBSERVADO_2005",
            "VL_OBSERVADO_2007": "VL_OBSERVADO_2007",
        },
    ] + rows
    df = pd.DataFrame(df_rows)
    xlsx_path = folder / "temp.xlsx"
    df.to_excel(xlsx_path, index=False, header=False)

    package_zip = folder / "divulgacao_anos_finais_municipios_2025.zip"
    with zipfile.ZipFile(package_zip, "w") as z:
        z.write(xlsx_path, "divulgacao_anos_finais_municipios_2025/divulgacao_anos_finais_municipios_2025.xlsx")
        z.writestr("divulgacao_anos_finais_municipios_2025/leia-me.txt", "text")

    return package_zip


def test_final_years_network_values(tmp_path):
    rows = [
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Estadual",
            "VL_OBSERVADO_2005": "4,5",
            "VL_OBSERVADO_2007": "5.0",
        },
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Municipal",
            "VL_OBSERVADO_2005": "-",
            "VL_OBSERVADO_2007": "4.1",
        },
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Pública",
            "VL_OBSERVADO_2005": "4.6",
            "VL_OBSERVADO_2007": "4.9",
        },
        {
            "SG_UF": "SP",
            "CO_MUNICIPIO": "3550308",
            "NO_MUNICIPIO": "São Paulo",
            "REDE": "Federal",
            "VL_OBSERVADO_2005": "ND",
            "VL_OBSERVADO_2007": "6.2",
        },
    ]
    _create_package(tmp_path, rows)

    cadastro = pl.DataFrame({"municipality_code": ["1100015", "3550308"]})
    result = harmonize_final_years_network(tmp_path, cadastro)

    expected = [
        ("1100015", 2005, "municipal", None),
        ("1100015", 2005, "public", 4.6),
        ("1100015", 2005, "state", 4.5),
        ("1100015", 2007, "municipal", 4.1),
        ("1100015", 2007, "public", 4.9),
        ("1100015", 2007, "state", 5.0),
        ("3550308", 2005, "federal", None),
        ("3550308", 2007, "federal", 6.2),
    ]

    assert result.rows() == expected
    assert result.schema["year"] == pl.Int16
    assert result.schema["ideb_final_years"] == pl.Float64


def test_final_years_network_unknown_network(tmp_path):
    rows = [
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Privada",
            "VL_OBSERVADO_2005": "5.0",
            "VL_OBSERVADO_2007": "5.5",
        },
    ]
    _create_package(tmp_path, rows)
    cadastro = pl.DataFrame({"municipality_code": ["1100015"]})

    with pytest.raises(ValueError, match="REDE"):
        harmonize_final_years_network(tmp_path, cadastro)


def test_final_years_network_errors(tmp_path):
    folder_with_data = tmp_path / "pkg"
    folder_with_data.mkdir()
    rows = [
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Estadual",
            "VL_OBSERVADO_2005": "4,5",
            "VL_OBSERVADO_2007": "5.0",
        },
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Municipal",
            "VL_OBSERVADO_2005": "-",
            "VL_OBSERVADO_2007": "4.1",
        },
        {
            "SG_UF": "RO",
            "CO_MUNICIPIO": "1100015",
            "NO_MUNICIPIO": "Alta Floresta",
            "REDE": "Pública",
            "VL_OBSERVADO_2005": "4.6",
            "VL_OBSERVADO_2007": "4.9",
        },
        {
            "SG_UF": "SP",
            "CO_MUNICIPIO": "3550308",
            "NO_MUNICIPIO": "São Paulo",
            "REDE": "Federal",
            "VL_OBSERVADO_2005": "ND",
            "VL_OBSERVADO_2007": "6.2",
        },
    ]
    _create_package(folder_with_data, rows)

    cadastro = pl.DataFrame({"municipality_code": ["1100015"]})
    with pytest.raises(ValueError, match="codes outside the municipal registry"):
        harmonize_final_years_network(folder_with_data, cadastro)

    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()
    with pytest.raises(FileNotFoundError):
        harmonize_final_years_network(empty_folder, cadastro)
