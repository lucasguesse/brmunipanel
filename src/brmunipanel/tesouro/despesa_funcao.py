"""Esquema e classificação comuns de despesas por função do Tesouro Nacional.

A saída tem só as 28 funções da classificação funcional.
O total declarado e a despesa intraorçamentária são usados só nas conferências internas.
"""
import polars as pl
FUNCOES = [
    ("01", "Legislativa", "desp_01_legislativa"),
    ("02", "Judiciária", "desp_02_judiciaria"),
    ("03", "Essencial à Justiça", "desp_03_essencial_justica"),
    ("04", "Administração", "desp_04_administracao"),
    ("05", "Defesa Nacional", "desp_05_defesa_nacional"),
    ("06", "Segurança Pública", "desp_06_seguranca_publica"),
    ("07", "Relações Exteriores", "desp_07_relacoes_exteriores"),
    ("08", "Assistência Social", "desp_08_assistencia_social"),
    ("09", "Previdência Social", "desp_09_previdencia_social"),
    ("10", "Saúde", "desp_10_saude"),
    ("11", "Trabalho", "desp_11_trabalho"),
    ("12", "Educação", "desp_12_educacao"),
    ("13", "Cultura", "desp_13_cultura"),
    ("14", "Direitos da Cidadania", "desp_14_direitos_cidadania"),
    ("15", "Urbanismo", "desp_15_urbanismo"),
    ("16", "Habitação", "desp_16_habitacao"),
    ("17", "Saneamento", "desp_17_saneamento"),
    ("18", "Gestão Ambiental", "desp_18_gestao_ambiental"),
    ("19", "Ciência e Tecnologia", "desp_19_ciencia_tecnologia"),
    ("20", "Agricultura", "desp_20_agricultura"),
    ("21", "Organização Agrária", "desp_21_organizacao_agraria"),
    ("22", "Indústria", "desp_22_industria"),
    ("23", "Comércio e Serviços", "desp_23_comercio_servicos"),
    ("24", "Comunicações", "desp_24_comunicacoes"),
    ("25", "Energia", "desp_25_energia"),
    ("26", "Transporte", "desp_26_transporte"),
    ("27", "Desporto e Lazer", "desp_27_desporto_lazer"),
    ("28", "Encargos Especiais", "desp_28_encargos_especiais"),
]

ESQUEMA = {
    "cod_municipio": pl.String,
    "ano": pl.Int16,
    "fonte": pl.String,
    **{c_out: pl.Float64 for _, _, c_out in FUNCOES},
    "desp_total_funcoes": pl.Float64,
    "desp_intraorcamentaria": pl.Float64,
    "declara_intraorcamentaria": pl.Boolean,
}

COLUNAS_PUBLICADAS = ["cod_municipio", "ano"] + [f[2] for f in FUNCOES]
