import polars as pl
from typing import Any, Dict, List

def auditar_tabela_resumo(df: pl.DataFrame, table_name: str, key_cols: List[str]) -> dict:
    linhas = df.height
    colunas = df.width
    chave = ", ".join(key_cols)
    
    duplicatas_de_chave = 0
    if linhas > 0 and key_cols and all(c in df.columns for c in key_cols):
        duplicatas_de_chave = df.group_by(key_cols).len().filter(pl.col("len") > 1).height

    ano_minimo = ""
    ano_maximo = ""
    if "ano" in df.columns and linhas > 0 and df["ano"].null_count() < linhas:
        ano_minimo = str(df["ano"].min())
        ano_maximo = str(df["ano"].max())
        
    municipios_distintos = 0
    if "cod_municipio" in df.columns and linhas > 0:
        municipios_distintos = df["cod_municipio"].n_unique()
        
    celulas_nulas = sum(df[c].null_count() for c in df.columns)
    total_celulas = linhas * colunas
    percentual_celulas_nulas = round((celulas_nulas / total_celulas) * 100, 2) if total_celulas > 0 else 0.0
    
    return {
        "tabela": table_name,
        "linhas": linhas,
        "colunas": colunas,
        "chave": chave,
        "duplicatas_de_chave": duplicatas_de_chave,
        "ano_minimo": ano_minimo,
        "ano_maximo": ano_maximo,
        "municipios_distintos": municipios_distintos,
        "celulas_nulas": celulas_nulas,
        "percentual_celulas_nulas": percentual_celulas_nulas
    }

class QualityAuditor:
    def __init__(self, municipios_df: pl.DataFrame):
        self.municipios_df = municipios_df
        self.valid_cods = set()
        if municipios_df is not None and "cod_municipio" in municipios_df.columns:
            self.valid_cods = set(municipios_df["cod_municipio"].drop_nulls().to_list())
        self.checks = []
        
    def add_check(self, tabela: str, regra: str, status: str, observado: str, esperado: str, detalhe: str = ""):
        self.checks.append({
            "tabela": tabela,
            "regra": regra,
            "status": status,
            "observado": observado,
            "esperado": esperado,
            "detalhe": detalhe
        })
        if status == "FALHA" and "crítica" in detalhe.lower():
            raise ValueError(f"FALHA CRÍTICA: [{tabela}] {regra} - Observado: {observado}, Esperado: {esperado}")

    def auditar_esquema(self, df: pl.DataFrame, tabela: str, expected_cols: List[str], expected_dtypes: Dict[str, Any]):
        actual_cols = df.columns
        if actual_cols == expected_cols:
            self.add_check(tabela, "esquema e ordem de colunas", "OK", "Correto", "Correto")
        else:
            self.add_check(tabela, "esquema e ordem de colunas", "FALHA", str(actual_cols), str(expected_cols), "Crítica: não bate o contrato")
            
        tipos_ok = True
        observados = []
        for c in actual_cols:
            if c in expected_dtypes:
                dtype = df[c].dtype
                if dtype != expected_dtypes[c]:
                    tipos_ok = False
                    observados.append(f"{c}: {dtype}")
        if tipos_ok:
            self.add_check(tabela, "tipos correspondem ao contrato", "OK", "Correto", "Correto")
        else:
            self.add_check(tabela, "tipos correspondem ao contrato", "FALHA", str(observados), "Correto", "Crítica: tipos incompatíveis")

    def auditar_chaves(self, df: pl.DataFrame, tabela: str, key_cols: List[str]):
        if not key_cols:
            return
        
        has_nulls = False
        null_counts = []
        for c in key_cols:
            if c in df.columns:
                n = df[c].null_count()
                if n > 0:
                    has_nulls = True
                    null_counts.append(f"{c}: {n}")
        
        if not has_nulls:
            self.add_check(tabela, "chave sem nulo", "OK", "0", "0")
        else:
            self.add_check(tabela, "chave sem nulo", "FALHA", str(null_counts), "0", "Crítica: chaves não podem ser nulas")
            
        dups = df.group_by(key_cols).len().filter(pl.col("len") > 1).height
        if dups == 0:
            self.add_check(tabela, "chave sem duplicata", "OK", "0", "0")
        else:
            self.add_check(tabela, "chave sem duplicata", "FALHA", str(dups), "0", "Crítica: chaves não podem ser duplicadas")

    def auditar_codigos_municipais(self, df: pl.DataFrame, tabela: str, col_name="cod_municipio"):
        if col_name in df.columns and self.valid_cods:
            invalid_count = df.filter(~pl.col(col_name).is_in(self.valid_cods)).height
            if invalid_count == 0:
                self.add_check(tabela, f"códigos municipais ({col_name})", "OK", "0 inválidos", "0 inválidos")
            else:
                self.add_check(tabela, f"códigos municipais ({col_name})", "FALHA", f"{invalid_count} inválidos", "0 inválidos", "Crítica: todos devem pertencer a municipios.parquet")

    def auditar_valores_negativos(self, df: pl.DataFrame, tabela: str):
        numeric_cols = [c for c, dtype in zip(df.columns, df.dtypes) if dtype.is_numeric()]
        falhas = []
        for c in numeric_cols:
            # Only count columns where conceptually negative doesn't make sense.
            # Most features in this panel shouldn't be negative (counts, expenses, etc).
            if c in ["latitude_sede", "longitude_sede"]:
                continue # Coordinates can be negative
            neg_count = df.filter(pl.col(c) < 0).height
            if neg_count > 0:
                falhas.append(f"{c}: {neg_count}")
        if not falhas:
            self.add_check(tabela, "valores não negativos", "OK", "Nenhum", "Nenhum")
        else:
            self.add_check(tabela, "valores não negativos", "FALHA", str(falhas), "Nenhum", "Contagens não podem ser negativas")
            
    def auditar_dominios_geograficos(self, df: pl.DataFrame, tabela: str):
        if tabela == "municipios":
            area_inv = df.filter(pl.col("area_km2") <= 0).height
            lat_inv = df.filter((pl.col("latitude_sede") < -35) | (pl.col("latitude_sede") > 6)).height
            lon_inv = df.filter((pl.col("longitude_sede") < -75) | (pl.col("longitude_sede") > -34)).height
            if area_inv == 0 and lat_inv == 0 and lon_inv == 0:
                self.add_check(tabela, "domínios geográficos", "OK", "Correto", "Correto")
            else:
                self.add_check(tabela, "domínios geográficos", "FALHA", f"area_inv={area_inv}, lat_inv={lat_inv}, lon_inv={lon_inv}", "0", "Limites do Brasil")
        
        if tabela == "municipios_limitrofes":
            comp_inv = df.filter(pl.col("comprimento_km") <= 0).height
            if comp_inv == 0:
                self.add_check(tabela, "comprimentos positivos", "OK", "Correto", "Correto")
            else:
                self.add_check(tabela, "comprimentos positivos", "FALHA", f"{comp_inv} <= 0", "0", "Comprimento deve ser > 0")

    def get_checks_df(self) -> pl.DataFrame:
        schema = {
            "tabela": pl.String,
            "regra": pl.String,
            "status": pl.String,
            "observado": pl.String,
            "esperado": pl.String,
            "detalhe": pl.String
        }
        return pl.DataFrame(self.checks, schema=schema)
