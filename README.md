# br-municipios-panel (Nome Provisório)

**A Python ETL library and data access tool for the Harmonized Panel of Socioeconomic, Fiscal, Territorial, and Social Protection Indicators for Brazilian Municipalities (2006–2023).**

## Overview
`br-municipios-panel` is an open-source Python library designed to fully automate the extraction, transformation, and loading (ETL) of public administrative records from multiple Brazilian federal agencies. It solves the massive structural burden of dealing with fragmented, historically inconsistent, and undocumented municipal data in Brazil.

By standardizing the 7-digit IBGE municipality code as the primary join key and freezing the territorial division to the 2025 canonical grid, this library allows researchers and data scientists to easily build and consume a longitudinal structural database of 5,571 municipalities, structured across six tables: two territorial ones and four longitudinal thematic ones (Demographics/Economy/Social, Public Finances, Health, and Education).

This library is the official scientific protocol and companion codebase to the dataset published in our *Data in Brief* Data Article.

## Key Features
- **Fully Reproducible ETL:** Transparent code that downloads raw data directly from official sources (IBGE, Tesouro Nacional/SICONFI, DATASUS, IPEA Data, INEP) and processes it systematically.
- **Harmonized Joins:** Automatically aligns historical data (2006–2023) against the most recent and stable territorial division grid (DTB 2025).
- **Thematic Modularity:** Provides six standardized tables. The non-educational longitudinal tables share a complete grid of municipalities and years (can be joined or consumed in isolation). The educational table aggregates micro-data from School Census, Higher Education Census and public school IDEB scores, only storing observed combinations.
- **Extensive Metadada & Data Dictionaries:** Exposes variables with explicitly documented domain rules, missing value tracking, and schema changes over the years.
- **Highly Performant:** Built with `duckdb` and `polars`/`pyarrow` for blazing fast in-memory analytics of large municipal microdata.

## Installation

You can install the library directly from PyPI (once published) or from the source repository.

```bash
# Recommended via pip
pip install br-municipios-panel
```

## Quick Start (Usage Example)

```python
import br_municipios_panel as bmp

# Fetch municipal public finance data from SICONFI
finance_df = bmp.tesouro.get_siconfi_despesas(years=[2022])

# Fetch health infrastructure from DATASUS
health_df = bmp.datasus.get_health_infrastructure(years=[2020])
```

## Data Sources Handled
The library currently wraps and harmonizes the following official sources:
* **IBGE (Instituto Brasileiro de Geografia e Estatística):**
  * Population estimates
  * Municipal GDP (PIB Municipal)
  * Central Register of Enterprises (CEMPRE)
  * Territorial grids (DTB, Area, Geolocation, Adjacency matrices)
* **Tesouro Nacional (STN):**
  * FINBRA (2006-2012)
  * SICONFI (2013-2023)
* **IPEA Data (MDS):**
  * Bolsa Família numbers and financial volume
* **Ministério da Saúde (DATASUS):**
  * Hospital beds, ICU capacity, diagnostics equipment, and physicians per municipality.
* **INEP:**
  * School Census and Higher Education Census (general numbers).

## Reproducing the Full Pipeline
If you wish to re-run the entire pipeline from the raw datasets to the final parquet artifacts:

```bash
git clone https://github.com/your-org/artigo-01-base-clusterizacao.git
cd artigo-01-base-clusterizacao
pip install -e .
python scripts/run_pipeline.py --all
```

## How to Cite
If you use this library or the generated dataset in your research, please cite our Data Paper:

> **[Citação a ser preenchida após aceitação na Data in Brief]**

## License
MIT License. See [LICENSE](LICENSE) for details.
