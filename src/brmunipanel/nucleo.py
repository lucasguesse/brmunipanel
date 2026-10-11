"""Núcleo comum da coleta: requisição com novas tentativas, bruto gravado como veio e manifesto de proveniência por fonte.

Cada fonte tem uma pasta própria dentro da pasta de dados brutos, com um `manifest.json` que registra,
para cada arquivo, a requisição que o gerou (URL, método, corpo), a data, o tamanho e o hash da resposta.
Um arquivo já registrado no manifesto nunca é baixado de novo nem sobrescrito, o que torna a coleta retomável.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import requests

MANIFESTO = "manifest.json"
AGENTE = "Mozilla/5.0 (compatible; brmunipanel/0.1)"


class RespostaInvalida(Exception):
    """A resposta chegou com HTTP 200, mas o conteúdo não é o esperado (página de erro, tabela vazia etc.)."""


@dataclass(frozen=True)
class Requisicao:
    """Uma requisição e o arquivo bruto que ela gera, relativo à pasta da fonte."""

    chave: str
    url: str
    arquivo: str
    metodo: str = "GET"
    corpo: str | None = None
    cabecalhos: dict[str, str] = field(default_factory=dict)
    compactar: bool = True


def ler_manifesto(pasta: Path) -> dict[str, dict]:
    caminho = Path(pasta) / MANIFESTO
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text(encoding="utf-8"))


def _gravar_atomico(caminho: Path, conteudo: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".parcial")
    temporario.write_bytes(conteudo)
    os.replace(temporario, caminho)


def _gravar_manifesto(pasta: Path, manifesto: dict[str, dict]) -> None:
    texto = json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True)
    _gravar_atomico(Path(pasta) / MANIFESTO, texto.encode("utf-8"))


def ler_bruto(pasta: Path, arquivo: str) -> bytes:
    """Devolve os bytes da resposta original, descompactando quando o arquivo foi gravado em gzip."""
    conteudo = (Path(pasta) / arquivo).read_bytes()
    return gzip.decompress(conteudo) if arquivo.endswith(".gz") else conteudo


def _requisitar(req: Requisicao, sessao: requests.Session, timeout: float) -> requests.Response:
    cabecalhos = {"User-Agent": AGENTE, **req.cabecalhos}
    if req.metodo == "POST":
        return sessao.post(req.url, data=req.corpo, headers=cabecalhos, timeout=timeout)
    return sessao.get(req.url, headers=cabecalhos, timeout=timeout)


def baixar(
    req: Requisicao,
    pasta: Path,
    *,
    sessao: requests.Session | None = None,
    validar: Callable[[bytes], None] | None = None,
    tentativas: int = 5,
    espera: float = 10.0,
    timeout: float = 300.0,
) -> tuple[dict, bool]:
    """Baixa `req` para dentro de `pasta` e registra no manifesto. Devolve o registro e se houve download.

    Erros de rede, HTTP 429 e 5xx e respostas recusadas por `validar` são tentados de novo, com espera
    dobrada a cada tentativa. Os demais erros HTTP sobem na hora, porque repetir não os resolve.
    """
    pasta = Path(pasta)
    manifesto = ler_manifesto(pasta)
    destino = pasta / req.arquivo
    if req.chave in manifesto and destino.exists():
        return manifesto[req.chave], False

    sessao = sessao or requests.Session()
    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        if tentativa:
            time.sleep(espera * 2 ** (tentativa - 1))
        try:
            resposta = _requisitar(req, sessao, timeout)
            if resposta.status_code == 429 or resposta.status_code >= 500:
                raise RespostaInvalida(f"HTTP {resposta.status_code}")
            resposta.raise_for_status()
            conteudo = resposta.content
            if validar is not None:
                validar(conteudo)
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError, RespostaInvalida) as erro:
            ultimo_erro = erro
    else:
        raise RuntimeError(f"{req.chave}: falhou depois de {tentativas} tentativas ({ultimo_erro})") from ultimo_erro

    gravado = gzip.compress(conteudo, mtime=0) if req.compactar else conteudo
    _gravar_atomico(destino, gravado)
    registro = {
        "url": req.url,
        "metodo": req.metodo,
        "arquivo": req.arquivo,
        "bytes": len(conteudo),
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if req.corpo is not None:
        registro["corpo"] = req.corpo
    manifesto = ler_manifesto(pasta)
    manifesto[req.chave] = registro
    _gravar_manifesto(pasta, manifesto)
    return registro, True


def registrar_manual(pasta: Path, chave: str, arquivo: str, *, url: str, parametros: dict[str, str]) -> tuple[dict, bool]:
    """Registra no manifesto um arquivo que já está em `pasta`, baixado à mão. Devolve o registro e se ele é novo."""
    pasta = Path(pasta)
    destino = pasta / arquivo
    if not destino.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {destino}")

    conteudo = destino.read_bytes()
    sha256 = hashlib.sha256(conteudo).hexdigest()

    manifesto = ler_manifesto(pasta)

    if chave in manifesto:
        if manifesto[chave].get("sha256") == sha256:
            return manifesto[chave], False
        raise RuntimeError(f"{chave}: arquivo mudou depois de registrado")

    mtime = destino.stat().st_mtime
    baixado_em = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")

    registro = {
        "url": url,
        "metodo": "MANUAL",
        "arquivo": arquivo,
        "bytes": len(conteudo),
        "sha256": sha256,
        "baixado_em": baixado_em,
        "parametros": parametros,
    }

    manifesto[chave] = registro
    _gravar_manifesto(pasta, manifesto)

    return registro, True


def baixar_lote(
    requisicoes: Iterable[Requisicao],
    pasta: Path,
    *,
    intervalo: float = 0.0,
    avisar: Callable[[str], None] | None = print,
    **opcoes,
) -> list[dict]:
    """Baixa as requisições em sequência, na mesma sessão HTTP, pulando as que já estão no manifesto."""
    sessao = opcoes.pop("sessao", None) or requests.Session()
    registros = []
    for req in requisicoes:
        inicio = time.monotonic()
        registro, baixou = baixar(req, pasta, sessao=sessao, **opcoes)
        registros.append(registro)
        if avisar is not None:
            situacao = f"baixado em {time.monotonic() - inicio:.1f}s" if baixou else "já estava no manifesto"
            avisar(f"{req.chave}: {registro['bytes']:,} bytes, {situacao}")
        if baixou and intervalo:
            time.sleep(intervalo)
    return registros
