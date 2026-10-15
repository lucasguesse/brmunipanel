# BRMuniPanel

[![CI](https://github.com/lucasguesse/brmunipanel/actions/workflows/ci.yml/badge.svg)](https://github.com/lucasguesse/brmunipanel/actions/workflows/ci.yml)

**A Python ETL library and data access tool for the Harmonized Suite of Tables of Socioeconomic, Fiscal, Territorial, Health, and Educational Indicators for Brazilian Municipalities (2006–2023).**

## Overview
`brmunipanel` is an open-source Python library designed to fully automate the extraction, transformation, and loading (ETL) of public administrative records from multiple Brazilian federal agencies. It solves the massive structural burden of dealing with fragmented, historically inconsistent, and undocumented municipal data in Brazil.

By standardizing the 7-digit IBGE municipality code as the primary join key and freezing the territorial division to the 2025 canonical grid, this library allows researchers and data scientists to easily build and consume a longitudinal structural database of 5,571 municipalities, structured across six standardized tables: two territorial tables and four longitudinal thematic tables (Demographics/Economy/Social, Public Finances, Health, and Education).

This library provides the reproducible scientific protocol and supporting codebase for building the harmonized dataset of Brazilian municipal indicators.

## Key Features
- **Fully Reproducible ETL:** Transparent code that downloads raw data directly from official sources (IBGE, Tesouro Nacional/SICONFI, DATASUS, IPEA Data, INEP) and processes it systematically.
- **Harmonized Joins:** Automatically aligns historical data (2006–2023) against the most recent and stable territorial division grid (DTB 2025).
- **Thematic Modularity:** Provides six standardized tables:
  - `municipalities`: Canonical territorial crosswalk and municipal metadata (DTB 2025, territorial area in km², coordinates of municipal seat, border and coastal indicators).
  - `socioeconomic`: Longitudinal panel covering population estimates, municipal GDP, formal employment from CEMPRE, and Bolsa Família beneficiaries and transfers.
  - `public_finance`: Longitudinal panel covering municipal budgetary expenditures by functional classification (28 functions) combining FINBRA (2006–2012) and SICONFI (2013–2023).
  - `health`: Longitudinal panel covering health infrastructure, human resources, mortality, and live births from DATASUS (CNES, SIM, Sinasc).
  - `neighboring_municipalities`: Adjacency pairs identifying contiguous neighbor municipalities across Brazil.
  - `education`: Observed municipal panel aggregating microdata from School Census (Censo Escolar), Higher Education Census (Censo da Educação Superior), and observed public school IDEB scores across primary, lower secondary, and upper secondary education.
- **Extensive Metadata & Data Dictionaries:** Exposes variables with explicitly documented domain rules, missing value tracking, and schema changes over the years.
- **Performance:** Built on `polars`, which reads and aggregates the large municipal microdata files in memory.

## Installation

You can install the library from PyPI or from the source repository:

```bash
# Recommended: from PyPI
pip install brmunipanel

# From the GitHub repository
pip install git+https://github.com/lucasguesse/brmunipanel.git
```

## Quick Start (Usage Example)

The library exposes version metadata and source namespaces at top level, along with modular ETL and harmonization routines in each submodule:

```python
from pathlib import Path
import brmunipanel as bmp
from brmunipanel.ibge import population, gdp
from brmunipanel.ipea import cash_transf_program
from brmunipanel.inep import (
    harmonize_school_census,
    harmonize_higher_education_census,
    harmonize_ideb,
)
from brmunipanel.tesouro import siconfi, finbra
from brmunipanel.datasus import health

# Package version and source namespaces
print(bmp.__version__)
# Available namespaces: bmp.ibge, bmp.tesouro, bmp.ipea, bmp.datasus, bmp.inep

# Example: Harmonize population estimates from a local SIDRA raw folder
# df_pop = population.harmonize(Path("raw/ibge/sidra"))

# Example: Harmonize Bolsa Família records from an IPEA Data raw folder
# df_ctp = cash_transf_program.harmonize(Path("raw/ipea/cash-transf-program"))

# Example: Harmonize public school IDEB scores with municipal crosswalk
# df_ideb = harmonize_ideb(Path("raw/inep/ideb"), municipalities_df)
```

## Changes in 0.3.0

Version 0.3.0 names modules, functions, tables, columns, category values and manifest fields in English and is not compatible with 0.2.0. See [CHANGELOG.md](CHANGELOG.md) for the list of changes and for how to migrate a raw data folder downloaded with 0.2.0.

## Data Sources Handled
The library currently wraps and harmonizes the following official sources:
* **IBGE (Instituto Brasileiro de Geografia e Estatística):**
  * Population estimates (SIDRA Table 6579)
  * Municipal GDP (PIB Municipal, SIDRA Table 5938)
  * Central Register of Enterprises (CEMPRE, SIDRA Tables 1685 and 9509)
  * Territorial grids (DTB 2025, Area, Municipal Seat Coordinates, Adjacency matrices)
* **Tesouro Nacional (STN):**
  * FINBRA (2006–2012, budgetary expenditure by function)
  * SICONFI (2013–2023, budgetary expenditure by function)
* **IPEA Data (MDS):**
  * Programa Bolsa Família (beneficiaries and financial transfers, FAM_PBF / VAL_PBF)
* **Ministério da Saúde (DATASUS):**
  * CNES: Hospital beds, ICU capacity, diagnostic imaging equipment, and physicians per municipality
  * SIM: Violent deaths and infant mortality
  * Sinasc: Live births
  * Health Regions and Macro-regions
* **INEP (Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira):**
  * Censo Escolar: Active schools, enrollments, and teachers across basic education stages
  * Censo da Educação Superior: In-person higher education institutions and enrollments
  * IDEB: Observed public school scores across primary (anos iniciais), lower secondary (anos finais), and upper secondary (ensino médio) education

The INEP download server (`download.inep.gov.br`) sends its certificate without the intermediate certificate that signed it, which makes the default verification of `requests` fail. The package ships that intermediate certificate (RNP ICPEdu GR46 OV TLS CA 2025, issued by GlobalSign Root R46 and valid until November 2030) and uses it only for requests to that server. Certificate verification stays on.

## Development, Testing, and Building
To set up the library for local development, run tests, and build verifiable distribution packages according to the Python Packaging User Guide:

```bash
# 1. Clone repository and navigate to root
git clone https://github.com/lucasguesse/brmunipanel.git
cd brmunipanel

# 2. Create and activate a dedicated virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install in editable mode with development dependencies
pip install -e ".[dev]"

# 4. Run the linter and the full test suite
ruff check src tests
pytest

# 5. Build standard distribution artifacts (sdist and wheel)
# Ensure dist/ is clean before building
python -m build

# 6. Validate distribution artifacts strictly with Twine
python -m twine check --strict dist/*

# 7. Test installation of the built wheel in a separate, clean virtual environment
python -m venv .venv-clean
source .venv-clean/bin/activate  # On Windows: .venv-clean\Scripts\activate
pip install --no-deps dist/brmunipanel-*.whl
python -c "import brmunipanel as bmp; print(bmp.__version__)"
deactivate
```

> **Note on Publishing:** Distribution packages are published to PyPI by GitHub Actions with PyPA Trusted Publishing (OIDC), without persistent tokens or secrets, when a GitHub Release (`v*`) is published. Never commit API tokens, credentials, or `.pypirc` files to version control.

## How to Cite
If you use this library or its data routines in your research, please cite this software repository and specify the release version used while a definitive academic citation is not yet available:

- **Repository:** [https://github.com/lucasguesse/brmunipanel](https://github.com/lucasguesse/brmunipanel)
- **Release:** Specify the release tag or version used in your analysis.

A formal academic citation will be provided here once available.

## License
MIT License. See [LICENSE](LICENSE) for details.

