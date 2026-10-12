"""
Censo Escolar - INEP

Fonte: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (INEP)
Unidade de origem: escola
Chave: município, ano, dependência administrativa, localização

Ressalvas:
- matriculas_basica é o total que o INEP publica (de 2007 em diante), e não a soma das outras etapas, que se sobrepõem.
- A soma de docentes conta mais de uma vez quem atua em mais de uma escola no município.
- Nulo significa que nenhuma escola do grupo tem o dado.
- Em 2006, o leiaute é outro: a data de referência é 29 de março de 2006 (e de 2007 em diante é a última quarta-feira de maio); o vazio vale zero; a EJA inclui os cursos semipresenciais nas matrículas e não nas turmas; o curso normal e o médio integrado estão dentro do ensino médio; catorze colunas são nulas; e a série muda de método em 2007, quando o INEP passou a coletar o censo por aluno.
- Docentes em 2006: são os professores em exercício da escola, e os de cada nível contam o mesmo professor em mais de um.
"""

from pathlib import Path
import zipfile
import tempfile
import polars as pl

from brmunipanel.nucleo import Requisicao, RespostaInvalida, baixar_lote

ANOS_ATUAIS = list(range(2007, 2024))
ANOS_TODOS = list(range(2006, 2024))

ETAPAS = [
    ("BAS", "basica"),
    ("INF", "infantil"),
    ("INF_CRE", "creche"),
    ("INF_PRE", "pre_escola"),
    ("FUND", "fundamental"),
    ("FUND_AI", "fund_anos_iniciais"),
    ("FUND_AF", "fund_anos_finais"),
    ("MED", "medio"),
    ("PROF", "profissional"),
    ("PROF_TEC", "prof_tecnica"),
    ("EJA", "eja"),
    ("EJA_FUND", "eja_fundamental"),
    ("EJA_MED", "eja_medio"),
    ("ESP", "especial"),
    ("ESP_CC", "especial_inclusiva"),
    ("ESP_CE", "especial_exclusiva"),
]

COLUNAS_QUANTIDADE = []
for orig, dest in ETAPAS:
    COLUNAS_QUANTIDADE.append((f"QT_MAT_{orig}", f"matriculas_{dest}"))
for orig, dest in ETAPAS:
    COLUNAS_QUANTIDADE.append((f"QT_DOC_{orig}", f"docentes_{dest}"))
for orig, dest in ETAPAS:
    COLUNAS_QUANTIDADE.append((f"QT_TUR_{orig}", f"turmas_{dest}"))

def validar_zip(conteudo: bytes):
    if not conteudo.startswith(b"PK\x03\x04"):
        raise RespostaInvalida("O conteúdo não é um arquivo ZIP válido.")

def baixar(pasta: Path | str, **opcoes):
    pasta = Path(pasta)
    reqs = []
    for ano in ANOS_TODOS:
        reqs.append(
            Requisicao(
                chave=f"censo-escolar/{ano}",
                url=f"https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip",
                arquivo=f"censo-escolar/censo-escolar_{ano}.zip",
                metodo="GET",
                compactar=False
            )
        )
    baixar_lote(reqs, pasta, validar=validar_zip, intervalo=1.0, **opcoes)

def _get_dn(cols):
    res = []
    for c in cols:
        res.append(c)
        res.append('N' + c[1:])
    return res

def ler_ano_2006(pasta: Path, valid_municipios: set[str]) -> pl.DataFrame:
    caminho_zip = pasta / "censo-escolar/censo-escolar_2006.zip"
    
    with zipfile.ZipFile(caminho_zip, 'r') as z:
        censo_cands = [info for info in z.infolist() if 'CENSOESC_2006.CSV' in info.filename.upper()]
        educ_cands = [info for info in z.infolist() if 'EDUCPROF_2006.CSV' in info.filename.upper()]
        
        if len(censo_cands) != 1 or len(educ_cands) != 1:
            raise ValueError("Ano 2006: faltando CENSOESC_2006.CSV ou EDUCPROF_2006.CSV no ZIP.")
            
        membro_censo = censo_cands[0]
        membro_educ = educ_cands[0]
        
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            z.extract(membro_censo, td_path)
            z.extract(membro_educ, td_path)
            
            arquivo_censo = td_path / membro_censo.filename
            arquivo_educ = td_path / membro_educ.filename
            
            colunas_todas = set(pl.scan_csv(arquivo_censo, separator="|", encoding="utf8-lossy", infer_schema_length=0).collect_schema().names())
            
            # Mapeamento de variáveis
            matriculas = {}
            matriculas['creche'] = _get_dn(['DPE119'])
            matriculas['pre_escola'] = _get_dn(['DPE11D'])
            matriculas['infantil'] = matriculas['creche'] + matriculas['pre_escola']
            matriculas['fund_anos_iniciais'] = _get_dn(['DEF11C', 'DEF11D', 'DEF11E', 'DEF11F', 'DE9F11C', 'DE9F11D', 'DE9F11E', 'DE9F11F', 'DE9F11G'])
            matriculas['fund_anos_finais'] = _get_dn(['DEF11G', 'DEF11H', 'DEF11I', 'DEF11J', 'DE9F11H', 'DE9F11I', 'DE9F11J', 'DE9F11N'])
            matriculas['fundamental'] = matriculas['fund_anos_iniciais'] + matriculas['fund_anos_finais']
            matriculas['medio'] = _get_dn(['DEM118', 'DEM119', 'DEM11A', 'DEM11B', 'DEM11C'])
            
            eja_fund = _get_dn(['DES101F', 'DES101G', 'DES101H', 'DES101I'])
            for x in list("23456789ABCD"):
                for y in ["3", "4"]:
                    eja_fund.append(f"VES12{x}{y}")
            matriculas['eja_fundamental'] = eja_fund
            
            eja_medio = _get_dn(['DES101A'])
            for x in list("23456789ABCD"):
                eja_medio.append(f"VES12{x}2")
            matriculas['eja_medio'] = eja_medio
            matriculas['eja'] = matriculas['eja_fundamental'] + matriculas['eja_medio']
            
            matriculas['especial_exclusiva'] = [c for c in colunas_todas if any(c.startswith(p) for p in ['VEE10', 'VEE11', 'VEE16', 'VEE17'])]
            matriculas['especial_inclusiva'] = [c for c in colunas_todas if any(c.startswith(p) for p in ['VEE12', 'VEE13', 'VEE18', 'VEE19'])]
            matriculas['especial'] = matriculas['especial_exclusiva'] + matriculas['especial_inclusiva']
            
            turmas = {}
            turmas['creche'] = _get_dn(['DPE113'])
            turmas['pre_escola'] = _get_dn(['DPE117'])
            turmas['infantil'] = turmas['creche'] + turmas['pre_escola'] + _get_dn(['DPE11F'])
            turmas['fund_anos_iniciais'] = _get_dn(['DEF113', 'DEF114', 'DEF115', 'DEF116', 'DE9F113', 'DE9F114', 'DE9F115', 'DE9F116', 'DE9F117'])
            turmas['fund_anos_finais'] = _get_dn(['DEF117', 'DEF118', 'DEF119', 'DEF11A', 'DE9F118', 'DE9F119', 'DE9F11A', 'DE9F11L'])
            turmas['fundamental'] = turmas['fund_anos_iniciais'] + turmas['fund_anos_finais'] + _get_dn(['DEF11B', 'DE9F11B', 'DEF11K', 'DE9F11K'])
            turmas['medio'] = _get_dn(['DEM113', 'DEM114', 'DEM115', 'DEM116', 'DEM117'])
            turmas['eja_fundamental'] = _get_dn(['DES101B', 'DES101C', 'DES101D', 'DES101E'])
            turmas['eja_medio'] = _get_dn(['DES1016'])
            turmas['eja'] = turmas['eja_fundamental'] + turmas['eja_medio']
            
            docentes = {}
            docentes['basica'] = ['PROFESS']
            docentes['creche'] = ['VDG1CA']
            docentes['pre_escola'] = ['VDG1C1']
            docentes['fundamental'] = ['VDG1C3']
            docentes['medio'] = ['VDG1C4']
            docentes['especial'] = ['VDG1C5']
            docentes['eja'] = ['VDG1C6']
            docentes['prof_tecnica'] = ['VDG1C9']
            docentes['profissional'] = ['VDG1C9']
            
            educ_cols_to_sum = [f"EP31{i}" for i in range(1, 8)] + [f"EP32{i}" for i in range(1, 8)]
            
            colunas_para_ler = ["MASCARA", "CODMUNIC", "DEP", "LOC", "CODFUNC", "ANO"]
            for m in matriculas.values(): colunas_para_ler.extend(m)
            for t in turmas.values(): colunas_para_ler.extend(t)
            for d in docentes.values(): colunas_para_ler.extend(d)
            colunas_para_ler = list(set(colunas_para_ler))
            
            lf = pl.scan_csv(
                arquivo_censo,
                separator="|",
                encoding="utf8-lossy",
                infer_schema_length=0,
            ).select(colunas_para_ler)
            
            lf = lf.select([pl.col(c).str.strip_chars() for c in colunas_para_ler])
            lf = lf.filter(pl.col("CODFUNC") == "Ativo")
            
            dep_map = {"Federal": "federal", "Estadual": "estadual", "Municipal": "municipal", "Particular": "privada"}
            loc_map = {"Urbana": "urbana", "Rural": "rural"}
            
            lf = lf.with_columns(
                (pl.col("CODMUNIC").str.slice(0, 2) + pl.col("CODMUNIC").str.slice(-5)).alias("cod_municipio")
            )
            
            # Validações preguiçosas para erro de valor
            colunas_validar = list(set(colunas_para_ler) - {"MASCARA", "CODMUNIC", "DEP", "LOC", "CODFUNC", "ANO"})
            exprs_val = []
            for c in colunas_validar:
                exprs_val.append(
                    (~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).any().alias(c)
                )
            # Fazemos um collect pontual das validações para interromper antes de computar as agregações
            res = lf.select(exprs_val).collect(engine="streaming").row(0)
            for i, c in enumerate(colunas_validar):
                if res[i]:
                    # Para trazer os primeiros casos no erro
                    invalidos = lf.filter(~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).select("MASCARA", c).head(3).collect()
                    raise ValueError(f"Ano 2006: Valores não inteiros ou negativos na coluna {c}. Exemplo: {invalidos}")
            
            exprs = []
            for k, v in matriculas.items():
                exprs.append(
                    pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in v]).alias(f"matriculas_{k}")
                )
            for k, v in turmas.items():
                exprs.append(
                    pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in v]).alias(f"turmas_{k}")
                )
            for k, v in docentes.items():
                exprs.append(
                    pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in v]).alias(f"docentes_{k}")
                )
            
            lf = lf.with_columns(exprs)
            
            # Tabela EDUCPROF no plano preguiçoso
            lf_educ = pl.scan_csv(
                arquivo_educ,
                separator="|",
                encoding="utf8-lossy",
                infer_schema_length=0,
            ).select(["MASCARA", "CODFUNC"] + educ_cols_to_sum)
            
            lf_educ = lf_educ.select([pl.col(c).str.strip_chars() for c in ["MASCARA", "CODFUNC"] + educ_cols_to_sum])
            lf_educ = lf_educ.filter(pl.col("CODFUNC") == "Ativo")
            
            exprs_val_educ = []
            for c in educ_cols_to_sum:
                exprs_val_educ.append(
                    (~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).any().alias(c)
                )
            res_educ = lf_educ.select(exprs_val_educ).collect(engine="streaming").row(0)
            for i, c in enumerate(educ_cols_to_sum):
                if res_educ[i]:
                    invalidos = lf_educ.filter(~pl.col(c).is_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).select("MASCARA", c).head(3).collect()
                    raise ValueError(f"Ano 2006: Valores não inteiros ou negativos na coluna {c} de EDUCPROF. Exemplo: {invalidos}")
            
            lf_educ = lf_educ.with_columns(
                pl.sum_horizontal([pl.when(pl.col(c) == "").then(0).otherwise(pl.col(c)).cast(pl.Int64) for c in educ_cols_to_sum]).alias("matriculas_prof_tecnica")
            )
                
            lf_educ_agg = lf_educ.group_by("MASCARA").agg(pl.col("matriculas_prof_tecnica").sum())
            
            lf = lf.join(lf_educ_agg, on="MASCARA", how="left")
            lf = lf.with_columns(
                pl.col("matriculas_prof_tecnica").fill_null(0).alias("matriculas_prof_tecnica")
            )
            lf = lf.with_columns(
                pl.col("matriculas_prof_tecnica").alias("matriculas_profissional")
            )
            
            # As catorze colunas nulas
            lf = lf.with_columns(
                pl.lit(None).cast(pl.Int64).alias("matriculas_basica"),
                pl.lit(None).cast(pl.Int64).alias("turmas_basica"),
                pl.lit(None).cast(pl.Int64).alias("docentes_infantil"),
                pl.lit(None).cast(pl.Int64).alias("docentes_fund_anos_iniciais"),
                pl.lit(None).cast(pl.Int64).alias("docentes_fund_anos_finais"),
                pl.lit(None).cast(pl.Int64).alias("docentes_eja_fundamental"),
                pl.lit(None).cast(pl.Int64).alias("docentes_eja_medio"),
                pl.lit(None).cast(pl.Int64).alias("docentes_especial_inclusiva"),
                pl.lit(None).cast(pl.Int64).alias("docentes_especial_exclusiva"),
                pl.lit(None).cast(pl.Int64).alias("turmas_profissional"),
                pl.lit(None).cast(pl.Int64).alias("turmas_prof_tecnica"),
                pl.lit(None).cast(pl.Int64).alias("turmas_especial"),
                pl.lit(None).cast(pl.Int64).alias("turmas_especial_inclusiva"),
                pl.lit(None).cast(pl.Int64).alias("turmas_especial_exclusiva")
            )
            
            # Renomear colunas derivadas
            rename_map = {}
            for qt_col, metric_name in COLUNAS_QUANTIDADE:
                rename_map[metric_name] = qt_col
                
            lf = lf.rename(rename_map)
            lf = lf.with_columns(pl.lit(2006).cast(pl.Int16).alias("ano"))
            
            # Definir as colunas necessárias antes da colheita
            col_order = ["cod_municipio", "ano", "ANO", "CODMUNIC", "DEP", "LOC", "MASCARA"]
            for qt_col, _ in COLUNAS_QUANTIDADE:
                col_order.append(qt_col)
            
            df = lf.select(col_order).collect(engine="streaming")
            
            df = df.with_columns(
                pl.col("DEP").replace_strict(dep_map, default=pl.col("DEP")).alias("dependencia"),
                pl.col("LOC").replace_strict(loc_map, default=pl.col("LOC")).alias("localizacao")
            )
            
            errados_ano = df.filter(pl.col("ANO") != "2006")
            if len(errados_ano) > 0:
                raise ValueError(f"Ano 2006: Há registros com ANO diferente de 2006. Exemplo: {errados_ano.head(3)}")
                
            invalido_dep = df.filter(~pl.col("dependencia").is_in(dep_map.values()) | pl.col("dependencia").is_null())
            if len(invalido_dep) > 0:
                raise ValueError(f"Ano 2006: Valores inválidos em DEP. Exemplo: {invalido_dep.head(3)}")
                
            invalido_loc = df.filter(~pl.col("localizacao").is_in(loc_map.values()) | pl.col("localizacao").is_null())
            if len(invalido_loc) > 0:
                raise ValueError(f"Ano 2006: Valores inválidos em LOC. Exemplo: {invalido_loc.head(3)}")
            
            invalido_mun_len = df.filter((pl.col("CODMUNIC").str.len_chars() != 12) | pl.col("CODMUNIC").is_null())
            if len(invalido_mun_len) > 0:
                raise ValueError(f"Ano 2006: CODMUNIC com tamanho diferente de 12. Exemplo: {invalido_mun_len.head(3)}")
            
            invalido_mun = df.filter(~pl.col("cod_municipio").is_in(valid_municipios))
            if len(invalido_mun) > 0:
                raise ValueError(f"Ano 2006: Municípios inválidos ou nulos em CODMUNIC. Exemplo: {invalido_mun.head(3)}")
                
            escolas_ativas_mascaras = set(df["MASCARA"].to_list())
            df_educ_raw = lf_educ.collect()
            invalido_educ = df_educ_raw.filter(~pl.col("MASCARA").is_in(escolas_ativas_mascaras))
            if len(invalido_educ) > 0:
                raise ValueError(f"Ano 2006: Curso técnico ativo de escola inativa ou não encontrada. Exemplo: {invalido_educ.head(3)}")
            
            # Retornar removendo colunas temporárias
            return df.drop(["ANO", "CODMUNIC", "DEP", "LOC", "MASCARA"])



def ler_ano_atual(pasta: Path, ano: int, valid_municipios: set[str]) -> pl.DataFrame:
    caminho_zip = pasta / f"censo-escolar/censo-escolar_{ano}.zip"
    
    with zipfile.ZipFile(caminho_zip, 'r') as z:
        candidatos = [info for info in z.infolist() if 'microdados_ed_basica' in info.filename.lower() and info.filename.lower().endswith('.csv')]
        if len(candidatos) != 1:
            raise ValueError(f"Ano {ano}: esperado exatamente 1 arquivo CSV de microdados_ed_basica no ZIP, encontrados {len(candidatos)}.")
        
        membro = candidatos[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extract(membro, tmpdir)
            arquivo_extraido = Path(tmpdir) / membro.filename
            
            schema_header = pl.read_csv(arquivo_extraido, separator=";", n_rows=1, encoding="utf8-lossy", infer_schema_length=0)
            colunas_no_arquivo = set(schema_header.columns)
            
            colunas_obrigatorias = ["CO_MUNICIPIO", "TP_DEPENDENCIA", "TP_LOCALIZACAO", "TP_SITUACAO_FUNCIONAMENTO"]
            for col_orig, _ in COLUNAS_QUANTIDADE:
                colunas_obrigatorias.append(col_orig)
            
            for col in colunas_obrigatorias:
                if col not in colunas_no_arquivo:
                    raise ValueError(f"Ano {ano}: coluna obrigatória {col} ausente no CSV.")
            
            colunas_para_ler = list(colunas_obrigatorias)
            if "NU_ANO_CENSO" in colunas_no_arquivo:
                colunas_para_ler.append("NU_ANO_CENSO")
                
            df = pl.read_csv(
                arquivo_extraido,
                separator=";",
                encoding="utf8-lossy",
                infer_schema_length=0,
                columns=colunas_para_ler
            )
            
            if "NU_ANO_CENSO" in df.columns:
                errados = df.filter(pl.col("NU_ANO_CENSO") != str(ano))
                if len(errados) > 0:
                    raise ValueError(f"Ano {ano}: Há registros com NU_ANO_CENSO diferente de {ano}. Exemplo: {errados.head(3)}")
                df = df.drop("NU_ANO_CENSO")
            
            df = df.filter(pl.col("TP_SITUACAO_FUNCIONAMENTO") == "1")
            
            dep_map = {"1": "federal", "2": "estadual", "3": "municipal", "4": "privada"}
            loc_map = {"1": "urbana", "2": "rural"}
            
            invalido_dep = df.filter(~pl.col("TP_DEPENDENCIA").is_in(dep_map.keys()) | pl.col("TP_DEPENDENCIA").is_null())
            if len(invalido_dep) > 0:
                raise ValueError(f"Ano {ano}: Valores inválidos em TP_DEPENDENCIA. Exemplo: {invalido_dep.head(3)}")
                
            invalido_loc = df.filter(~pl.col("TP_LOCALIZACAO").is_in(loc_map.keys()) | pl.col("TP_LOCALIZACAO").is_null())
            if len(invalido_loc) > 0:
                raise ValueError(f"Ano {ano}: Valores inválidos em TP_LOCALIZACAO. Exemplo: {invalido_loc.head(3)}")
            
            df = df.with_columns(
                pl.col("TP_DEPENDENCIA").replace(dep_map).alias("dependencia"),
                pl.col("TP_LOCALIZACAO").replace(loc_map).alias("localizacao")
            )
            
            invalido_mun = df.filter(~pl.col("CO_MUNICIPIO").is_in(valid_municipios) | pl.col("CO_MUNICIPIO").is_null())
            if len(invalido_mun) > 0:
                raise ValueError(f"Ano {ano}: Municípios inválidos ou nulos em CO_MUNICIPIO. Exemplo: {invalido_mun.head(3)}")
            
            df = df.rename({"CO_MUNICIPIO": "cod_municipio"})
            
            exprs = []
            for orig, _ in COLUNAS_QUANTIDADE:
                invalido = df.filter(~pl.col(orig).is_null() & (pl.col(orig) != "") & ~pl.col(orig).str.contains(r"^\d+$"))
                if len(invalido) > 0:
                    raise ValueError(f"Ano {ano}: Valores não inteiros ou negativos na coluna {orig}. Exemplo: {invalido.head(3)}")
                
                exprs.append(
                    pl.when(pl.col(orig) == "").then(None).otherwise(pl.col(orig)).cast(pl.Int64).alias(orig)
                )
            
            df = df.with_columns(exprs)
            df = df.with_columns(pl.lit(ano).cast(pl.Int16).alias("ano"))
            
            return df

def harmonizar(pasta: Path | str, municipios: pl.DataFrame) -> pl.DataFrame:
    pasta = Path(pasta)
    valid_municipios = set(municipios["cod_municipio"].to_list())
    
    dfs = []
    for ano in ANOS_TODOS:
        if ano == 2006:
            df_ano = ler_ano_2006(pasta, valid_municipios)
        else:
            df_ano = ler_ano_atual(pasta, ano, valid_municipios)
        
        aggs = [pl.len().cast(pl.Int64).alias("escolas")]
        for orig, dest in COLUNAS_QUANTIDADE:
            aggs.append(
                pl.when(pl.col(orig).is_null().all())
                .then(None)
                .otherwise(pl.col(orig).sum())
                .alias(dest)
            )
            
        df_agg = (
            df_ano
            .group_by(["cod_municipio", "ano", "dependencia", "localizacao"])
            .agg(aggs)
        )
        dfs.append(df_agg)
        
    df_final = pl.concat(dfs)
    df_final = df_final.sort(["cod_municipio", "ano", "dependencia", "localizacao"])
    
    col_order = ["cod_municipio", "ano", "dependencia", "localizacao", "escolas"]
    for _, dest in COLUNAS_QUANTIDADE:
        col_order.append(dest)
        
    df_final = df_final.select(col_order)
    
    return df_final
