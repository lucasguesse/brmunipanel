# Changelog

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

The quality check on the length of shared boundaries is named `non-negative lengths`.

## 0.2.0 and earlier

See the [GitHub releases](https://github.com/lucasguesse/brmunipanel/releases).
