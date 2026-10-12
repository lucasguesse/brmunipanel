"""Consolidation of the dataset into six tables.

The consolidated dataset has six tables: the central municipalities table, three thematic
longitudinal tables (demografia_economia_social, financas_publicas, saude), the 
municipios_limitrofes table, and the educacao table.
No function here fills nulls, removes rows, modifies values, or calculates derived columns.
"""

from typing import Sequence
import polars as pl

ANOS_PAINEL = tuple(range(2006, 2024))

def montar_municipios(municipios: pl.DataFrame) -> pl.DataFrame:
    if "cod_municipio" not in municipios.columns:
        raise ValueError("Falta cod_municipio")
    
    dups_mun = municipios.filter(municipios["cod_municipio"].is_duplicated())["cod_municipio"]
    if not dups_mun.is_empty():
        raise ValueError(f"municipios: {dups_mun.n_unique()} chaves repetidas. Exemplos: {dups_mun.head(3).to_list()}")
        
    cols = [
        "cod_municipio", "nome_municipio", "cod_uf", "sigla_uf", "nome_uf",
        "nome_rg_intermediaria", "nome_rg_imediata", "fronteira_internacional",
        "litoraneo", "area_km2", "latitude_sede", "longitude_sede"
    ]
    for c in cols:
        if c not in municipios.columns:
            raise ValueError(f"Falta coluna {c} em municipios")
            
    return municipios.select(cols).sort("cod_municipio")

import re

def montar_despesa(finbra: pl.DataFrame, siconfi: pl.DataFrame) -> pl.DataFrame:
    if list(finbra.columns) != list(siconfi.columns):
        raise ValueError(f"Colunas diferentes ou em ordem diferente entre finbra e siconfi. finbra: {finbra.columns}, siconfi: {siconfi.columns}")
        
    if dict(zip(finbra.columns, finbra.dtypes)) != dict(zip(siconfi.columns, siconfi.dtypes)):
        raise ValueError("Tipos diferentes entre finbra e siconfi")
        
    # Checks if the same municipality and year appear in both
    finbra_keys = set(finbra.select(["cod_municipio", "ano"]).iter_rows())
    siconfi_keys = set(siconfi.select(["cod_municipio", "ano"]).iter_rows())
    inter = finbra_keys & siconfi_keys
    if inter:
        raise ValueError(f"{len(inter)} casos do mesmo município e ano nas duas tabelas. Exemplos: {list(inter)[:3]}")
        
    saida = pl.concat([finbra, siconfi])
    
    # Rename desp_XX_nome to desp_nome
    rename_map = {}
    for c in saida.columns:
        m = re.match(r"desp_\d{2}_(.*)", c)
        if m:
            rename_map[c] = f"desp_{m.group(1)}"
            
    return saida.rename(rename_map).sort(["cod_municipio", "ano"])

def montar_tabela_longitudinal(municipios: pl.DataFrame, fontes: list[pl.DataFrame], anos: Sequence[int] = ANOS_PAINEL, nome_tabela: str = "tabela_longitudinal") -> pl.DataFrame:
    codigos_validos = set(municipios["cod_municipio"])
    
    # Grid of municipalities and years
    grade = municipios.select(["cod_municipio"]).join(
        pl.DataFrame({"ano": list(anos)}).with_columns(pl.col("ano").cast(pl.Int16)),
        how="cross"
    )
    
    saida = grade
    colunas_vistas = {"cod_municipio", "ano"}
    
    for i, fonte in enumerate(fontes):
        if "ano" not in fonte.columns or fonte["ano"].dtype != pl.Int16:
            raise ValueError(f"{nome_tabela} (fonte {i}): 'ano' não é Int16 ou está ausente")
            
        dups = fonte.filter(fonte.select(["cod_municipio", "ano"]).is_duplicated())
        if not dups.is_empty():
            raise ValueError(f"{nome_tabela} (fonte {i}): {dups.select(['cod_municipio', 'ano']).n_unique()} chaves repetidas. Exemplos: {dups.head(3).to_dicts()}")
            
        invalidos = [c for c in set(fonte["cod_municipio"]) if c not in codigos_validos]
        if invalidos:
            raise ValueError(f"{nome_tabela} (fonte {i}): {len(invalidos)} códigos fora da tabela de municípios. Exemplos: {invalidos[:3]}")
            
        anos_invalidos = [a for a in set(fonte["ano"]) if a not in anos]
        if anos_invalidos:
            raise ValueError(f"{nome_tabela} (fonte {i}): {len(anos_invalidos)} anos fora da janela permitida. Exemplos: {anos_invalidos[:3]}")
            
        novas = set(fonte.columns) - {"cod_municipio", "ano"}
        inter = novas & colunas_vistas
        if inter:
            raise ValueError(f"{nome_tabela} (fonte {i}): coluna com nome que outra fonte já trouxe: {inter}")
            
        saida = saida.join(fonte, on=["cod_municipio", "ano"], how="left")
        colunas_vistas.update(novas)
        
    return saida.sort(["cod_municipio", "ano"])

def montar_limitrofes(municipios: pl.DataFrame, limitrofes: pl.DataFrame) -> pl.DataFrame:
    dups = limitrofes.filter(limitrofes.select(["cod_municipio", "cod_municipio_limitrofe"]).is_duplicated())
    if not dups.is_empty():
        raise ValueError(f"limitrofes: {dups.select(['cod_municipio', 'cod_municipio_limitrofe']).n_unique()} pares repetidos. Exemplos: {dups.head(3).to_dicts()}")
        
    codigos_validos = set(municipios["cod_municipio"])
    invalidos = [c for c in set(limitrofes["cod_municipio"]) | set(limitrofes["cod_municipio_limitrofe"]) if c not in codigos_validos]
    if invalidos:
        raise ValueError(f"limitrofes: {len(invalidos)} códigos fora da tabela de municípios. Exemplos: {invalidos[:3]}")
        
    return limitrofes.sort(["cod_municipio", "cod_municipio_limitrofe"])

def consolidar_educacao(censo_escolar: pl.DataFrame, censo_superior: pl.DataFrame, ideb: pl.DataFrame) -> pl.DataFrame:
    # Censo Escolar
    escolar_cols = ["cod_municipio", "ano", "dependencia", "localizacao", "escolas", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica"]
    for c in escolar_cols:
        if c not in censo_escolar.columns:
            raise ValueError(f"Falta coluna {c} em censo_escolar")
            
    if censo_escolar["cod_municipio"].dtype != pl.String:
        raise ValueError("censo_escolar: cod_municipio deve ser String")
    if censo_escolar["ano"].dtype != pl.Int16:
        raise ValueError("censo_escolar: ano deve ser Int16")
    for c in ["escolas", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica"]:
        if not censo_escolar[c].dtype.is_integer():
            raise ValueError(f"censo_escolar: {c} deve ser inteiro")

    if censo_escolar.select(["cod_municipio", "ano", "dependencia", "localizacao"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Chaves nulas na entrada censo_escolar")
        
    dups_escolar = censo_escolar.filter(censo_escolar.select(["cod_municipio", "ano", "dependencia", "localizacao"]).is_duplicated())
    if not dups_escolar.is_empty():
        raise ValueError("censo_escolar: chaves dimensionais duplicadas antes da agregação")

    escolar_aggs = [
        pl.when(pl.col(c).is_not_null().any()).then(pl.col(c).sum()).otherwise(None).alias(c)
        for c in ["escolas", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica"]
    ]
    escolar = censo_escolar.select(escolar_cols).group_by(["cod_municipio", "ano"]).agg(escolar_aggs).rename({"escolas": "instituicoes_basica"})
    for c in ["instituicoes_basica", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica"]:
        escolar = escolar.with_columns(pl.col(c).cast(pl.Int64))
        
    # Censo Superior
    superior_cols = ["cod_municipio", "ano", "categoria", "instituicoes", "matriculas"]
    for c in superior_cols:
        if c not in censo_superior.columns:
            raise ValueError(f"Falta coluna {c} em censo_superior")
            
    if censo_superior["cod_municipio"].dtype != pl.String:
        raise ValueError("censo_superior: cod_municipio deve ser String")
    if censo_superior["ano"].dtype != pl.Int16:
        raise ValueError("censo_superior: ano deve ser Int16")
    for c in ["instituicoes", "matriculas"]:
        if not censo_superior[c].dtype.is_integer():
            raise ValueError(f"censo_superior: {c} deve ser inteiro")

    if censo_superior.select(["cod_municipio", "ano", "categoria"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Chaves nulas na entrada censo_superior")
        
    dups_superior = censo_superior.filter(censo_superior.select(["cod_municipio", "ano", "categoria"]).is_duplicated())
    if not dups_superior.is_empty():
        raise ValueError("censo_superior: chaves dimensionais duplicadas antes da agregação")

    superior = censo_superior.select(superior_cols).filter((pl.col("ano") >= 2006) & (pl.col("ano") <= 2023))
    superior_aggs = [
        pl.when(pl.col(c).is_not_null().any()).then(pl.col(c).sum()).otherwise(None).alias(c)
        for c in ["instituicoes", "matriculas"]
    ]
    superior = superior.group_by(["cod_municipio", "ano"]).agg(superior_aggs).rename({"instituicoes": "instituicoes_superior", "matriculas": "matriculas_superior"})
    for c in ["instituicoes_superior", "matriculas_superior"]:
        superior = superior.with_columns(pl.col(c).cast(pl.Int64))

    # IDEB
    ideb_cols = ["cod_municipio", "ano", "ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"]
    for c in ideb_cols:
        if c not in ideb.columns:
            raise ValueError(f"Falta coluna {c} em ideb")
            
    if ideb["cod_municipio"].dtype != pl.String:
        raise ValueError("ideb: cod_municipio deve ser String")
    if ideb["ano"].dtype != pl.Int16:
        raise ValueError("ideb: ano deve ser Int16")
    for c in ["ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"]:
        if ideb[c].dtype != pl.Float64:
            raise ValueError(f"ideb: {c} deve ser Float64")

    if ideb.select(["cod_municipio", "ano"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Chaves nulas na entrada ideb")
    if not ideb.filter(ideb.select(["cod_municipio", "ano"]).is_duplicated()).is_empty():
        raise ValueError("Chaves duplicadas na entrada ideb")

    ideb_filtrado = ideb.select(ideb_cols).filter((pl.col("ano") >= 2006) & (pl.col("ano") <= 2023))
    
    # Drop rows where all three IDEB measures are null
    ideb_filtrado = ideb_filtrado.filter(
        pl.col("ideb_anos_iniciais_publica").is_not_null() |
        pl.col("ideb_anos_finais_publica").is_not_null() |
        pl.col("ideb_ensino_medio_publica").is_not_null()
    )

    for c in ["ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"]:
        nulos = ideb_filtrado.filter((pl.col(c).is_not_null()) & ((pl.col(c) < 0.0) | (pl.col(c) > 10.0)))
        if not nulos.is_empty():
            raise ValueError(f"ideb: valores fora de 0-10 em {c}")

    # Join
    saida = escolar.join(superior, on=["cod_municipio", "ano"], how="full", coalesce=True)
    saida = saida.join(ideb_filtrado, on=["cod_municipio", "ano"], how="full", coalesce=True)
    
    # Validations
    if saida.select(["cod_municipio", "ano"]).null_count().sum_horizontal().sum() > 0:
        raise ValueError("Chaves nulas na tabela de educação consolidad")
    dups = saida.filter(saida.select(["cod_municipio", "ano"]).is_duplicated())
    if not dups.is_empty():
        raise ValueError("educacao: chaves duplicadas")
        
    ordem = [
        "cod_municipio", "ano",
        "instituicoes_basica", "matriculas_infantil", "matriculas_fundamental", "matriculas_medio", "docentes_basica",
        "instituicoes_superior", "matriculas_superior",
        "ideb_anos_iniciais_publica", "ideb_anos_finais_publica", "ideb_ensino_medio_publica"
    ]
    return saida.select(ordem).sort(["cod_municipio", "ano"])
