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

The keys are `municipality_code` and `year`. Expenditure columns use the prefix `exp_` (for example, `exp_health`). Every column, with its description, is listed in `metadata/variables.json`. In the School Census, special education columns are named `inclusive_ed`, `inclusive_ed_common_classes` and `inclusive_ed_exclusive_classes` (with the prefixes `enroll_`, `teachers_` and `classes_`).

Category values in the intermediate tables are in English: administrative dependency `federal`, `state`, `municipal` and `private`; location `urban` and `rural`; Higher Education Census category `federal`, `state`, `municipal`, `private` and `special`; population source `estimate` and `interpolated`. The FINBRA and SICONFI readers return `declares_intra_budgetary`.

### Download manifest

The manifest fields are `url`, `method`, `file`, `bytes`, `sha256`, `downloaded_at`, `body` and `parameters`. Some record keys and file names written by the downloads also changed: `school-census/` and `higher-education-census/` for the INEP censuses; `early_years/`, `final_years/` and `secondary/` for the IDEB keys; `health_regions_offset*` for the health regions pages; `t<table>/metadata` for SIDRA metadata; `<series>/metadata` for IPEA Data metadata; `neighboring_2024` and `localities_2022` for the territorial files; `annual_accounts_<year>` for the SICONFI portal files; `dca_annex_i_e_<year>.jsonl.gz` for the SICONFI API files; and English names for the TabNet tabulations (`cnes_inpatient_beds`, `sim_assault_deaths`, `sinasc_live_births` and others).

### Migrating a raw data folder

Version 0.3.0 does not read manifests written by 0.2.0. A record whose key did not change stops the download with an error, because its fields no longer match the request; a record whose key changed is downloaded again. Start a new raw data folder, or rename the manifest fields, record keys and files of the old folder as listed above, keeping the file contents unchanged.

## 0.2.0 and earlier

See the [GitHub releases](https://github.com/lucasguesse/brmunipanel/releases).
