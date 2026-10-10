"""Cliente do TabNet (DATASUS) para extração de tabulações de saúde municipais via POST.

Endpoint: http://tabnet.datasus.gov.br/cgi/tabcgi.exe?<definicao>.def
As consultas geram arquivos em formato PRN (CSV separado por ponto e vírgula dentro de tags <PRE>).
"""

from __future__ import annotations

import csv
import html
import io
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from .. import nucleo
from ..nucleo import Requisicao, RespostaInvalida


@dataclass(frozen=True)
class Tabulacao:
    """Configuração de uma tabulação do TabNet."""

    nome: str
    definicao: str
    coluna: str
    incrementos: tuple[str, ...]
    prefixo: str
    periodos: tuple[str, ...]
    filtros: dict[str, str] = field(default_factory=dict)


TABULACOES: tuple[Tabulacao, ...] = (
    Tabulacao(
        nome="cnes_leitos_internacao",
        definicao="cnes/cnv/leiintbr",
        coluna="--Não-Ativa--",
        incrementos=("Quantidade_existente", "Quantidade_SUS"),
        prefixo="ltbr",
        periodos=tuple(f"{ano:04d}07" for ano in range(2006, 2024)),
    ),
    Tabulacao(
        nome="cnes_leitos_complementares",
        definicao="cnes/cnv/leiutibr",
        coluna="Leitos_complementares",
        incrementos=("Quantidade_existente",),
        prefixo="lubr",
        periodos=tuple(f"{ano:04d}07" for ano in range(2006, 2024)),
    ),
    Tabulacao(
        nome="cnes_estabelecimentos",
        definicao="cnes/cnv/estabbr",
        coluna="Tipo_de_Estabelecimento",
        incrementos=("Quantidade",),
        prefixo="stbr",
        periodos=tuple(f"{ano:04d}07" for ano in range(2006, 2024)),
    ),
    Tabulacao(
        nome="cnes_equipamentos_grupo",
        definicao="cnes/cnv/equipobr",
        coluna="Grupo_de_Equipamentos",
        incrementos=("Equipamentos_Existentes",),
        prefixo="eqbr",
        periodos=tuple(f"{ano:04d}07" for ano in range(2006, 2024)),
    ),
    Tabulacao(
        nome="cnes_medicos_cbo1994",
        definicao="cnes/cnv/profidbr",
        coluna="Médicos",
        incrementos=("Quantidade",),
        prefixo="pfbr",
        periodos=("200607", "200707"),
    ),
    Tabulacao(
        nome="cnes_medicos_cbo2002",
        definicao="cnes/cnv/prid02br",
        coluna="Médicos",
        incrementos=("Quantidade",),
        prefixo="pfbr",
        periodos=("200708",) + tuple(f"{ano:04d}07" for ano in range(2008, 2024)),
    ),
    Tabulacao(
        nome="sim_obitos_agressao",
        definicao="sim/cnv/obt10br",
        coluna="--Não-Ativa--",
        incrementos=("Óbitos_p/Residênc",),
        prefixo="obtbr",
        periodos=tuple(str(ano) for ano in range(2006, 2024)),
        filtros={"SGrupo_CID-10": "246"},
    ),
    Tabulacao(
        nome="sim_obitos_infantis",
        definicao="sim/cnv/inf10br",
        coluna="--Não-Ativa--",
        incrementos=("Óbitos_p/Residênc",),
        prefixo="infbr",
        periodos=tuple(str(ano) for ano in range(2006, 2024)),
    ),
    Tabulacao(
        nome="sinasc_nascidos_vivos",
        definicao="sinasc/cnv/nvbr",
        coluna="--Não-Ativa--",
        incrementos=("Nascim_p/resid.mãe",),
        prefixo="nvbr",
        periodos=tuple(str(ano) for ano in range(2006, 2024)),
    ),
)


def _codificar(texto: str) -> str:
    """Codifica parâmetro URL em Latin-1 para compatibilidade com o servidor TabNet."""
    return urllib.parse.quote(str(texto), safe="", encoding="latin-1")


def nome_dbf(tabulacao: Tabulacao, periodo: str | int) -> str:
    """Devolve o nome do arquivo .dbf no servidor para a tabulação e período."""
    p = str(periodo).strip()
    if len(p) == 4 and tabulacao.definicao.startswith("cnes/"):
        p = f"{p}07"
    if len(p) == 6:
        # Formato AAAAMM (ex: 200607 -> 0607, 200708 -> 0708)
        return f"{tabulacao.prefixo}{p[2:4]}{p[4:6]}.dbf"
    # Formato AAAA (ex: 2006 -> 06, 2023 -> 23)
    return f"{tabulacao.prefixo}{p[2:4]}.dbf"


def montar_corpo(tabulacao: Tabulacao, periodo: str | int) -> str:
    """Monta a string de formulário POST codificada em Latin-1 na ordem requerida pelo TabNet."""
    partes = [
        f"{_codificar('Linha')}={_codificar('Município')}",
        f"{_codificar('Coluna')}={_codificar(tabulacao.coluna)}",
    ]
    for inc in tabulacao.incrementos:
        partes.append(f"{_codificar('Incremento')}={_codificar(inc)}")

    partes.append(f"{_codificar('Arquivos')}={_codificar(nome_dbf(tabulacao, periodo))}")

    for chave, valor in tabulacao.filtros.items():
        partes.append(f"{_codificar(chave)}={_codificar(valor)}")

    partes.append(f"{_codificar('formato')}={_codificar('prn')}")
    partes.append(f"{_codificar('mostre')}={_codificar('Mostra')}")

    return "&".join(partes)


def requisicao(tabulacao: Tabulacao, periodo: str | int) -> Requisicao:
    """Cria o objeto Requisicao para a tabulação e período."""
    periodo_str = str(periodo).strip()
    chave = f"{tabulacao.nome}/{periodo_str}"
    url = f"http://tabnet.datasus.gov.br/cgi/tabcgi.exe?{tabulacao.definicao}.def"
    arquivo = f"{tabulacao.nome}/{tabulacao.nome}_{periodo_str}.html.gz"
    corpo = montar_corpo(tabulacao, periodo_str)
    cabecalhos = {"Content-Type": "application/x-www-form-urlencoded"}
    return Requisicao(
        chave=chave,
        url=url,
        arquivo=arquivo,
        metodo="POST",
        corpo=corpo,
        cabecalhos=cabecalhos,
        compactar=True,
    )


def extrair_tabela(conteudo: bytes) -> tuple[list[str], list[list[str]]]:
    """Extrai cabeçalho e linhas da tabela HTML gerada pelo TabNet dentro de <PRE>...</PRE>."""
    texto = conteudo.decode("latin-1", errors="replace")
    m = re.search(r"<pre[^>]*>([\s\S]*?)</pre>", texto, re.IGNORECASE)
    if not m:
        raise RespostaInvalida("Tag <PRE> não encontrada na resposta do TabNet")

    bloco_pre = m.group(1).strip()
    leitor = csv.reader(io.StringIO(bloco_pre), delimiter=";")
    linhas_brutas = [row for row in leitor if any(c.strip() for c in row)]

    if not linhas_brutas:
        raise RespostaInvalida("Bloco <PRE> vazio na resposta do TabNet")

    cabecalho = [html.unescape(c.strip().strip('"')) for c in linhas_brutas[0]]
    linhas = [[html.unescape(c.strip().strip('"')) for c in row] for row in linhas_brutas[1:]]

    # Filtrar eventuais linhas de rodapé com número divergente de colunas após 'Total'
    linhas_validas = []
    atingiu_total = False
    for row in linhas:
        if atingiu_total:
            break
        if len(row) != len(cabecalho):
            rotulo = row[0].strip() if row else ""
            raise RespostaInvalida(
                f"Linha malformada antes do Total: rótulo '{rotulo}' com {len(row)} colunas (esperado {len(cabecalho)})"
            )
        linhas_validas.append(row)
        if row and row[0].strip().lower() == "total":
            atingiu_total = True

    return cabecalho, linhas_validas


def validar(conteudo: bytes, *, min_linhas: int = 1000) -> None:
    """Valida se a resposta do TabNet contém dados tabulares válidos com total e colunas uniformes."""
    texto = conteudo.decode("latin-1", errors="replace")
    if "Nenhum registro selecionado" in texto:
        raise RespostaInvalida("TabNet retornou 'Nenhum registro selecionado'")

    cabecalho, linhas = extrair_tabela(conteudo)
    if not cabecalho:
        raise RespostaInvalida("Cabeçalho vazio na tabela do TabNet")

    linhas_municipio = [r for r in linhas if r and re.match(r"^\d{6}", r[0].strip())]
    if len(linhas_municipio) < min_linhas:
        raise RespostaInvalida(
            f"Tabela do TabNet possui poucas linhas de município ({len(linhas_municipio)} < {min_linhas})"
        )

    linha_total = [r for r in linhas if r and r[0].strip().lower() == "total"]
    if not linha_total:
        raise RespostaInvalida("Linha 'Total' não encontrada na tabela do TabNet")

    for i, row in enumerate(linhas):
        if len(row) != len(cabecalho):
            raise RespostaInvalida(
                f"Linha {i} com número de colunas ({len(row)}) diferente do cabeçalho ({len(cabecalho)})"
            )


def baixar(pasta: Path, **opcoes) -> list[dict]:
    """Baixa todas as tabulações e períodos cadastrados para a pasta de dados brutos."""
    pasta = Path(pasta)
    requisicoes = [requisicao(tab, p) for tab in TABULACOES for p in tab.periodos]
    intervalo = opcoes.pop("intervalo", 1.0)
    return nucleo.baixar_lote(requisicoes, pasta, validar=validar, intervalo=intervalo, **opcoes)
