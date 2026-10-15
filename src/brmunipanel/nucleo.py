"""Common collection core: requests with retries, raw data saved as received, and provenance manifest per source.

Each source has its own folder inside the raw data folder, with a `manifest.json` that records,
for each file, the request that generated it (URL, method, body), the date, size, and response hash.
A file already recorded in the manifest is never downloaded again or overwritten, making collection resumable.
Before a recorded file is reused, the request is compared with the record and the file with the recorded size and
hash, and any difference raises an error.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

import requests
import urllib3.util.connection

MANIFESTO = "manifest.json"
AGENTE = "Mozilla/5.0 (compatible; brmunipanel/0.1)"


class RespostaInvalida(Exception):
    """The response arrived with HTTP 200, but the content is not what was expected (error page, empty table, etc.)."""


@dataclass(frozen=True)
class Requisicao:
    """A request and the raw file it generates, relative to the source folder."""

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
    """Returns the bytes of the original response, decompressing when the file was saved in gzip."""
    conteudo = (Path(pasta) / arquivo).read_bytes()
    return gzip.decompress(conteudo) if arquivo.endswith(".gz") else conteudo


def _requisitar(req: Requisicao, sessao: requests.Session, timeout: float) -> requests.Response:
    cabecalhos = {"User-Agent": AGENTE, **req.cabecalhos}
    if req.metodo == "POST":
        return sessao.post(req.url, data=req.corpo, headers=cabecalhos, timeout=timeout)
    return sessao.get(req.url, headers=cabecalhos, timeout=timeout)


def _conferir_registro(pasta: Path, req: Requisicao, registro: dict) -> None:
    """Raises when the manifest record no longer describes `req` or the file on disk no longer matches it."""
    esperado = {"url": req.url, "metodo": req.metodo, "arquivo": req.arquivo, "corpo": req.corpo}
    diferentes = [campo for campo, valor in esperado.items() if registro.get(campo) != valor]
    if diferentes:
        raise RuntimeError(f"{req.chave}: a requisição difere do registro no manifesto ({', '.join(diferentes)})")
    gravado = (pasta / req.arquivo).read_bytes()
    try:
        conteudo = gzip.decompress(gravado) if req.compactar else gravado
    except (OSError, EOFError) as erro:
        raise RuntimeError(f"{req.chave}: o arquivo {req.arquivo} não pôde ser descompactado ({erro})") from erro
    if len(conteudo) != registro.get("bytes") or hashlib.sha256(conteudo).hexdigest() != registro.get("sha256"):
        raise RuntimeError(f"{req.chave}: o arquivo {req.arquivo} mudou depois de registrado no manifesto")


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
    """Downloads `req` into `pasta` and records it in the manifest. Returns the record and whether a download occurred.

    Network errors, HTTP 429 and 5xx, and responses rejected by `validar` are retried, with waiting time
    doubled on each attempt. Other HTTP errors and a failed certificate verification are raised immediately,
    because retrying does not resolve them.

    A key already in the manifest whose file exists is reused only when the record matches the request and the file
    still has the recorded size and hash; otherwise an error is raised and nothing is downloaded or overwritten.
    """
    pasta = Path(pasta)
    manifesto = ler_manifesto(pasta)
    destino = pasta / req.arquivo
    if req.chave in manifesto and destino.exists():
        _conferir_registro(pasta, req, manifesto[req.chave])
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
        except requests.exceptions.SSLError as erro:
            if "CERTIFICATE_VERIFY_FAILED" in str(erro):
                raise RuntimeError(f"{req.chave}: falha na verificação do certificado do servidor ({erro})") from erro
            ultimo_erro = erro
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
    """Records in the manifest a file that is already in `pasta`, downloaded manually. Returns the record and whether it is new."""
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


@contextmanager
def somente_ipv4():
    """Resolves host names to IPv4 addresses only while the block runs, then restores the previous behaviour."""
    original = urllib3.util.connection.allowed_gai_family
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
    try:
        yield
    finally:
        urllib3.util.connection.allowed_gai_family = original


def baixar_em_ritmo(
    requisicoes: Sequence[Requisicao],
    destino: Path,
    *,
    ritmo: float = 4.0,
    simultaneas: int = 8,
    sessao: requests.Session | None = None,
    validar: Callable[[bytes], None] | None = None,
    tentativas: int = 5,
    espera: float = 10.0,
    pausa_429: float = 30.0,
    timeout: float = 120.0,
    avisar: Callable[[str], None] | None = print,
) -> dict:
    """Downloads many small GET responses at a fixed rate into one gzip JSON Lines file.

    A request starts every 1/`ritmo` seconds, without waiting for the previous one, with at most `simultaneas`
    in flight. Each line holds the request key, URL, HTTP status and the response body as received. Lines are
    appended to `<destino>.em_andamento` as responses arrive, so an interrupted run resumes from the keys already there.
    Network errors and HTTP 5xx are retried with doubled waits; HTTP 429 pauses new requests for `pausa_429`
    seconds and retries; a failed certificate verification is raised at once. When every key is present, the lines
    are sorted by key, compressed into `destino` and the partial file is removed.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".em_andamento")
    feitas = set()
    if parcial.exists():
        for linha in parcial.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                feitas.add(json.loads(linha)["chave"])
    pendentes = [r for r in requisicoes if r.chave not in feitas]
    sessao = sessao or requests.Session()
    trava = threading.Lock()
    vagas = threading.Semaphore(simultaneas)
    estado = {"pausa_ate": 0.0, "falhas": {}, "pausas_429": 0}

    def esperar_pausa() -> None:
        while True:
            restante = estado["pausa_ate"] - time.monotonic()
            if restante <= 0:
                return
            time.sleep(restante)

    def executar(req: Requisicao) -> None:
        try:
            ultimo = None
            for tentativa in range(tentativas):
                if tentativa:
                    time.sleep(espera * 2 ** (tentativa - 1))
                esperar_pausa()
                try:
                    resposta = sessao.get(req.url, headers={"User-Agent": AGENTE, **req.cabecalhos}, timeout=timeout)
                    if resposta.status_code == 429:
                        with trava:
                            estado["pausa_ate"] = max(estado["pausa_ate"], time.monotonic() + pausa_429)
                            estado["pausas_429"] += 1
                        ultimo = RespostaInvalida("HTTP 429")
                        continue
                    if resposta.status_code >= 500:
                        raise RespostaInvalida(f"HTTP {resposta.status_code}")
                    resposta.raise_for_status()
                    conteudo = resposta.content
                    if validar is not None:
                        validar(conteudo)
                    linha = json.dumps({"chave": req.chave, "url": req.url, "http": resposta.status_code, "corpo": conteudo.decode("utf-8")}, ensure_ascii=False)
                    with trava:
                        with open(parcial, "a", encoding="utf-8") as arquivo:
                            arquivo.write(linha + "\n")
                    return
                except requests.exceptions.SSLError as erro:
                    if "CERTIFICATE_VERIFY_FAILED" in str(erro):
                        raise RuntimeError(f"{req.chave}: falha na verificação do certificado do servidor ({erro})") from erro
                    ultimo = erro
                except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError, RespostaInvalida) as erro:
                    ultimo = erro
            with trava:
                estado["falhas"][req.chave] = str(ultimo)
        finally:
            vagas.release()

    inicio = time.monotonic()
    with ThreadPoolExecutor(max_workers=simultaneas) as pool:
        futuros = []
        for n, req in enumerate(pendentes):
            alvo = inicio + n / ritmo
            agora = time.monotonic()
            if alvo > agora:
                time.sleep(alvo - agora)
            esperar_pausa()
            vagas.acquire()
            futuros.append(pool.submit(executar, req))
        for futuro in futuros:
            futuro.result()

    if avisar is not None:
        avisar(f"{destino.name}: {len(pendentes)} requisições em {time.monotonic() - inicio:.1f}s, {len(feitas)} já estavam no arquivo parcial, "
               f"{len(estado['falhas'])} falhas, {estado['pausas_429']} respostas 429")
    if estado["falhas"]:
        exemplo = next(iter(estado["falhas"].items()))
        raise RuntimeError(f"{destino.name}: {len(estado['falhas'])} requisições falharam; rode de novo para continuar. Exemplo: {exemplo}")
    linhas = [json.loads(linha) for linha in parcial.read_text(encoding="utf-8").splitlines() if linha.strip()]
    linhas.sort(key=lambda d: d["chave"])
    texto = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in linhas).encode("utf-8")
    _gravar_atomico(destino, gzip.compress(texto, mtime=0))
    parcial.unlink()
    return {"linhas": len(linhas), "pausas_429": estado["pausas_429"]}


def registrar_arquivo(pasta: Path, chave: str, arquivo: str, *, url: str, metodo: str, parametros: dict[str, str]) -> dict:
    """Records in the manifest a file that the library itself wrote to `pasta`."""
    pasta = Path(pasta)
    conteudo = (pasta / arquivo).read_bytes()
    registro = {
        "url": url,
        "metodo": metodo,
        "arquivo": arquivo,
        "bytes": len(conteudo),
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parametros": parametros,
    }
    manifesto = ler_manifesto(pasta)
    manifesto[chave] = registro
    _gravar_manifesto(pasta, manifesto)
    return registro


def baixar_lote(
    requisicoes: Iterable[Requisicao],
    pasta: Path,
    *,
    intervalo: float = 0.0,
    avisar: Callable[[str], None] | None = print,
    **opcoes,
) -> list[dict]:
    """Downloads requests in sequence, in the same HTTP session, skipping those already in the manifest."""
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
