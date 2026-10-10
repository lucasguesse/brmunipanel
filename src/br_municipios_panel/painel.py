"""Consolidação da base em cinco tabelas.

A base consolidada tem cinco tabelas: a central de municípios, o painel com as séries
por município e ano (onde a consolidação junta as fontes), a tabela
de municípios limítrofes, e as duas de educação, que entram como vieram da harmonização.
Nenhuma função aqui preenche nulo, tira linha, altera valor nem calcula coluna derivada.
"""

from typing import Sequence
import polars as pl

ANOS_PAINEL = tuple(range(2006, 2024))

def montar_municipios(municipios: pl.DataFrame, regioes_saude: pl.DataFrame) -> pl.DataFrame:
    if "cod_municipio" not in municipios.columns or "cod_municipio" not in regioes_saude.columns:
        raise ValueError("Falta cod_municipio")
    
    dups_mun = municipios.filter(municipios["cod_municipio"].is_duplicated())["cod_municipio"]
    if not dups_mun.is_empty():
        raise ValueError(f"municipios: {dups_mun.n_unique()} chaves repetidas. Exemplos: {dups_mun.head(3).to_list()}")
        
    dups_reg = regioes_saude.filter(regioes_saude["cod_municipio"].is_duplicated())["cod_municipio"]
    if not dups_reg.is_empty():
        raise ValueError(f"regioes_saude: {dups_reg.n_unique()} chaves repetidas. Exemplos: {dups_reg.head(3).to_list()}")
        
    codigos_validos = set(municipios["cod_municipio"])
    invalidos = [c for c in regioes_saude["cod_municipio"] if c not in codigos_validos]
    if invalidos:
        raise ValueError(f"regioes_saude: {len(invalidos)} códigos fora da tabela de municípios. Exemplos: {invalidos[:3]}")

    colunas_comuns = set(municipios.columns) & set(regioes_saude.columns) - {"cod_municipio"}
    if colunas_comuns:
        raise ValueError(f"Coluna de mesmo nome nas duas tabelas além da chave: {colunas_comuns}")
        
    saida = municipios.join(regioes_saude, on="cod_municipio", how="left")
    return saida.sort("cod_municipio")

def montar_despesa(finbra: pl.DataFrame, siconfi: pl.DataFrame) -> pl.DataFrame:
    if list(finbra.columns) != list(siconfi.columns):
        raise ValueError(f"Colunas diferentes ou em ordem diferente entre finbra e siconfi. finbra: {finbra.columns}, siconfi: {siconfi.columns}")
        
    if dict(zip(finbra.columns, finbra.dtypes)) != dict(zip(siconfi.columns, siconfi.dtypes)):
        raise ValueError("Tipos diferentes entre finbra e siconfi")
        
    # Confere se há o mesmo município e ano nas duas
    finbra_keys = set(finbra.select(["cod_municipio", "ano"]).iter_rows())
    siconfi_keys = set(siconfi.select(["cod_municipio", "ano"]).iter_rows())
    inter = finbra_keys & siconfi_keys
    if inter:
        raise ValueError(f"{len(inter)} casos do mesmo município e ano nas duas tabelas. Exemplos: {list(inter)[:3]}")
        
    saida = pl.concat([finbra, siconfi])
    return saida.sort(["cod_municipio", "ano"])

def montar_painel(municipios: pl.DataFrame, fontes: list[pl.DataFrame], anos: Sequence[int] = ANOS_PAINEL) -> pl.DataFrame:
    codigos_validos = set(municipios["cod_municipio"])
    
    # Grade de municipios e anos
    grade = municipios.select(["cod_municipio"]).join(
        pl.DataFrame({"ano": list(anos)}).with_columns(pl.col("ano").cast(pl.Int16)),
        how="cross"
    )
    
    saida = grade
    colunas_vistas = {"cod_municipio", "ano"}
    
    for i, fonte in enumerate(fontes):
        if "ano" not in fonte.columns or fonte["ano"].dtype != pl.Int16:
            raise ValueError(f"fonte {i}: 'ano' não é Int16 ou está ausente")
            
        dups = fonte.filter(fonte.select(["cod_municipio", "ano"]).is_duplicated())
        if not dups.is_empty():
            raise ValueError(f"fonte {i}: {dups.select(['cod_municipio', 'ano']).n_unique()} chaves repetidas. Exemplos: {dups.head(3).to_dicts()}")
            
        invalidos = [c for c in set(fonte["cod_municipio"]) if c not in codigos_validos]
        if invalidos:
            raise ValueError(f"fonte {i}: {len(invalidos)} códigos fora da tabela de municípios. Exemplos: {invalidos[:3]}")
            
        anos_invalidos = [a for a in set(fonte["ano"]) if a not in anos]
        if anos_invalidos:
            raise ValueError(f"fonte {i}: {len(anos_invalidos)} anos fora de anos. Exemplos: {anos_invalidos[:3]}")
            
        novas = set(fonte.columns) - {"cod_municipio", "ano"}
        inter = novas & colunas_vistas
        if inter:
            raise ValueError(f"fonte {i}: coluna com nome que outra fonte já trouxe: {inter}")
            
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

def montar_educacao(municipios: pl.DataFrame, tabela: pl.DataFrame, chave: Sequence[str], nome: str) -> pl.DataFrame:
    colunas_ausentes = [c for c in chave if c not in tabela.columns]
    if colunas_ausentes:
        raise ValueError(f"{nome}: faltam colunas da chave na tabela: {colunas_ausentes}")
        
    if "cod_municipio" not in chave or "ano" not in chave:
        raise ValueError(f"{nome}: cod_municipio e ano devem estar em chave")
        
    if tabela["ano"].dtype != pl.Int16:
        raise ValueError(f"{nome}: 'ano' não é Int16")
        
    for c in chave:
        if tabela[c].null_count() > 0:
            raise ValueError(f"{nome}: coluna da chave '{c}' tem nulos")
            
    dups = tabela.filter(tabela.select(chave).is_duplicated())
    if not dups.is_empty():
        raise ValueError(f"{nome}: {dups.select(chave).n_unique()} chaves repetidas. Exemplos: {dups.head(3).to_dicts()}")
        
    codigos_validos = set(municipios["cod_municipio"])
    invalidos = [c for c in set(tabela["cod_municipio"]) if c not in codigos_validos]
    if invalidos:
        raise ValueError(f"{nome}: {len(invalidos)} códigos fora da tabela de municípios. Exemplos: {invalidos[:3]}")
        
    return tabela.sort(chave)
