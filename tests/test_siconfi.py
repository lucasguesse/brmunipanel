import gzip
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from brmunipanel import nucleo
from brmunipanel.tesouro import despesa_funcao, finbra, siconfi
from brmunipanel.tesouro.despesa_funcao import ESQUEMA
from brmunipanel.tesouro.finbra import processar_tabela

def test_ler_cabecalho(tmp_path):
    z1 = tmp_path / "teste.zip"
    with zipfile.ZipFile(z1, "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    
    cab = siconfi.ler_cabecalho(z1)
    assert cab == {"exercicio": 2013, "escopo": "Municípios", "tabela": "Despesas por Função (Anexo I-E)"}
    
    # Wrong scope
    with zipfile.ZipFile(tmp_path / "t2.zip", "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Estados/DF\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    with pytest.raises(ValueError, match="Estados/DF"):
        siconfi.ler_cabecalho(tmp_path / "t2.zip")
        
    # Other table
    with zipfile.ZipFile(tmp_path / "t3.zip", "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Outra Tabela\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    with pytest.raises(ValueError, match="Outra Tabela"):
        siconfi.ler_cabecalho(tmp_path / "t3.zip")
        
    # 4th line header
    with zipfile.ZipFile(tmp_path / "t4.zip", "w") as zf:
        zf.writestr("finbra.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Valor\n".encode("latin-1"))
    with pytest.raises(ValueError, match="Cabeçalho inválido"):
        siconfi.ler_cabecalho(tmp_path / "t4.zip")
        
    # Two CSV files
    with zipfile.ZipFile(tmp_path / "t5.zip", "w") as zf:
        zf.writestr("f1.csv", "")
        zf.writestr("f2.csv", "")
    with pytest.raises(ValueError, match="encontrados 2"):
        siconfi.ler_cabecalho(tmp_path / "t5.zip")

def test_baixar(tmp_path):
    for ano in siconfi.ANOS:
        with zipfile.ZipFile(tmp_path / f"arq_{ano}.zip", "w") as zf:
            zf.writestr("f.csv", f"Exercício: {ano}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            
    # List and register
    registros = siconfi.baixar(tmp_path)
    assert len(registros) == len(siconfi.ANOS)
    for r in registros:
        assert r["metodo"] == "MANUAL"
        
    # Second call does not create a new record
    registros2 = siconfi.baixar(tmp_path)
    assert registros == registros2

def test_baixar_falta_ano(tmp_path):
    with zipfile.ZipFile(tmp_path / "qualquer.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    
    with pytest.raises(FileNotFoundError, match="2020"):
        siconfi.baixar(tmp_path)
        
def test_baixar_nome_diferente(tmp_path):
    with zipfile.ZipFile(tmp_path / "qualquer.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
        
    with pytest.raises(FileNotFoundError):
        siconfi.baixar(tmp_path)
    manifesto = nucleo.ler_manifesto(tmp_path)
    assert "contas_anuais_2015" in manifesto
    assert manifesto["contas_anuais_2015"]["arquivo"] == "qualquer.zip"

def test_baixar_dois_arquivos(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2015\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
        
    with pytest.raises(ValueError, match="Dois arquivos com mesmo exercício 2015"):
        siconfi.baixar(tmp_path)

def test_ler_arquivo(tmp_path):
    amostra = Path(__file__).parent / "dados" / "siconfi_contas_anuais_2013_amostra.csv"
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.write(amostra, "finbra.csv")
        
    df = siconfi.ler_arquivo(tmp_path, "a.zip")
    assert df.width == 4
    assert df.schema["valor"] == pl.Float64
    assert df.schema["cod_municipio"] == pl.String
    assert all(len(c) == 7 for c in df["cod_municipio"].to_list())
    
    # Check São Paulo total explicitly
    sp_total = df.filter((pl.col("cod_municipio") == "3550308") & (pl.col("coluna") == "Despesas Empenhadas") & (pl.col("conta") == "Despesas (Exceto Intra-Orçamentárias)"))["valor"][0]
    assert sp_total == 39136092195.15
    
    # Also verify number of lines is amostra minus 4 initial
    with open(amostra, "rb") as f:
        linhas = len(f.read().splitlines())
    assert df.height == linhas - 4
    
def test_processar_declaracao_simples():
    itens = [
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 100.0},
        {"coluna": "Despesas Empenhadas", "conta": "04.122 - Sub", "valor": 50.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 1000.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Intraorçamentárias)", "valor": 10.0},
    ]
    ret, av = siconfi.processar_declaracao(itens)
    assert ret["desp_04_administracao"] == 100.0
    assert ret["desp_total_funcoes"] == 1000.0
    assert ret["desp_intraorcamentaria"] == 10.0
    assert ret["declara_intraorcamentaria"] is True
    
    # Budget function only with subfunctions
    itens2 = [
        {"coluna": "Despesas Empenhadas", "conta": "08.122 - Sub", "valor": 30.0},
        {"coluna": "Despesas Empenhadas", "conta": "08.123 - Sub", "valor": 20.0},
    ]
    ret2, av2 = siconfi.processar_declaracao(itens2)
    assert ret2["desp_08_assistencia_social"] == 50.0
    assert "funcao_por_subfuncoes:08" in av2
    assert ret2["desp_intraorcamentaria"] == 0.0
    assert ret2["declara_intraorcamentaria"] is False
    
    # Budget function without any row counts as zero
    assert ret2["desp_10_saude"] == 0.0

def test_processar_declaracao_variantes_total():
    variantes = [
        ("Despesas (Exceto Intra-Orçamentárias)", "Despesas (Intra-Orçamentárias)"),
        ("Despesas (Exceto Intraorçamentárias)", "Despesas (Intraorçamentárias)"),
        ("Despesas Exceto Intraorçamentárias", "Despesas Intraorçamentárias")
    ]
    for tex, tin in variantes:
        itens = [
            {"coluna": "Despesas Empenhadas", "conta": tex, "valor": 500.0},
            {"coluna": "Despesas Empenhadas", "conta": tin, "valor": 5.0},
        ]
        ret, av = siconfi.processar_declaracao(itens)
        assert ret["desp_total_funcoes"] == 500.0
        assert ret["desp_intraorcamentaria"] == 5.0

def test_processar_declaracao_casos_especiais():
    # Without committed expenditure
    assert siconfi.processar_declaracao([{"coluna": "Outra", "conta": "04 - Administração", "valor": 1.0}]) == (None, [])
    
    # Two rows
    with pytest.raises(ValueError, match="Duas linhas de função com mesmo código 04"):
        siconfi.processar_declaracao([
            {"coluna": "Despesas Empenhadas", "conta": "04 - A", "valor": 1.0},
            {"coluna": "Despesas Empenhadas", "conta": "04 - B", "valor": 2.0},
        ])
        
    # Budget function with code 99 generates warning
    ret, av = siconfi.processar_declaracao([
        {"coluna": "Despesas Empenhadas", "conta": "99 - Z", "valor": 1.0}
    ])
    assert "funcao_fora_da_classificacao:99" in av
    assert len(ret) == 31
    assert not any("99" in k for k in ret.keys())
    
    # Null value becomes zero
    ret, av = siconfi.processar_declaracao([
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": None},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 0.0}
    ])
    assert ret["desp_04_administracao"] == 0.0
    assert "valor_nulo:04 - Administração" in av
    
    # Without total row
    ret, av = siconfi.processar_declaracao([
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 10.0}
    ])
    assert ret["desp_total_funcoes"] is None
    assert "sem_total" in av
    
    # Other column of the same budget function does not enter
    ret, av = siconfi.processar_declaracao([
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 10.0},
        {"coluna": "Despesas Liquidadas", "conta": "04 - Administração", "valor": 5.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 10.0}
    ])
    assert ret["desp_04_administracao"] == 10.0
    
    # Budget function assembled by sum of subfunctions
    ret, av = siconfi.processar_declaracao([
        {"coluna": "Despesas Empenhadas", "conta": "10.301 - Sub", "valor": 5.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 10.0}
    ])
    assert ret["desp_10_saude"] == 5.0
    assert "funcao_por_subfuncoes:10" in av
    
def test_processar_declaracao_residuo_sem_codigo():
    itens = [
        {"coluna": "Despesas Empenhadas", "conta": "04 - Administração", "valor": 10.0},
        {"coluna": "Despesas Empenhadas", "conta": "Demais Subfunções", "valor": 5.0},
        {"coluna": "Despesas Empenhadas", "conta": "Demais Subfunções", "valor": 2.0},
        {"coluna": "Despesas Empenhadas", "conta": "Demais Subfunções", "valor": 3.0},
        {"coluna": "Despesas Empenhadas", "conta": "Despesas (Exceto Intraorçamentárias)", "valor": 10.0}
    ]
    ret, av = siconfi.processar_declaracao(itens)
    assert ret["desp_04_administracao"] == 10.0
    assert av.count("residuo_sem_codigo") == 1
    
def test_ler_arquivo_linha_curta(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.writestr("f.csv", "A\nB\nC\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n1;2;3\n".encode("latin-1"))
    with pytest.raises(ValueError, match="linha 5 com número de campos diferente do cabeçalho"):
        siconfi.ler_arquivo(tmp_path, "a.zip")

def test_ler_arquivo_linha_longa(tmp_path):
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        zf.writestr("f.csv", "A\nB\nC\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n1;2;3;4;5;6;7;8;9\n".encode("latin-1"))
    with pytest.raises(ValueError, match="linha 5 com número de campos diferente do cabeçalho"):
        siconfi.ler_arquivo(tmp_path, "a.zip")

def test_harmonizar(tmp_path):
    municipios = pl.DataFrame({"cod_municipio": ["3550308", "1600279", "4126652"], "cod_uf": ["35", "16", "41"]})
    
    for ano in siconfi.ANOS:
        with zipfile.ZipFile(tmp_path / f"a_{ano}.zip", "w") as zf:
            zf.writestr("f.csv", f"Exercício: {ano}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\nInst;3550308;SP;1;Despesas Empenhadas;04 - Administração;;10.0\nInst;1600279;AP;1;Despesas Empenhadas;08 - Assistência;;5.0\n".encode("latin-1"))
            
    siconfi.baixar(tmp_path)
    
    df = siconfi.harmonizar(tmp_path, municipios)
    assert df.columns == despesa_funcao.COLUNAS_PUBLICADAS
    assert df.schema["cod_municipio"] == pl.String
    assert df.schema["ano"] == pl.Int16
    for c in despesa_funcao.COLUNAS_PUBLICADAS[2:]:
        assert df.schema[c] == pl.Float64
    assert df.height == len(siconfi.ANOS) * 2
    assert df.is_sorted(["cod_municipio", "ano"])

def test_harmonizar_amostras_reais(tmp_path):
    amostras = [
        (2013, Path(__file__).parent / "dados" / "siconfi_contas_anuais_2013_amostra.csv"),
        (2022, Path(__file__).parent / "dados" / "siconfi_contas_anuais_2022_amostra.csv"),
    ]
    municipios = pl.DataFrame({"cod_municipio": ["3550308", "1600279", "4126652", "2905206"]})
    
    manifesto = {}
    for ano, p in amostras:
        caminho_zip = tmp_path / f"a_{ano}.zip"
        with zipfile.ZipFile(caminho_zip, "w") as zf:
            zf.write(p, "f.csv")
        manifesto[f"contas_anuais_{ano}"] = {"arquivo": caminho_zip.name}
    
    for ano in siconfi.ANOS:
        if f"contas_anuais_{ano}" not in manifesto:
            caminho_zip = tmp_path / f"a_{ano}.zip"
            with zipfile.ZipFile(caminho_zip, "w") as zf:
                zf.writestr("f.csv", f"Exercício: {ano}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            manifesto[f"contas_anuais_{ano}"] = {"arquivo": caminho_zip.name}
            
    nucleo._gravar_manifesto(tmp_path, manifesto)
    
    relatorio = []
    df = siconfi.harmonizar(tmp_path, municipios, relatorio=relatorio)
    
    sp_2013 = df.filter((pl.col("ano") == 2013) & (pl.col("cod_municipio") == "3550308"))
    assert sp_2013.height == 1
    soma_sp = sum(sp_2013[0, col] for _, _, col in despesa_funcao.FUNCOES)
    
    df_raw_2013 = siconfi.ler_arquivo(tmp_path, manifesto["contas_anuais_2013"]["arquivo"])
    itens_2013 = df_raw_2013.filter(pl.col("cod_municipio") == "3550308").to_dicts()
    ret_2013, _ = siconfi.processar_declaracao(itens_2013)
    assert abs(soma_sp - ret_2013["desp_total_funcoes"]) < 0.01
    
    sp_2022 = df.filter((pl.col("ano") == 2022) & (pl.col("cod_municipio") == "3550308"))
    assert sp_2022.height == 1
    soma_sp2 = sum(sp_2022[0, col] for _, _, col in despesa_funcao.FUNCOES)
    
    df_raw_2022 = siconfi.ler_arquivo(tmp_path, manifesto["contas_anuais_2022"]["arquivo"])
    itens_2022 = df_raw_2022.filter(pl.col("cod_municipio") == "3550308").to_dicts()
    ret_2022, _ = siconfi.processar_declaracao(itens_2022)
    assert abs(soma_sp2 - ret_2022["desp_total_funcoes"]) < 0.01
    
    lj_2013 = df.filter((pl.col("ano") == 2013) & (pl.col("cod_municipio") == "1600279"))
    assert lj_2013.height == 1
    assert lj_2013[0, "desp_10_saude"] == 9360236.83
    
    assert any(r["cod_municipio"] == "1600279" and r["ano"] == 2013 and r["tipo"].startswith("funcao_por_subfuncoes") for r in relatorio)

def test_harmonizar_descarte(tmp_path):
    municipios = pl.DataFrame({"cod_municipio": ["1234567"]})
    with zipfile.ZipFile(tmp_path / "a_2013.zip", "w") as zf:
        zf.writestr("f.csv", "Exercício: 2013\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\nI;5300108;DF;1;Despesas Empenhadas;04 - A;;1\nI;9999999;XX;1;Despesas Empenhadas;04 - A;;1\n".encode("latin-1"))
        
    manifesto = {}
    for ano in siconfi.ANOS:
        if ano == 2013:
            manifesto[f"contas_anuais_{ano}"] = {"arquivo": "a_2013.zip"}
        else:
            caminho_zip = tmp_path / f"a_{ano}.zip"
            with zipfile.ZipFile(caminho_zip, "w") as zf:
                zf.writestr("f.csv", f"Exercício: {ano}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            manifesto[f"contas_anuais_{ano}"] = {"arquivo": caminho_zip.name}
    nucleo._gravar_manifesto(tmp_path, manifesto)
    
    relatorio = []
    df = siconfi.harmonizar(tmp_path, municipios, relatorio=relatorio)
    assert any(r["cod_municipio"] == "5300108" and r["tipo"] == "distrito_federal" for r in relatorio)
    assert any(r["cod_municipio"] == "9999999" and r["tipo"] == "fora_da_dtb" for r in relatorio)
    
def test_finbra_esquema_igual():
    amostra = Path(__file__).parent / "dados" / "finbra_dsubfuncao_2006_amostra.json"
    with open(amostra, encoding="utf-8") as f:
        tabela_2006 = json.load(f)

    muns_reais = pl.DataFrame({
        "cod_municipio_6": ["355030"],
        "cod_municipio": ["3550308"],
    })
    
    df, _ = processar_tabela(tabela_2006, 2006, muns_reais)
    
    assert df.schema == ESQUEMA


def test_requisicoes_api():
    reqs_2013 = siconfi.requisicoes_api(2013, ["1200013"])
    assert len(reqs_2013) == 1
    assert reqs_2013[0].chave == "2013/1200013"
    assert reqs_2013[0].url.endswith("no_anexo=Anexo+I-E")

    reqs_2014 = siconfi.requisicoes_api(2014, ["1200013"])
    assert len(reqs_2014) == 1
    assert reqs_2014[0].chave == "2014/1200013"
    assert reqs_2014[0].url.endswith("no_anexo=DCA-Anexo+I-E")

    reqs_ordem = siconfi.requisicoes_api(2015, ["3550308", "1100015", "1200013"])
    assert [r.chave for r in reqs_ordem] == ["2015/1100015", "2015/1200013", "2015/3550308"]


def test_validar_resposta_api():
    siconfi.validar_resposta_api(b'{"items": [], "hasMore": false}')

    with pytest.raises(nucleo.RespostaInvalida):
        siconfi.validar_resposta_api(b"texto nao json")

    with pytest.raises(nucleo.RespostaInvalida):
        siconfi.validar_resposta_api(b'{"hasMore": false}')

    with pytest.raises(nucleo.RespostaInvalida):
        siconfi.validar_resposta_api(b'{"items": [], "hasMore": true}')


def test_baixar_api_pula_ano_registrado_e_exclui_df(tmp_path, monkeypatch):
    chamadas = []

    def fake_baixar_em_ritmo(requisicoes, destino, **kwargs):
        chamadas.append(list(requisicoes))
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(gzip.compress(b'{"chave": "x"}\n', mtime=0))
        return {"linhas": len(requisicoes), "pausas_429": 0}

    monkeypatch.setattr(nucleo, "baixar_em_ritmo", fake_baixar_em_ritmo)

    municipios = ["1200013", "5300108", "1100015"]
    anos = [2013, 2014]

    siconfi.baixar_api(tmp_path, municipios, anos=anos)
    assert len(chamadas) == 2
    for lote in chamadas:
        chaves = [r.chave for r in lote]
        assert not any("5300108" in c for c in chaves)

    manifesto = nucleo.ler_manifesto(tmp_path)
    assert "dca_2013" in manifesto
    assert "dca_2014" in manifesto
    assert manifesto["dca_2013"]["metodo"] == "GET"
    assert manifesto["dca_2014"]["metodo"] == "GET"

    siconfi.baixar_api(tmp_path, municipios, anos=anos)
    assert len(chamadas) == 2


def test_harmonizar_api_igual_ao_portal(tmp_path):
    pasta_portal = tmp_path / "portal"
    pasta_api = tmp_path / "api"
    pasta_portal.mkdir()
    pasta_api.mkdir()

    amostras = [
        (2013, Path(__file__).parent / "dados" / "siconfi_contas_anuais_2013_amostra.csv"),
        (2022, Path(__file__).parent / "dados" / "siconfi_contas_anuais_2022_amostra.csv"),
    ]
    municipios = pl.DataFrame({"cod_municipio": ["3550308", "1600279", "4126652", "2905206"]})

    manifesto_portal = {}
    manifesto_api = {}

    for ano, p in amostras:
        caminho_zip = pasta_portal / f"a_{ano}.zip"
        with zipfile.ZipFile(caminho_zip, "w") as zf:
            zf.write(p, "f.csv")
        manifesto_portal[f"contas_anuais_{ano}"] = {"arquivo": caminho_zip.name}

        df_ano = siconfi.ler_arquivo(pasta_portal, caminho_zip.name)
        linhas_jsonl = []
        for cod_mun, grupo in df_ano.group_by("cod_municipio"):
            cod_str = cod_mun[0] if isinstance(cod_mun, tuple) else cod_mun
            items = []
            for row in grupo.iter_rows(named=True):
                items.append({
                    "cod_ibge": int(cod_str),
                    "coluna": row["coluna"],
                    "conta": row["conta"],
                    "valor": row["valor"],
                })
            corpo = json.dumps({"items": items, "hasMore": False}, ensure_ascii=False)
            linhas_jsonl.append(json.dumps({
                "chave": f"{ano}/{cod_str}",
                "url": f"http://api/{ano}/{cod_str}",
                "http": 200,
                "corpo": corpo,
            }, ensure_ascii=False))

        arquivo_api_ano = siconfi.arquivo_api(ano)
        texto_gz = gzip.compress("\n".join(linhas_jsonl).encode("utf-8") + (b"\n" if linhas_jsonl else b""), mtime=0)
        (pasta_api / arquivo_api_ano).write_bytes(texto_gz)
        manifesto_api[f"dca_{ano}"] = {"arquivo": arquivo_api_ano}

    for ano in siconfi.ANOS:
        if f"contas_anuais_{ano}" not in manifesto_portal:
            caminho_zip = pasta_portal / f"a_{ano}.zip"
            with zipfile.ZipFile(caminho_zip, "w") as zf:
                zf.writestr("f.csv", f"Exercício: {ano}\nEscopo: Municípios\nTabela: Despesas por Função (Anexo I-E)\nInstituição;Cod.IBGE;UF;População;Coluna;Conta;Identificador da Conta;Valor\n".encode("latin-1"))
            manifesto_portal[f"contas_anuais_{ano}"] = {"arquivo": caminho_zip.name}

        if f"dca_{ano}" not in manifesto_api:
            arquivo_api_ano = siconfi.arquivo_api(ano)
            (pasta_api / arquivo_api_ano).write_bytes(gzip.compress(b"", mtime=0))
            manifesto_api[f"dca_{ano}"] = {"arquivo": arquivo_api_ano}

    nucleo._gravar_manifesto(pasta_portal, manifesto_portal)
    nucleo._gravar_manifesto(pasta_api, manifesto_api)

    df_portal = siconfi.harmonizar(pasta_portal, municipios)
    df_api = siconfi.harmonizar(pasta_api, municipios, origem="api")

    assert df_api.equals(df_portal)

    with pytest.raises(ValueError, match="Origem desconhecida"):
        siconfi.harmonizar(pasta_api, municipios, origem="outra")


