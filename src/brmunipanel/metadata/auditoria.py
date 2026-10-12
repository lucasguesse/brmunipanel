import polars as pl
from typing import Any, Dict, List
import json

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
        "arquivo": table_name + ".parquet",
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
        self.has_critical_failure = False
        
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
            self.has_critical_failure = True

    def auditar_arquivos_esperados(self, etapa: str, arquivos_encontrados: List[str], contrato: dict):
        esperados = list(contrato.keys())
        for f in esperados:
            if f not in arquivos_encontrados:
                self.add_check(f"[{etapa}] {f}", "arquivo existe e abre", "FALHA", "Ausente", "Presente", "Crítica: Arquivo faltando no projeto")

    def auditar_esquema(self, df: pl.DataFrame, tabela: str, contrato: dict):
        clean_name = tabela.replace("[processed] ", "").replace("[intermediate] ", "")
        if clean_name not in contrato:
            self.add_check(tabela, "esquema e ordem de colunas", "FALHA", "Falta contrato", "Contrato esperado", "Crítica: tabela sem contrato")
            return
            
        expected_cols = list(contrato[clean_name]["cols"].keys())
        expected_dtypes = contrato[clean_name]["cols"]
        
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

    def auditar_periodo_e_contagens(self, df: pl.DataFrame, tabela: str, contrato: dict):
        clean_name = tabela.replace("[processed] ", "").replace("[intermediate] ", "")
        if clean_name not in contrato:
            return
            
        c = contrato[clean_name]
        
        if c["periodo"]:
            min_ano, max_ano = c["periodo"]
            df_min = df["ano"].min() if "ano" in df.columns else None
            df_max = df["ano"].max() if "ano" in df.columns else None
            if df_min == min_ano and df_max == max_ano:
                self.add_check(tabela, "anos esperado vs observado", "OK", f"{df_min}-{df_max}", f"{min_ano}-{max_ano}")
            else:
                self.add_check(tabela, "anos esperado vs observado", "FALHA", f"{df_min}-{df_max}", f"{min_ano}-{max_ano}", "Crítica: período inválido")
                
        if c.get("linhas"):
            linhas = df.height
            if linhas == c["linhas"]:
                self.add_check(tabela, "contagem de linhas", "OK", str(linhas), str(c["linhas"]))
            else:
                self.add_check(tabela, "contagem de linhas", "FALHA", str(linhas), str(c["linhas"]), "Crítica: total de linhas divergente")
                
        if c.get("municipios") and "cod_municipio" in df.columns:
            muns = df["cod_municipio"].n_unique()
            if muns == c["municipios"]:
                self.add_check(tabela, "municípios distintos", "OK", str(muns), str(c["municipios"]))
            else:
                self.add_check(tabela, "municípios distintos", "FALHA", str(muns), str(c["municipios"]), "Crítica: municípios divergentes")

    def auditar_totais_de_controle(self, df: pl.DataFrame, tabela: str):
        clean_name = tabela.replace("[processed] ", "").replace("[intermediate] ", "")
        
        if clean_name == "educacao":
            # National control totals for basic and higher education, in 2006 and in 2023
            df_2006 = df.filter(pl.col("ano") == 2006)
            df_2023 = df.filter(pl.col("ano") == 2023)
            df_sp_2023 = df_2023.filter(pl.col("cod_municipio") == "3550308")
            
            # 2006 totals
            inst_basica_2006 = df_2006["instituicoes_basica"].sum()
            mat_inf_2006 = df_2006["matriculas_infantil"].sum()
            mat_fund_2006 = df_2006["matriculas_fundamental"].sum()
            mat_med_2006 = df_2006["matriculas_medio"].sum()
            docentes_2006 = df_2006["docentes_basica"].sum()
            
            self.add_check(tabela, "educacao basica 2006 institutos", "OK" if inst_basica_2006 == 203973 else "FALHA", str(inst_basica_2006), "203973")
            self.add_check(tabela, "educacao basica 2006 infantil", "OK" if mat_inf_2006 == 7016095 else "FALHA", str(mat_inf_2006), "7016095")
            self.add_check(tabela, "educacao basica 2006 fundamental", "OK" if mat_fund_2006 == 33282663 else "FALHA", str(mat_fund_2006), "33282663")
            self.add_check(tabela, "educacao basica 2006 medio", "OK" if mat_med_2006 == 8906820 else "FALHA", str(mat_med_2006), "8906820")
            self.add_check(tabela, "educacao basica 2006 docentes", "OK" if docentes_2006 == 2647414 else "FALHA", str(docentes_2006), "2647414")
            
            # 2023 totals
            inst_basica_2023 = df_2023["instituicoes_basica"].sum()
            mat_inf_2023 = df_2023["matriculas_infantil"].sum()
            mat_fund_2023 = df_2023["matriculas_fundamental"].sum()
            mat_med_2023 = df_2023["matriculas_medio"].sum()
            docentes_2023 = df_2023["docentes_basica"].sum()
            inst_sup_2023 = df_2023["instituicoes_superior"].sum()
            mat_sup_2023 = df_2023["matriculas_superior"].sum()
            
            self.add_check(tabela, "educacao basica 2023 institutos", "OK" if inst_basica_2023 == 180230 else "FALHA", str(inst_basica_2023), "180230")
            self.add_check(tabela, "educacao basica 2023 infantil", "OK" if mat_inf_2023 == 9461155 else "FALHA", str(mat_inf_2023), "9461155")
            self.add_check(tabela, "educacao basica 2023 fundamental", "OK" if mat_fund_2023 == 26108208 else "FALHA", str(mat_fund_2023), "26108208")
            self.add_check(tabela, "educacao basica 2023 medio", "OK" if mat_med_2023 == 7676743 else "FALHA", str(mat_med_2023), "7676743")
            self.add_check(tabela, "educacao basica 2023 docentes", "OK" if docentes_2023 == 2934558 else "FALHA", str(docentes_2023), "2934558")
            self.add_check(tabela, "educacao superior 2023 institutos", "OK" if inst_sup_2023 == 3800 else "FALHA", str(inst_sup_2023), "3800")
            self.add_check(tabela, "educacao superior 2023 matriculas", "OK" if mat_sup_2023 == 5063936 else "FALHA", str(mat_sup_2023), "5063936")
            
            # SP 2023 totals
            if df_sp_2023.height > 0:
                self.add_check(tabela, "SP 2023 basica inst", "OK" if df_sp_2023["instituicoes_basica"][0] == 7252 else "FALHA", str(df_sp_2023["instituicoes_basica"][0]), "7252")
                self.add_check(tabela, "SP 2023 basica inf", "OK" if df_sp_2023["matriculas_infantil"][0] == 666498 else "FALHA", str(df_sp_2023["matriculas_infantil"][0]), "666498")
                self.add_check(tabela, "SP 2023 basica fund", "OK" if df_sp_2023["matriculas_fundamental"][0] == 1338720 else "FALHA", str(df_sp_2023["matriculas_fundamental"][0]), "1338720")
                self.add_check(tabela, "SP 2023 basica med", "OK" if df_sp_2023["matriculas_medio"][0] == 447010 else "FALHA", str(df_sp_2023["matriculas_medio"][0]), "447010")
                self.add_check(tabela, "SP 2023 basica doc", "OK" if df_sp_2023["docentes_basica"][0] == 155496 else "FALHA", str(df_sp_2023["docentes_basica"][0]), "155496")
                self.add_check(tabela, "SP 2023 sup inst", "OK" if df_sp_2023["instituicoes_superior"][0] == 155 else "FALHA", str(df_sp_2023["instituicoes_superior"][0]), "155")
                self.add_check(tabela, "SP 2023 sup mat", "OK" if df_sp_2023["matriculas_superior"][0] == 493613 else "FALHA", str(df_sp_2023["matriculas_superior"][0]), "493613")
                self.add_check(tabela, "SP 2023 ideb pub ini", "OK" if abs(df_sp_2023["ideb_anos_iniciais_publica"][0] - 5.9) < 0.01 else "FALHA", str(df_sp_2023["ideb_anos_iniciais_publica"][0]), "5.9")
                self.add_check(tabela, "SP 2023 ideb pub fin", "OK" if abs(df_sp_2023["ideb_anos_finais_publica"][0] - 4.8) < 0.01 else "FALHA", str(df_sp_2023["ideb_anos_finais_publica"][0]), "4.8")
                self.add_check(tabela, "SP 2023 ideb pub med", "OK" if abs(df_sp_2023["ideb_ensino_medio_publica"][0] - 4.2) < 0.01 else "FALHA", str(df_sp_2023["ideb_ensino_medio_publica"][0]), "4.2")

            # Count of non-null IDEB values in each stage, from 2006 to 2023
            nn_ini = df.filter((pl.col("ano") >= 2006) & (pl.col("ano") <= 2023))["ideb_anos_iniciais_publica"].drop_nulls().len()
            nn_fin = df.filter((pl.col("ano") >= 2006) & (pl.col("ano") <= 2023))["ideb_anos_finais_publica"].drop_nulls().len()
            nn_med = df.filter((pl.col("ano") >= 2006) & (pl.col("ano") <= 2023))["ideb_ensino_medio_publica"].drop_nulls().len()
            self.add_check(tabela, "IDEB pub ini nao nulo", "OK" if nn_ini == 48097 else "FALHA", str(nn_ini), "48097")
            self.add_check(tabela, "IDEB pub fin nao nulo", "OK" if nn_fin == 47897 else "FALHA", str(nn_fin), "47897")
            self.add_check(tabela, "IDEB pub med nao nulo", "OK" if nn_med == 18493 else "FALHA", str(nn_med), "18493")
        
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
            if c in ["latitude_sede", "longitude_sede", "pib", "pib_per_capita"] or c.startswith("desp_"):
                continue
            neg_count = df.filter(pl.col(c) < 0).height
            if neg_count > 0:
                falhas.append(f"{c}: {neg_count}")
        if not falhas:
            self.add_check(tabela, "valores não negativos", "OK", "Nenhum", "Nenhum")
        else:
            self.add_check(tabela, "valores não negativos", "FALHA", str(falhas), "Nenhum", "Contagens não podem ser negativas")
            
    def auditar_dominios_geograficos(self, df: pl.DataFrame, tabela: str):
        clean_name = tabela.replace("[processed] ", "").replace("[intermediate] ", "")
        if clean_name in ["municipios", "ibge_municipios"]:
            area_inv = df.filter(pl.col("area_km2") <= 0).height
            # Fernando de Noronha is -32 longitude (around -32.4)
            # latitude should be within -35 and 6
            # longitude should be within -75 and -30
            lat_inv = df.filter((pl.col("latitude_sede") < -35) | (pl.col("latitude_sede") > 6)).height
            lon_inv = df.filter((pl.col("longitude_sede") < -75) | (pl.col("longitude_sede") > -30)).height
            if area_inv == 0 and lat_inv == 0 and lon_inv == 0:
                self.add_check(tabela, "domínios geográficos", "OK", "Correto", "Correto")
            else:
                self.add_check(tabela, "domínios geográficos", "FALHA", f"area_inv={area_inv}, lat_inv={lat_inv}, lon_inv={lon_inv}", "0", "Limites do Brasil")
        
        if clean_name in ["municipios_limitrofes", "ibge_municipios_limitrofes"]:
            if self.valid_cods:
                inv_cod_lim = df.filter(~pl.col("cod_municipio_limitrofe").is_in(self.valid_cods)).height
                if inv_cod_lim == 0:
                    self.add_check(tabela, "códigos limítrofes", "OK", "Correto", "Correto")
                else:
                    self.add_check(tabela, "códigos limítrofes", "FALHA", f"{inv_cod_lim} inválidos", "0", "Devem pertencer ao cadastro")
            comp_inv = df.filter(pl.col("comprimento_km") < 0).height # 0 is accepted
            if comp_inv == 0:
                self.add_check(tabela, "comprimentos positivos", "OK", "Correto", "Correto")
            else:
                self.add_check(tabela, "comprimentos positivos", "FALHA", f"{comp_inv} < 0", "0", "Comprimento deve ser >= 0")

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
