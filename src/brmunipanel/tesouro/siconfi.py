"""Despesa municipal empenhada por função em 2013–2023 (SICONFI, Tesouro Nacional).

A saída tem só as 28 funções da classificação funcional.
O total declarado e a despesa intraorçamentária são usados só nas conferências internas.

Fonte: consulta "Contas Anuais" do portal do SICONFI, tabela "Despesas por Função (Anexo I-E)", escopo "Municípios",
com um arquivo por exercício e todos os municípios em cada arquivo. O portal barra o download por script com um
captcha, então os arquivos são baixados à mão e postos na pasta de dados brutos da fonte. `baixar` não acessa
a rede: confere o cabeçalho de cada `.zip` e o registra no manifesto. Para refazer o download, abrir `URL_PORTAL`,
escolher o exercício, o escopo e a tabela acima, deixar o período de homologação em branco e salvar o `.zip` na
pasta, com qualquer nome, porque o ano vem de dentro do arquivo. O arquivo de 2024 é registrado e não é harmonizado.

A harmonização usa só as linhas de "Despesas Empenhadas". A função com linha própria usa o valor da linha; sem linha
própria, recebe a soma das suas subfunções; sem nenhuma das duas, vale zero. `desp_total_funcoes` é a linha de total
sem as intraorçamentárias e fica nula quando a declaração não a traz. `desp_intraorcamentaria` é a linha de total
intraorçamentário, ou zero quando ela não existe, e `declara_intraorcamentaria` é verdadeira quando ela é maior que
zero. A conta "Demais Subfunções" sem código de função, que só aparece em 2017, é ignorada. O município sem despesa
empenhada no ano não gera linha, e o Distrito Federal fica fora. A saída segue `despesa_funcao.ESQUEMA`.
"""
import csv
import re
import zipfile
from pathlib import Path

import polars as pl

from brmunipanel import nucleo
from brmunipanel.tesouro.despesa_funcao import COLUNAS_PUBLICADAS, ESQUEMA, FUNCOES

ANOS = tuple(range(2013, 2024))
URL_PORTAL = "https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra/finbra_list.jsf"
ESCOPO = "Municípios"
TABELA = "Despesas por Função (Anexo I-E)"
CABECALHO = "Instituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor"


def ler_cabecalho(caminho_zip: Path) -> dict:
    with zipfile.ZipFile(caminho_zip) as zf:
        membros_csv = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(membros_csv) != 1:
            raise ValueError(f"{caminho_zip.name}: Esperado 1 arquivo CSV, encontrados {len(membros_csv)}")
            
        with zf.open(membros_csv[0]) as f:
            linhas = []
            for _ in range(4):
                try:
                    linha = f.readline().decode("latin-1").strip()
                    linhas.append(linha)
                except Exception:
                    raise ValueError(f"{caminho_zip.name}: Não foi possível ler as 4 primeiras linhas.")
                    
            if len(linhas) < 4:
                raise ValueError(f"{caminho_zip.name}: Arquivo curto, menos de 4 linhas.")
                
            l1, l2, l3, l4 = linhas
            
            if not l1.startswith("Exercício: "):
                raise ValueError(f"{caminho_zip.name}: Linha 1 inválida: {l1}")
            exercicio = int(l1.split(": ")[1])
            
            if not l2.startswith("Escopo: "):
                raise ValueError(f"{caminho_zip.name}: Linha 2 inválida: {l2}")
            escopo = l2.split(": ")[1]
            if escopo != ESCOPO:
                raise ValueError(f"{caminho_zip.name}: Escopo inválida: {escopo}")
                
            if not l3.startswith("Tabela: "):
                raise ValueError(f"{caminho_zip.name}: Linha 3 inválida: {l3}")
            tabela = l3.split(": ")[1]
            if tabela != TABELA:
                raise ValueError(f"{caminho_zip.name}: Tabela inválida: {tabela}")
                
            if l4 != CABECALHO:
                raise ValueError(f"{caminho_zip.name}: Cabeçalho inválido: {l4}")
                
            return {
                "exercicio": exercicio,
                "escopo": escopo,
                "tabela": tabela
            }


def baixar(pasta: Path, **opcoes) -> list[dict]:
    pasta = Path(pasta)
    if not pasta.exists():
        pasta.mkdir(parents=True)
    
    zips = sorted(pasta.glob("*.zip"), key=lambda p: p.name)
    anos_encontrados = {}
    registros = []
    
    for z in zips:
        cab = ler_cabecalho(z)
        ano = cab["exercicio"]
        
        if ano in anos_encontrados:
            raise ValueError(f"Dois arquivos com mesmo exercício {ano}: {anos_encontrados[ano]} e {z.name}")
        anos_encontrados[ano] = z.name
        
        registro, _ = nucleo.registrar_manual(
            pasta, 
            chave=f"contas_anuais_{ano}", 
            arquivo=z.name, 
            url=URL_PORTAL, 
            parametros={"exercicio": str(ano), "escopo": ESCOPO, "tabela": TABELA}
        )
        registros.append(registro)
        
    anos_faltantes = [ano for ano in ANOS if ano not in anos_encontrados]
    if anos_faltantes:
        raise FileNotFoundError(
            f"Faltam anos: {anos_faltantes}. "
            f"Baixe manualmente da URL {URL_PORTAL}, exercício correspondente, escopo '{ESCOPO}', "
            f"tabela '{TABELA}', homologação em branco, e salve na pasta {pasta}."
        )
        
    return registros


def ler_arquivo(pasta: Path, arquivo: str) -> pl.DataFrame:
    caminho = Path(pasta) / arquivo
    
    with zipfile.ZipFile(caminho) as zf:
        membros_csv = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        with zf.open(membros_csv[0]) as f:
            linhas = f.read().decode("latin-1").splitlines()
            
    linhas = linhas[3:]
    
    reader = csv.reader(linhas, delimiter=";")
    headers = next(reader)
    
    idx_cod = headers.index("Cod.IBGE")
    idx_coluna = headers.index("Coluna")
    idx_conta = headers.index("Conta")
    idx_valor = headers.index("Valor")
    
    dados = []
    for i, row in enumerate(reader):
        if not row:
            continue
        if len(row) != len(headers):
            raise ValueError(f"{arquivo}: linha {i + 5} com número de campos diferente do cabeçalho.")
        cod_mun = row[idx_cod].replace(" ", "")
        coluna = row[idx_coluna]
        conta = row[idx_conta].strip()
        
        v_str = row[idx_valor].strip()
        if not v_str:
            valor = None
        else:
            valor = float(v_str.replace(",", "."))
            
        dados.append((cod_mun, coluna, conta, valor))
        
    df = pl.DataFrame(
        dados, 
        schema={"cod_municipio": pl.String, "coluna": pl.String, "conta": pl.String, "valor": pl.Float64},
        orient="row"
    )
    return df


def processar_declaracao(itens: list[dict]) -> tuple[dict | None, list[str]]:
    empenhadas = [i for i in itens if i["coluna"] == "Despesas Empenhadas"]
    if not empenhadas:
        return None, []
        
    avisos = []
    
    linhas_funcao = {}
    linhas_subfuncao = {}
    total_funcao = None
    intra = []
    
    for item in empenhadas:
        conta = item["conta"].strip()
        valor = item["valor"]
        
        if valor is None:
            valor = 0.0
            avisos.append(f"valor_nulo:{conta}")
            
        if re.match(r"^(\d{2}) - ", conta):
            cod = conta[:2]
            if not (1 <= int(cod) <= 28):
                avisos.append(f"funcao_fora_da_classificacao:{cod}")
                continue
            if cod in linhas_funcao:
                raise ValueError(f"Duas linhas de função com mesmo código {cod}")
            linhas_funcao[cod] = valor
            
        elif re.match(r"^(?:(\d{2})\.\d{3}|FU(\d{2})) - ", conta):
            m = re.match(r"^(?:(\d{2})\.\d{3}|FU(\d{2})) - ", conta)
            cod = m.group(1) or m.group(2)
            if not (1 <= int(cod) <= 28):
                avisos.append(f"funcao_fora_da_classificacao:{cod}")
                continue
            linhas_subfuncao.setdefault(cod, []).append(valor)
            
        elif conta == "Demais Subfunções":
            if "residuo_sem_codigo" not in avisos:
                avisos.append("residuo_sem_codigo")
            
        elif "exceto" in conta.lower() and "intra" in conta.lower():
            if total_funcao is not None:
                raise ValueError("Duas linhas de total por função")
            total_funcao = valor
            
        elif "intra" in conta.lower() and "exceto" not in conta.lower():
            intra.append(valor)
            
        else:
            avisos.append(f"conta_desconhecida:{conta}")
            
    ret = {}
    for cod, _, c_out in FUNCOES:
        if cod in linhas_funcao:
            ret[c_out] = linhas_funcao[cod]
        elif cod in linhas_subfuncao:
            ret[c_out] = sum(linhas_subfuncao[cod])
            avisos.append(f"funcao_por_subfuncoes:{cod}")
        else:
            ret[c_out] = 0.0
            
    if total_funcao is not None:
        ret["desp_total_funcoes"] = total_funcao
    else:
        ret["desp_total_funcoes"] = None
        avisos.append("sem_total")
        
    if not intra:
        ret["desp_intraorcamentaria"] = 0.0
    else:
        ret["desp_intraorcamentaria"] = sum(intra)
        if len(intra) > 1:
            avisos.append("intra_em_mais_de_uma_linha")
            
    ret["declara_intraorcamentaria"] = ret["desp_intraorcamentaria"] > 0
    
    return ret, avisos


def harmonizar(pasta: Path, municipios: pl.DataFrame, relatorio: list[dict] | None = None) -> pl.DataFrame:
    pasta = Path(pasta)
    manifesto = nucleo.ler_manifesto(pasta)
    
    linhas = []
    valid_cods = set(municipios.select("cod_municipio").to_series().to_list())
    
    for ano in ANOS:
        chave = f"contas_anuais_{ano}"
        if chave not in manifesto:
            raise FileNotFoundError(f"Chave {chave} não encontrada no manifesto. Rode a etapa 'baixar'.")
            
        arquivo = manifesto[chave]["arquivo"]
        df = ler_arquivo(pasta, arquivo)
        mun_todos = df.select("cod_municipio").unique().to_series().to_list()
        
        df_empenhada = df.filter(pl.col("coluna") == "Despesas Empenhadas")
        df_dict = df_empenhada.partition_by("cod_municipio", as_dict=True)
        
        n_harmonizados = 0
        for cod_mun in mun_todos:
            if len(cod_mun) != 7:
                if relatorio is not None:
                    relatorio.append({"cod_municipio": cod_mun, "ano": ano, "tipo": "codigo_invalido"})
                continue
            if cod_mun.startswith("53"):
                if relatorio is not None:
                    relatorio.append({"cod_municipio": cod_mun, "ano": ano, "tipo": "distrito_federal"})
                continue
            if cod_mun not in valid_cods:
                if relatorio is not None:
                    relatorio.append({"cod_municipio": cod_mun, "ano": ano, "tipo": "fora_da_dtb"})
                continue
                
            if (cod_mun,) not in df_dict:
                if relatorio is not None:
                    relatorio.append({"cod_municipio": cod_mun, "ano": ano, "tipo": "sem_despesa_empenhada"})
                continue
                
            itens = df_dict[(cod_mun,)].to_dicts()
            ret, avisos = processar_declaracao(itens)
            
            if ret is None:
                if relatorio is not None:
                    relatorio.append({"cod_municipio": cod_mun, "ano": ano, "tipo": "sem_despesa_empenhada"})
                continue
                
            if relatorio is not None:
                for aviso in avisos:
                    relatorio.append({"cod_municipio": cod_mun, "ano": ano, "tipo": aviso})
                    
            ret["cod_municipio"] = cod_mun
            ret["ano"] = ano
            ret["fonte"] = "siconfi"
            linhas.append(ret)
            n_harmonizados += 1
            
        print(f"SICONFI {ano}: harmonizados {n_harmonizados} municípios.")
        
    df_out = pl.DataFrame(linhas, schema=ESQUEMA).select(COLUNAS_PUBLICADAS)
    df_out = df_out.sort(["cod_municipio", "ano"])
    return df_out
