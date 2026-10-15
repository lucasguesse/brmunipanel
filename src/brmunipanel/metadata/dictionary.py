from typing import Any, Dict

import polars as pl


def compute_statistics(df: pl.DataFrame, col_name: str) -> dict[str, Any]:
    """Computes summary statistics (nulls, null percentage, min, max, domain) for `col_name` in `df`."""
    col = df[col_name]
    nulls = col.null_count()
    percentage_nulls = round((nulls / df.height) * 100, 2) if df.height > 0 else 0.0

    dtype = col.dtype
    minimum = ""
    maximum = ""
    domain = ""

    is_numeric = dtype.is_numeric()
    is_boolean = dtype == pl.Boolean
    is_string = dtype == pl.Utf8 or dtype == pl.String

    # Minimum and Maximum
    if is_numeric and df.height > 0 and nulls < df.height:
        minimum = str(col.min())
        maximum = str(col.max())

    # Domain
    if is_boolean and df.height > 0 and nulls < df.height:
        # For boolean, domain is "true, false"
        vals = sorted(list(set(col.drop_nulls().to_list())))
        domain = ", ".join(str(v).lower() for v in vals)
    elif is_string and df.height > 0 and nulls < df.height:
        # Compute cardinality
        cardinality = col.n_unique()
        # The domain lists distinct values only for text columns with few values, not for codes or municipality names
        # If cardinality <= 35, list them
        if cardinality <= 35:
            vals = sorted(list(set(col.drop_nulls().to_list())))
            domain = ", ".join(str(v) for v in vals)
        else:
            domain = ""

    return {
        "nulls": nulls,
        "null_percentage": percentage_nulls,
        "min": minimum,
        "max": maximum,
        "domain": domain
    }

def build_table_dictionary(df: pl.DataFrame, table_name: str, table_metadata: Dict[str, Any], key_cols: list[str]) -> pl.DataFrame:
    """Builds a standardized variable dictionary DataFrame for `table_name` from metadata and statistics."""
    rows = []
    
    for col_name in df.columns:
        if col_name not in table_metadata:
            raise ValueError(f"Missing metadata for column '{col_name}' in table '{table_name}'")
    
    for meta_col in table_metadata:
        if meta_col not in df.columns:
            raise ValueError(f"Orphan metadata for column '{meta_col}' in table '{table_name}'")

    for col_name in df.columns:
        meta = table_metadata[col_name]
        stats = compute_statistics(df, col_name)
        
        is_key = "Yes" if col_name in key_cols else "No"
        
        # dictionary schema
        row = {
            "table": table_name,
            "variable": col_name,
            "type": str(df[col_name].dtype),
            "description_en": meta.get("description_en", ""),
            "description_pt": meta.get("description_pt", ""),
            "unit": meta.get("unit", ""),
            "source": meta.get("source", ""),
            "period": meta.get("period", ""),
            "key": is_key,
            "nulls": stats["nulls"],
            "null_percentage": stats["null_percentage"],
            "min": stats["min"],
            "max": stats["max"],
            "domain": stats["domain"],
            "methodological_note": meta.get("methodological_note", "")
        }
        rows.append(row)
        
    schema = {
        "table": pl.String,
        "variable": pl.String,
        "type": pl.String,
        "description_en": pl.String,
        "description_pt": pl.String,
        "unit": pl.String,
        "source": pl.String,
        "period": pl.String,
        "key": pl.String,
        "nulls": pl.Int64,
        "null_percentage": pl.Float64,
        "min": pl.String,
        "max": pl.String,
        "domain": pl.String,
        "methodological_note": pl.String
    }
    
    return pl.DataFrame(rows, schema=schema)
