# Changelog

## 0.4.1

This release adds optional year selection to two harmonizers and documents the panel builder. Calls written for 0.4.0 keep working and return the same tables.

### Added

School Census year selection. `inep.school_census.harmonize` (exported as `inep.harmonize_school_census`) takes a keyword-only `years` argument. Omitting it, or passing `None`, keeps the 2006–2023 window; a nonempty sequence of distinct integers within that window reads only those years. Invalid selections raise `ValueError` before any file is read.

SICONFI year selection. `tesouro.siconfi.harmonize` takes a keyword-only `years` argument for the expenditures by function, read from the portal files or from the API. Omitting it, or passing `None`, keeps the 2013–2023 window; a selection must be a nonempty sequence of distinct integers within that window, and each selected year needs its manifest entry and its file. Invalid selections raise `ValueError`, and a missing entry or file still raises `FileNotFoundError`.

### Documentation

`panel.build_longitudinal_table` documents its inputs, key types, validations, left joins, null handling and exceptions, with a runnable example. The README shows year selection and the panel builder.

## 0.4.0

This release adds four education tables by school network, the 2011 mesoregions and microregions in the municipalities table, and two raw sources. Code written for 0.3.0 keeps working, and the six tables of 0.3.0 keep their contents, apart from four new columns in `municipalities`.

### Added

INEP school performance rates. The new module `inep.pass_rates` downloads the municipal pass, failure and dropout rates published by INEP for 2007 to 2025 (`download`, one file per year, with keys `pass-rates/<year>` in the folder `inep/pass-rates`) and harmonizes the rates of the final years of elementary education and of upper secondary education by municipality, year, location and school network (`harmonize`, also exported as `inep.harmonize_pass_rates`). Rates are kept as published, with null where the file shows `--`.

School Census by school network. `inep.school_census.harmonize_network` (exported as `inep.harmonize_school_census_network`) reads the School Census from 2007 to 2024 school by school, decoding the files as Latin-1 so that school names keep their accents. It returns one row per federal school and year, with a type of school derived from its names (`federal_network`, `military`, `laboratory_school`, `university_linked` and `other_federal`), and the enrolments of active schools by municipality, year and network (`federal_network`, `federal_other`, `state`, `municipal` and `private`). `inep.school_census.download_network` downloads the 2007–2024 files; `download` is unchanged.

IDEB by school network. `inep.ideb.harmonize_final_years_network` (exported as `inep.harmonize_ideb_final_years_network`) reads the state, municipal, public and federal results of the final years of elementary education from the 2025 municipal release, for the editions from 2005 to 2025.

Territorial division of 2011. `ibge.territory.download` also downloads the 2011 Brazilian Territorial Division (key `dtb_2011` in the folder `ibge/territory`), and `ibge.territory.harmonize_municipalities` adds `mesoregion_2011_code`, `mesoregion_2011_name`, `microregion_2011_code` and `microregion_2011_name`, the geographic mesoregions and microregions of the 1990 regional division, to the municipalities table. They are null for the six municipalities installed after 2011, and the codes identify the microregions, since four microregion names repeat across states.

Consolidation, audit and package. `panel.build_keyed_table` validates a table by its keys and sorts it. The consolidation writes `federal_schools`, `enrollment_network`, `pass_rates` and `ideb_final_years_network` next to the six tables of 0.3.0, with contracts and dictionary entries in English and Portuguese, and the final package carries the ten tables in Parquet and CSV. The audit checks that the three rates of a stage add up to 100, that rates lie between 0 and 100 and the IDEB between 0 and 10, that the upper secondary enrolment of the five networks adds up to `enroll_secondary` in `education`, that the federal networks match `federal_schools`, and that the IDEB of the public network matches `education`, with control totals for 2023, and it counts the 2011 mesoregions and microregions of the municipalities table. The pipeline gains the sources `pass_rates`, `school_census_network` and `ideb_network`, and `metadata/raw_sources.json` lists the pass rates and the 2011 Brazilian Territorial Division as new raw sources, twenty in all, and the School Census up to 2024.

## 0.3.0

This release names the whole public interface in English: modules, functions, parameters, table and column names, category values, messages and the fields of the download manifest. Official acronyms and the labels published by the sources (column names of the INEP microdata, TabNet headers, API fields, budget function names in FINBRA and SICONFI, and file names chosen by the sources) are kept as published.

It is not compatible with 0.2.0. Code, tables and raw data folders written for 0.2.0 must be updated.

### Modules

| 0.2.0 | 0.3.0 |
|---|---|
| `nucleo` | `core` |
| `painel` | `panel` |
| `empacotamento` | `packaging` |
| `metadata.auditoria`, `metadata.contratos`, `metadata.dicionario` | `metadata.audit`, `metadata.contracts`, `metadata.dictionary` |
| `metadata/variaveis.json` | `metadata/variables.json` |
| `datasus.regioes_saude`, `datasus.saude` | `datasus.health_regions`, `datasus.health` |
| `ibge.pib`, `ibge.populacao`, `ibge.territorio` | `ibge.gdp`, `ibge.population`, `ibge.territory` |
| `inep.censo_escolar`, `inep.censo_superior`, `inep.conexao` | `inep.school_census`, `inep.higher_education_census`, `inep.connection` |
| `ipea.pbf` | `ipea.cash_transf_program` |
| `tesouro.despesa_funcao` | `tesouro.expenditure_by_function` |

`datasus.tabnet`, `ibge.cempre`, `ibge.sidra`, `inep.ideb`, `tesouro.finbra` and `tesouro.siconfi` keep their names.

### Functions

The verbs follow one pattern: `baixar` became `download`, `harmonizar` became `harmonize`, `montar_*` became `build_*`, `consolidar_*` became `consolidate_*`, `ler_*` became `read_*`, `validar_*` became `validate_*` and `auditar_*` became `audit_*`. The INEP shortcuts are `harmonize_school_census`, `harmonize_higher_education_census` and `harmonize_ideb`.

### Tables and columns

| 0.2.0 | 0.3.0 |
|---|---|
| `municipios` | `municipalities` |
| `municipios_limitrofes` | `neighboring_municipalities` |
| `demografia_economia_social` | `socioeconomic` |
| `financas_publicas` | `public_finance` |
| `saude` | `health` |
| `educacao` | `education` |

The keys are `municipality_code` and `year`. Expenditure columns use the prefix `exp_` (for example, `exp_health`), and revenue columns the prefix `rev_` (for example, `rev_fpm`). Every column, with its description, is listed in `metadata/variables.json`. In the School Census, special education columns are named `inclusive_ed`, `inclusive_ed_common_classes` and `inclusive_ed_exclusive_classes` (with the prefixes `enroll_`, `teachers_` and `classes_`).

Category values in the intermediate tables are in English: administrative dependency `federal`, `state`, `municipal` and `private`; location `urban` and `rural`; Higher Education Census category `federal`, `state`, `municipal`, `private` and `special`; population source `estimate` and `interpolated`. The FINBRA and SICONFI readers return `declares_intra_budgetary`.

### Download manifest

The manifest fields are `url`, `method`, `file`, `bytes`, `sha256`, `downloaded_at`, `body` and `parameters`. Some record keys and file names written by the downloads also changed: `school-census/` and `higher-education-census/` for the INEP censuses; `early_years/`, `final_years/` and `secondary/` for the IDEB keys; `health_regions_offset*` for the health regions pages; `t<table>/metadata` for SIDRA metadata; `<series>/metadata` for IPEA Data metadata; `neighboring_2024` and `localities_2022` for the territorial files; `annual_accounts_<year>` for the SICONFI portal files; `dca_annex_i_e_<year>.jsonl.gz` for the SICONFI API files; and English names for the TabNet tabulations (`cnes_inpatient_beds`, `sim_assault_deaths`, `sinasc_live_births` and others).

### Migrating a raw data folder

Version 0.3.0 does not read manifests written by 0.2.0. A record whose key did not change stops the download with an error, because its fields no longer match the request; a record whose key changed is downloaded again. Start a new raw data folder, or rename the manifest fields, record keys and files of the old folder as listed above, keeping the file contents unchanged.

### Added

Budget revenue. `tesouro.revenue` defines eight revenue columns: `rev_current_gross` (gross current revenue), `rev_current_deductions` (current revenue deductions, with the sign declared by the municipality), `rev_iptu`, `rev_iss`, `rev_itbi`, `rev_fees`, `rev_fpm` and `rev_icms_share`. `tesouro.finbra.harmonize_revenue` reads them from table `Receita` of the FINBRA databases (2006–2012), through the new `tesouro.finbra.read_access_table`. The new module `tesouro.siconfi_revenue` reads them from Annex I-C of the annual accounts (2013–2023), which `tesouro.siconfi.download_api` now collects with `annex="I-C"`; the files are `dca_annex_i_c_<year>.jsonl.gz`, with manifest keys `dca_i_c_<year>` (`tesouro.siconfi.api_manifest_key`), and annex I-E keeps its names. `panel.build_revenue` combines the two sources, and `public_finance` carries the eight columns after the 28 expenditure columns. The audit accepts negative values in `rev_` columns, as it already did in `exp_` columns.

Data dictionary in English and Portuguese. `metadata.dictionary.build_table_dictionary` writes the unit, the source and the methodological note in both languages, in the columns `unit_en`, `unit_pt`, `source_en`, `source_pt`, `methodological_note_en` and `methodological_note_pt`, which replace `unit`, `source` and `methodological_note`. `metadata/variables.json` uses the same keys. The period of the three IDEB variables is now the years with values: 2007–2023, and 2017–2023 for upper secondary education.

Deposit metadata in the data package. `packaging.build_final_package` takes `dataset_license`, `doi` and `url`, writes them to the manifest and to the citation lines of the package README, and leaves out of the manifest the raw sources marked with `"in_package": false`.

Uncompressed CSV tables in the data package. `packaging.build_final_package` provides the six tables in Parquet and uncompressed UTF-8 CSV (replacing gzip-compressed CSV), using comma delimiters, empty strings for nulls and LF line endings. The package manifest records `format: "csv"` for these files.

Command-line interface `brmunipanel build` to execute the complete dataset pipeline (`download`, `harmonize`, `consolidate`, `finalize`) across raw and output directories.

Package dataset `metadata/raw_sources.json` listing the 18 official raw data sources, their accession methods, time periods, and manifest regex patterns.

Dictionary and quality audit module `metadata.document.generate_dictionaries` to generate data dictionaries and automated quality reports directly within the library.

The quality check on the length of shared boundaries is named `non-negative lengths`.

## 0.2.0 and earlier

See the [GitHub releases](https://github.com/lucasguesse/brmunipanel/releases).
