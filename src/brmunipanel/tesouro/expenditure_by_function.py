"""Common schema and classification of expenditures by budget function from Tesouro Nacional.

The output contains only the 28 functions of the functional classification.
Declared total and intra-budgetary expenditure are used only in internal checks.
"""
import polars as pl
FUNCTIONS = [
    ("01", "Legislativa", "exp_01_legislative"),
    ("02", "Judiciária", "exp_02_judiciary"),
    ("03", "Essencial à Justiça", "exp_03_essential_to_justice"),
    ("04", "Administração", "exp_04_administration"),
    ("05", "Defesa Nacional", "exp_05_national_defense"),
    ("06", "Segurança Pública", "exp_06_public_security"),
    ("07", "Relações Exteriores", "exp_07_foreign_affairs"),
    ("08", "Assistência Social", "exp_08_social_assistance"),
    ("09", "Previdência Social", "exp_09_social_security"),
    ("10", "Saúde", "exp_10_health"),
    ("11", "Trabalho", "exp_11_labor"),
    ("12", "Educação", "exp_12_education"),
    ("13", "Cultura", "exp_13_culture"),
    ("14", "Direitos da Cidadania", "exp_14_citizenship_rights"),
    ("15", "Urbanismo", "exp_15_urban_planning"),
    ("16", "Habitação", "exp_16_housing"),
    ("17", "Saneamento", "exp_17_sanitation"),
    ("18", "Gestão Ambiental", "exp_18_environmental_management"),
    ("19", "Ciência e Tecnologia", "exp_19_science_technology"),
    ("20", "Agricultura", "exp_20_agriculture"),
    ("21", "Organização Agrária", "exp_21_agrarian_organization"),
    ("22", "Indústria", "exp_22_industry"),
    ("23", "Comércio e Serviços", "exp_23_commerce_services"),
    ("24", "Comunicações", "exp_24_communications"),
    ("25", "Energia", "exp_25_energy"),
    ("26", "Transporte", "exp_26_transport"),
    ("27", "Desporto e Lazer", "exp_27_sports_leisure"),
    ("28", "Encargos Especiais", "exp_28_special_charges"),
]

SCHEMA = {
    "municipality_code": pl.String,
    "year": pl.Int16,
    "source": pl.String,
    **{c_out: pl.Float64 for _, _, c_out in FUNCTIONS},
    "exp_total_functions": pl.Float64,
    "exp_intra_budgetary": pl.Float64,
    "declares_intra_budgetary": pl.Boolean,
}

PUBLISHED_COLUMNS = ["municipality_code", "year"] + [f[2] for f in FUNCTIONS]
