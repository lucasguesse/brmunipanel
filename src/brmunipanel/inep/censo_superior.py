"""
Censo da Educação Superior - INEP

Source: Instituto Nacional de Estudos e Pesquisas Educacionais Anísio Teixeira (INEP)
Source tables: CADASTRO_CURSOS and CADASTRO_IES
Key: municipality, year, administrative category

Caveats:
- Only in-person education enters the columns. Distance-learning courses are not counted.
- Teachers are those of the entire institution, in the seat municipality, and include those working in distance-learning courses of an institution that also offers in-person courses.
- The 'especial' category was created by INEP in 2012.
- The absence of a row in a covered year means that there is no institution with an in-person course or seat in the municipality for that category.
- From 2000 to 2008: the layout is different; enrollment is that of the first semester; teachers from 2000 to 2003 are the total minus those on leave, and those from 2004 to 2008 come from the practicing teachers variable; the old layout records offerings in more small municipalities than the new one (1,365 municipalities with courses in 2008 and 1,159 in 2009); teachers increase from 321 thousand in 2008 to 341 thousand in 2009, when INEP began collecting the census per teacher; and the sum of undergraduate enrollments is about 0.05% below the published total.
"""
from __future__ import annotations

from pathlib import Path
import zipfile
import tempfile
import polars as pl
import re

from brmunipanel.inep.conexao import criar_sessao
from brmunipanel.nucleo import Requisicao, RespostaInvalida, baixar_lote

ANOS_ATUAIS = list(range(2009, 2025))
ANOS_ANTIGOS = list(range(2000, 2009))
ANOS_TODOS = list(range(2000, 2025))

def validar_zip(conteudo: bytes):
    if not conteudo.startswith(b"PK\x03\x04"):
        raise RespostaInvalida("O conteúdo não é um arquivo ZIP válido.")

def baixar(pasta: Path | str, **opcoes):
    pasta = Path(pasta)
    reqs = []
    for ano in ANOS_TODOS:
        reqs.append(
            Requisicao(
                chave=f"censo-superior/{ano}",
                url=f"https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_{ano}.zip",
                arquivo=f"censo-superior/censo-superior_{ano}.zip",
                metodo="GET",
                compactar=False
            )
        )
    sessao = opcoes.pop("sessao", None) or criar_sessao()
    baixar_lote(reqs, pasta, sessao=sessao, validar=validar_zip, intervalo=1.0, **opcoes)

def ler_ano_antigo(pasta: Path, ano: int, valid_municipios: set[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    caminho_zip = pasta / f"censo-superior/censo-superior_{ano}.zip"
    
    with zipfile.ZipFile(caminho_zip, 'r') as z:
        cand_grad = [info for info in z.infolist() if info.filename.lower().endswith('/graduacao_presencial.csv')]
        if len(cand_grad) != 1:
            raise ValueError(f"Ano {ano}: esperado exatamente 1 arquivo CSV de graduacao_presencial.csv no ZIP, encontrados {len(cand_grad)}.")
        
        cand_seq = [info for info in z.infolist() if info.filename.lower().endswith('/forme_presencial.csv')]
        if len(cand_seq) != 1:
            raise ValueError(f"Ano {ano}: esperado exatamente 1 arquivo CSV de forme_presencial.csv no ZIP, encontrados {len(cand_seq)}.")
            
        cand_ies = [info for info in z.infolist() if info.filename.lower().endswith('/instituicao.csv')]
        if len(cand_ies) != 1:
            raise ValueError(f"Ano {ano}: esperado exatamente 1 arquivo CSV de instituicao.csv no ZIP, encontrados {len(cand_ies)}.")
        
        id_col = "IES" if ano == 2008 else "MASCARA"
        
        def ler_arquivo(membro, id_col, col_mun, prefixes_req, is_ies=False):
            with z.open(membro.filename) as f:
                header_line = f.readline()
                header_df = pl.read_csv(header_line, separator="|", n_rows=0, encoding="utf8-lossy", quote_char=None)
            
            orig_cols = header_df.columns
            col_map = {c.strip(): c for c in orig_cols}
            
            used_clean = [id_col, col_mun]
            if is_ies:
                used_clean.append("CATEGADM")
            if "ANO" in col_map:
                used_clean.append("ANO")
                
            cols_val = []
            for prefix in prefixes_req:
                matched = [c for c in col_map if re.match(rf"^{prefix}\d+$", c)]
                if not matched and is_ies and prefix == "I07":
                    raise ValueError(f"Ano {ano}: Nenhuma coluna I07 encontrada.")
                if not matched and is_ies and prefix == "I44" and 2004 <= ano <= 2008:
                    raise ValueError(f"Ano {ano}: Nenhuma coluna I44 encontrada.")
                if not matched and not is_ies:
                    raise ValueError(f"Ano {ano}: Nenhuma coluna de matrícula ({prefix}) encontrada.")
                cols_val.extend(matched)
                
            used_clean.extend(cols_val)
            used_clean = list(dict.fromkeys(used_clean))
            used_orig = [col_map[c] for c in used_clean if c in col_map]
            
            content = z.read(membro.filename)
            df = pl.read_csv(
                content,
                separator="|",
                infer_schema_length=0,
                encoding="utf8-lossy",
                quote_char=None,
                columns=used_orig
            )
            df = df.rename({orig: clean for orig, clean in zip(used_orig, used_clean)})
            df = df.select(pl.all().str.strip_chars())
            
            if "ANO" in df.columns:
                invalido_ano = df.filter(~pl.col("ANO").is_in([str(ano)]))
                if len(invalido_ano) > 0:
                    raise ValueError(f"Ano {ano}: ANO diferente do ano do pacote. Exemplo: {invalido_ano.head(3)}")
            
            invalid_flags = df.select([
                (pl.col(c).is_not_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).any().alias(c)
                for c in cols_val
            ]).to_dicts()[0]
            
            for c, is_invalid in invalid_flags.items():
                if is_invalid:
                    bad_row = df.filter(pl.col(c).is_not_null() & (pl.col(c) != "") & ~pl.col(c).str.contains(r"^\d+$")).row(0, named=True)
                    raise ValueError(f"Ano {ano}: Valor não inteiro ou negativo em {c}. Exemplo IES/MASCARA: {bad_row[id_col]}")
            
            exprs = [pl.col(c).fill_null("0").replace("", "0").cast(pl.Int64).alias(c) for c in cols_val]
            exprs.extend([pl.col(c) for c in df.columns if c not in cols_val])
            
            df_casted = df.select(exprs)
                        
            return df_casted, cols_val
            
        col_mun_curso = "CODMUNIC_CURSO" if ano in (2007, 2008) else "CODMUNICCURSO"
        
        df_grad, cols_grad = ler_arquivo(cand_grad[0], id_col, col_mun_curso, ["C042"])
        df_seq, cols_seq = ler_arquivo(cand_seq[0], id_col, col_mun_curso, ["C281"])
        
        if 2004 <= ano <= 2008:
            df_ies, cols_ies = ler_arquivo(cand_ies[0], id_col, "CODMUNIC", ["I44"], is_ies=True)
        else:
            df_ies, cols_ies = ler_arquivo(cand_ies[0], id_col, "CODMUNIC", ["I07", "I11"], is_ies=True)
            
        df_ies = df_ies.with_columns(pl.col(id_col).str.replace(r"^0+", "", n=-1).alias("CO_IES"))
        
        ies_counts = df_ies.group_by("CO_IES").len()
        ies_repetidas = ies_counts.filter(pl.col("len") > 1)
        if len(ies_repetidas) > 0:
            raise ValueError(f"Ano {ano}: Identificador repetido em INSTITUICAO.CSV. Exemplo: {ies_repetidas.head(3)}")
            
        cat_map = {
            "FEDERAL": "federal", 
            "ESTADUAL": "estadual", 
            "MUNICIPAL": "municipal", 
            "PRIVADA": "privada"
        }
        
        invalido_cat = df_ies.filter(~pl.col("CATEGADM").is_in(cat_map.keys()) | pl.col("CATEGADM").is_null())
        if len(invalido_cat) > 0:
            raise ValueError(f"Ano {ano}: CATEGADM fora da lista. Exemplo: {invalido_cat.head(3)}")
            
        df_ies = df_ies.with_columns(pl.col("CATEGADM").replace(cat_map).alias("categoria"))
        
        if 2004 <= ano <= 2008:
            df_ies = df_ies.with_columns(pl.sum_horizontal(cols_ies).alias("QT_DOC_EXE_CAST"))
        else:
            cols_07 = [c for c in cols_ies if c.startswith("I07")]
            cols_11 = [c for c in cols_ies if c.startswith("I11")]
            sum_07 = pl.sum_horizontal(cols_07) if cols_07 else pl.lit(0)
            sum_11 = pl.sum_horizontal(cols_11) if cols_11 else pl.lit(0)
            df_ies = df_ies.with_columns((sum_07 - sum_11).alias("QT_DOC_EXE_CAST"))
            
            invalido_doc = df_ies.filter(pl.col("QT_DOC_EXE_CAST") < 0)
            if len(invalido_doc) > 0:
                raise ValueError(f"Ano {ano}: Mais afastados que o total. Exemplo: {invalido_doc.head(3)}")
                
        df_ies = df_ies.with_columns(
            pl.when(pl.col("CODMUNIC").str.len_chars() == 12)
            .then(pl.col("CODMUNIC").str.slice(0, 2) + pl.col("CODMUNIC").str.slice(7, 5))
            .otherwise(pl.col("CODMUNIC"))
            .alias("CO_MUNICIPIO_IES")
        )
        
        df_grad = df_grad.with_columns(pl.col(id_col).str.replace(r"^0+", "", n=-1).alias("CO_IES"))
        df_grad = df_grad.with_columns(
            pl.when(pl.col(col_mun_curso).str.len_chars() == 12)
            .then(pl.col(col_mun_curso).str.slice(0, 2) + pl.col(col_mun_curso).str.slice(7, 5))
            .otherwise(pl.col(col_mun_curso))
            .alias("CO_MUNICIPIO")
        )
        df_grad = df_grad.with_columns(pl.sum_horizontal(cols_grad).alias("QT_MAT"))
        
        df_seq = df_seq.with_columns(pl.col(id_col).str.replace(r"^0+", "", n=-1).alias("CO_IES"))
        df_seq = df_seq.with_columns(
            pl.when(pl.col(col_mun_curso).str.len_chars() == 12)
            .then(pl.col(col_mun_curso).str.slice(0, 2) + pl.col(col_mun_curso).str.slice(7, 5))
            .otherwise(pl.col(col_mun_curso))
            .alias("CO_MUNICIPIO")
        )
        df_seq = df_seq.with_columns(pl.sum_horizontal(cols_seq).alias("QT_MAT"))
        
        df_cursos = pl.concat([
            df_grad.select(["CO_MUNICIPIO", "CO_IES", "QT_MAT"]),
            df_seq.select(["CO_MUNICIPIO", "CO_IES", "QT_MAT"])
        ])
        
        df_cursos = df_cursos.join(df_ies.select(["CO_IES", "categoria"]), on="CO_IES", how="left")
        faltantes = df_cursos.filter(pl.col("categoria").is_null())
        if len(faltantes) > 0:
            raise ValueError(f"Ano {ano}: Curso de instituição que não está em INSTITUICAO.CSV. Exemplo: {faltantes.head(3)}")
            
        ies_com_cursos = df_cursos.select("CO_IES").unique()
        ies_presenciais_list = ies_com_cursos["CO_IES"].to_list()
        df_ies = df_ies.filter(pl.col("CO_IES").is_in(ies_presenciais_list))
        
        invalido_mun_cursos = df_cursos.filter(~pl.col("CO_MUNICIPIO").is_in(valid_municipios) | pl.col("CO_MUNICIPIO").is_null())
        if len(invalido_mun_cursos) > 0:
             raise ValueError(f"Ano {ano}: Municípios inválidos ou nulos na tabela de cursos. Exemplo: {invalido_mun_cursos.head(3)}")
             
        invalido_mun_ies = df_ies.filter(~pl.col("CO_MUNICIPIO_IES").is_in(valid_municipios) | pl.col("CO_MUNICIPIO_IES").is_null())
        if len(invalido_mun_ies) > 0:
             raise ValueError(f"Ano {ano}: Municípios inválidos ou nulos na tabela de IES. Exemplo: {invalido_mun_ies.head(3)}")
             
        df_cursos = df_cursos.select(["CO_MUNICIPIO", "CO_IES", "categoria", "QT_MAT"])
        df_ies = df_ies.select(["CO_IES", "CO_MUNICIPIO_IES", "categoria", "QT_DOC_EXE_CAST"])
        
        return df_cursos, df_ies

def ler_ano_atual(pasta: Path, ano: int, valid_municipios: set[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    caminho_zip = pasta / f"censo-superior/censo-superior_{ano}.zip"
    
    with zipfile.ZipFile(caminho_zip, 'r') as z:
        cand_cursos = [info for info in z.infolist() if 'cadastro_cursos' in info.filename.lower() and info.filename.lower().endswith('.csv')]
        if len(cand_cursos) != 1:
            raise ValueError(f"Ano {ano}: esperado exatamente 1 arquivo CSV de CADASTRO_CURSOS no ZIP, encontrados {len(cand_cursos)}.")
        
        cand_ies = [info for info in z.infolist() if '_ies_' in info.filename.lower() and info.filename.lower().endswith('.csv')]
        if len(cand_ies) != 1:
            raise ValueError(f"Ano {ano}: esperado exatamente 1 arquivo CSV de IES no ZIP, encontrados {len(cand_ies)}.")
            
        membro_cursos = cand_cursos[0]
        membro_ies = cand_ies[0]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            z.extract(membro_cursos, tmpdir)
            arquivo_cursos = Path(tmpdir) / membro_cursos.filename
            
            z.extract(membro_ies, tmpdir)
            arquivo_ies = Path(tmpdir) / membro_ies.filename
            
            # Courses
            colunas_cursos = ["CO_MUNICIPIO", "CO_IES", "TP_MODALIDADE_ENSINO", "TP_CATEGORIA_ADMINISTRATIVA", "QT_MAT"]
            df_cursos = pl.read_csv(
                arquivo_cursos,
                separator=";",
                encoding="utf8-lossy",
                infer_schema_length=0,
                columns=colunas_cursos,
                schema_overrides={"CO_MUNICIPIO": pl.Utf8, "CO_IES": pl.Utf8, "TP_MODALIDADE_ENSINO": pl.Utf8, "TP_CATEGORIA_ADMINISTRATIVA": pl.Utf8, "QT_MAT": pl.Utf8}
            )
            
            # IES
            col_docentes = "QT_DOCENTE_EXE" if ano == 2009 else "QT_DOC_EXE"
            colunas_ies = ["CO_IES", "CO_MUNICIPIO_IES", "TP_CATEGORIA_ADMINISTRATIVA", col_docentes]
            df_ies = pl.read_csv(
                arquivo_ies,
                separator=";",
                encoding="utf8-lossy",
                infer_schema_length=0,
                columns=colunas_ies,
                schema_overrides={"CO_IES": pl.Utf8, "CO_MUNICIPIO_IES": pl.Utf8, "TP_CATEGORIA_ADMINISTRATIVA": pl.Utf8, col_docentes: pl.Utf8}
            )
            
            # Filter in-person courses
            df_cursos = df_cursos.filter(pl.col("TP_MODALIDADE_ENSINO") == "1")
            
            # Category mapping
            cat_map = {
                "1": "federal", 
                "2": "estadual", 
                "3": "municipal", 
                "4": "privada", 
                "5": "privada", 
                "6": "privada", 
                "8": "privada", 
                "9": "privada", 
                "7": "especial"
            }
            
            for nome, df, col_mun in [("Cursos", df_cursos, "CO_MUNICIPIO"), ("IES", df_ies, "CO_MUNICIPIO_IES")]:
                invalido_cat = df.filter(~pl.col("TP_CATEGORIA_ADMINISTRATIVA").is_in(cat_map.keys()) | pl.col("TP_CATEGORIA_ADMINISTRATIVA").is_null())
                if len(invalido_cat) > 0:
                    raise ValueError(f"Ano {ano}: Valores inválidos em TP_CATEGORIA_ADMINISTRATIVA na tabela de {nome}. Exemplo: {invalido_cat.head(3)}")
                
                if nome == "Cursos":
                    invalido_mun = df.filter(~pl.col(col_mun).is_in(valid_municipios) | pl.col(col_mun).is_null())
                    if len(invalido_mun) > 0:
                         raise ValueError(f"Ano {ano}: Municípios inválidos ou nulos em {col_mun} na tabela de {nome}. Exemplo: {invalido_mun.head(3)}")
            
            df_cursos = df_cursos.with_columns(
                pl.col("TP_CATEGORIA_ADMINISTRATIVA").replace(cat_map).alias("categoria")
            )
            df_ies = df_ies.with_columns(
                pl.col("TP_CATEGORIA_ADMINISTRATIVA").replace(cat_map).alias("categoria")
            )
            
            # Validate and convert qt_mat and qt_docentes
            for nome, df, col_q in [("Cursos", df_cursos, "QT_MAT"), ("IES", df_ies, col_docentes)]:
                invalido = df.filter(~pl.col(col_q).str.contains(r"^\d+$") | pl.col(col_q).is_null())
                if len(invalido) > 0:
                    raise ValueError(f"Ano {ano}: Valores não inteiros, negativos ou vazios na coluna {col_q} da tabela de {nome}. Exemplo: {invalido.head(3)}")
            
            df_cursos = df_cursos.with_columns(pl.col("QT_MAT").cast(pl.Int64))
            df_ies = df_ies.with_columns(pl.col(col_docentes).cast(pl.Int64).alias("QT_DOC_EXE_CAST"))
            
            # Verify integrity IES <-> Courses
            ies_com_cursos = df_cursos.select(["CO_IES", "categoria"]).unique()
            ies_cadastro = df_ies.select(["CO_IES", "categoria"]).unique()
            
            join_ies = ies_com_cursos.join(ies_cadastro, on="CO_IES", how="left", suffix="_cadastro")
            
            faltantes = join_ies.filter(pl.col("categoria_cadastro").is_null())
            if len(faltantes) > 0:
                raise ValueError(f"Ano {ano}: Instituição com curso presencial ausente da tabela de instituições. Exemplo: {faltantes.head(3)}")
                
            divergentes = join_ies.filter(pl.col("categoria") != pl.col("categoria_cadastro"))
            if len(divergentes) > 0:
                raise ValueError(f"Ano {ano}: Instituição com curso presencial com categoria divergente na tabela de instituições. Exemplo: {divergentes.head(3)}")
            
            # Filter only in-person IES
            ies_presenciais_list = ies_com_cursos["CO_IES"].to_list()
            df_ies_presenciais = df_ies.filter(pl.col("CO_IES").is_in(ies_presenciais_list))
            
            # Validate IES municipality code here (only for in-person IES)
            invalido_mun_ies = df_ies_presenciais.filter(~pl.col("CO_MUNICIPIO_IES").is_in(valid_municipios) | pl.col("CO_MUNICIPIO_IES").is_null())
            if len(invalido_mun_ies) > 0:
                 raise ValueError(f"Ano {ano}: Municípios inválidos ou nulos em CO_MUNICIPIO_IES na tabela de IES. Exemplo: {invalido_mun_ies.head(3)}")
            
            return df_cursos, df_ies_presenciais

def agregar(df_cursos: pl.DataFrame, df_ies_presenciais: pl.DataFrame, ano: int) -> pl.DataFrame:
    # Courses aggregation
    agg_cursos = (
        df_cursos
        .rename({"CO_MUNICIPIO": "cod_municipio"})
        .group_by(["cod_municipio", "categoria"])
        .agg([
            pl.col("CO_IES").n_unique().cast(pl.Int64).alias("instituicoes"),
            pl.col("QT_MAT").sum().cast(pl.Int64).alias("matriculas")
        ])
    )
    
    # IES aggregation
    agg_ies = (
        df_ies_presenciais
        .rename({"CO_MUNICIPIO_IES": "cod_municipio"})
        .group_by(["cod_municipio", "categoria"])
        .agg([
            pl.col("CO_IES").n_unique().cast(pl.Int64).alias("instituicoes_sede"),
            pl.col("QT_DOC_EXE_CAST").sum().cast(pl.Int64).alias("docentes_sede")
        ])
    )
    
    # Full outer join
    res = agg_cursos.join(agg_ies, on=["cod_municipio", "categoria"], how="full", coalesce=True)
    
    # Fill nulls with zero where applicable
    res = res.with_columns([
        pl.col("instituicoes").fill_null(0).cast(pl.Int64),
        pl.col("matriculas").fill_null(0).cast(pl.Int64),
        pl.col("instituicoes_sede").fill_null(0).cast(pl.Int64),
        pl.col("docentes_sede").fill_null(0).cast(pl.Int64),
    ])
    
    res = res.with_columns(pl.lit(ano).cast(pl.Int16).alias("ano"))
    
    return res

def harmonizar(pasta: Path | str, municipios: pl.DataFrame) -> pl.DataFrame:
    pasta = Path(pasta)
    valid_municipios = set(municipios["cod_municipio"].to_list())
    
    dfs = []
    for ano in ANOS_ANTIGOS:
        df_cursos, df_ies = ler_ano_antigo(pasta, ano, valid_municipios)
        df_ano = agregar(df_cursos, df_ies, ano)
        dfs.append(df_ano)
        
    for ano in ANOS_ATUAIS:
        df_cursos, df_ies = ler_ano_atual(pasta, ano, valid_municipios)
        df_ano = agregar(df_cursos, df_ies, ano)
        dfs.append(df_ano)
        
    df_final = pl.concat(dfs)
    df_final = df_final.sort(["cod_municipio", "ano", "categoria"])
    
    col_order = ["cod_municipio", "ano", "categoria", "instituicoes", "matriculas", "instituicoes_sede", "docentes_sede"]
    df_final = df_final.select(col_order)
    
    return df_final
