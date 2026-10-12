import json
import json.decoder
from pathlib import Path
from typing import Any, Dict

import polars as pl


def compute_statistics(df: pl.DataFrame, col_name: str) -> dict[str, Any]:
    col = df[col_name]
    nulos = col.null_count()
    percentual_nulos = round((nulos / df.height) * 100, 2) if df.height > 0 else 0.0

    dtype = col.dtype
    minimo = ""
    maximo = ""
    dominio = ""

    is_numeric = dtype.is_numeric()
    is_boolean = dtype == pl.Boolean
    is_string = dtype == pl.Utf8 or dtype == pl.String

    # Minimum and Maximum
    if is_numeric and df.height > 0 and nulos < df.height:
        minimo = str(col.min())
        maximo = str(col.max())

    # Domain
    if is_boolean and df.height > 0 and nulos < df.height:
        # For boolean, domain is "true, false"
        vals = sorted(list(set(col.drop_nulls().to_list())))
        dominio = ", ".join(str(v).lower() for v in vals)
    elif is_string and df.height > 0 and nulos < df.height:
        # Compute cardinality
        cardinality = col.n_unique()
        # The domain lists distinct values only for text columns with few values, not for codes or municipality names
        # If cardinality <= 35, list them
        if cardinality <= 35:
            vals = sorted(list(set(col.drop_nulls().to_list())))
            dominio = ", ".join(str(v) for v in vals)
        else:
            dominio = ""

    return {
        "nulos": nulos,
        "percentual_nulos": percentual_nulos,
        "minimo": minimo,
        "maximo": maximo,
        "dominio": dominio
    }

def build_table_dictionary(df: pl.DataFrame, table_name: str, table_metadata: Dict[str, Any], key_cols: list[str]) -> pl.DataFrame:
    rows = []
    
    for col_name in df.columns:
        if col_name not in table_metadata:
            raise ValueError(f"Metadado ausente para a coluna '{col_name}' na tabela '{table_name}'.")
    
    for meta_col in table_metadata:
        if meta_col not in df.columns:
            raise ValueError(f"Metadado órfão para a coluna '{meta_col}' na tabela '{table_name}'.")

    for col_name in df.columns:
        meta = table_metadata[col_name]
        stats = compute_statistics(df, col_name)
        
        is_key = "Sim" if col_name in key_cols else "Não"
        
        # dictionary schema
        row = {
            "tabela": table_name,
            "variavel": col_name,
            "tipo": str(df[col_name].dtype),
            "descricao_en": meta.get("descricao_en", ""),
            "descricao_pt": meta.get("descricao_pt", ""),
            "unidade": meta.get("unidade", ""),
            "fonte": meta.get("fonte", ""),
            "periodo": meta.get("periodo", ""),
            "chave": is_key,
            "nulos": stats["nulos"],
            "percentual_nulos": stats["percentual_nulos"],
            "minimo": stats["minimo"],
            "maximo": stats["maximo"],
            "dominio": stats["dominio"],
            "nota_metodologica": meta.get("nota_metodologica", "")
        }
        rows.append(row)
        
    schema = {
        "tabela": pl.String,
        "variavel": pl.String,
        "tipo": pl.String,
        "descricao_en": pl.String,
        "descricao_pt": pl.String,
        "unidade": pl.String,
        "fonte": pl.String,
        "periodo": pl.String,
        "chave": pl.String,
        "nulos": pl.Int64,
        "percentual_nulos": pl.Float64,
        "minimo": pl.String,
        "maximo": pl.String,
        "dominio": pl.String,
        "nota_metodologica": pl.String
    }
    
    return pl.DataFrame(rows, schema=schema)
