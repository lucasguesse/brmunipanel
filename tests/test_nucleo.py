"""Testes do núcleo comum de download, manifesto e tentativas (bra_municipalities_panel.nucleo)."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Sequence

import pytest
import requests

from bra_municipalities_panel.nucleo import (
    Requisicao,
    RespostaInvalida,
    baixar,
    baixar_lote,
    ler_bruto,
    ler_manifesto,
    registrar_manual,
)


class RespostaFalsa:
    def __init__(self, content: bytes = b"conteudo de teste", status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 500:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)
        if self.status_code >= 500:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class SessaoFalsa:
    def __init__(self, respostas: Sequence[RespostaFalsa | Exception] | None = None) -> None:
        self._respostas = list(respostas) if respostas is not None else [RespostaFalsa()]
        self.chamadas: list[dict] = []

    def get(self, url: str, headers: dict | None = None, timeout: float = 300.0) -> RespostaFalsa:
        self.chamadas.append({"metodo": "GET", "url": url, "headers": headers, "timeout": timeout})
        return self._proxima()

    def post(self, url: str, data: str | None = None, headers: dict | None = None, timeout: float = 300.0) -> RespostaFalsa:
        self.chamadas.append({"metodo": "POST", "url": url, "data": data, "headers": headers, "timeout": timeout})
        return self._proxima()

    def _proxima(self) -> RespostaFalsa:
        if not self._respostas:
            raise IndexError("Nenhuma resposta restante na sessão falsa")
        resp = self._respostas.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_baixar_grava_gzip_e_ler_bruto_descompacta(tmp_path: Path) -> None:
    """1. baixar grava o arquivo em gzip, e ler_bruto devolve exatamente os bytes da resposta."""
    dados = b"resposta original em texto ou json"
    sessao = SessaoFalsa([RespostaFalsa(dados, 200)])
    req = Requisicao(chave="teste/1", url="http://exemplo.org/1", arquivo="teste/1.json.gz", compactar=True)

    registro, baixou = baixar(req, tmp_path, sessao=sessao, espera=0)

    assert baixou is True
    destino = tmp_path / req.arquivo
    assert destino.exists()
    assert gzip.decompress(destino.read_bytes()) == dados
    assert ler_bruto(tmp_path, req.arquivo) == dados


def test_manifesto_registra_campos_esperados_get_e_post(tmp_path: Path) -> None:
    """2. O manifesto registra url, metodo, arquivo, bytes, sha256 (da resposta, não do gzip) e baixado_em; em POST, também corpo."""
    dados_get = b"resposta get"
    sessao_get = SessaoFalsa([RespostaFalsa(dados_get, 200)])
    req_get = Requisicao(chave="fonte/get", url="http://exemplo.org/get", arquivo="fonte/get.json.gz")
    registro_get, _ = baixar(req_get, tmp_path, sessao=sessao_get, espera=0)

    assert registro_get["url"] == "http://exemplo.org/get"
    assert registro_get["metodo"] == "GET"
    assert registro_get["arquivo"] == "fonte/get.json.gz"
    assert registro_get["bytes"] == len(dados_get)
    assert registro_get["sha256"] == hashlib.sha256(dados_get).hexdigest()
    assert "baixado_em" in registro_get
    assert "corpo" not in registro_get

    manifesto = ler_manifesto(tmp_path)
    assert manifesto["fonte/get"] == registro_get

    # POST com corpo
    dados_post = b"resposta post"
    sessao_post = SessaoFalsa([RespostaFalsa(dados_post, 200)])
    req_post = Requisicao(
        chave="fonte/post",
        url="http://exemplo.org/post",
        arquivo="fonte/post.json.gz",
        metodo="POST",
        corpo="param1=val1",
    )
    registro_post, _ = baixar(req_post, tmp_path, sessao=sessao_post, espera=0)

    assert registro_post["url"] == "http://exemplo.org/post"
    assert registro_post["metodo"] == "POST"
    assert registro_post["arquivo"] == "fonte/post.json.gz"
    assert registro_post["corpo"] == "param1=val1"
    assert registro_post["bytes"] == len(dados_post)
    assert registro_post["sha256"] == hashlib.sha256(dados_post).hexdigest()
    assert "baixado_em" in registro_post

    manifesto_atual = ler_manifesto(tmp_path)
    assert manifesto_atual["fonte/post"] == registro_post


def test_segunda_chamada_retorna_registro_sem_nova_requisicao(tmp_path: Path) -> None:
    """3. Segunda chamada com a mesma chave não faz requisição e devolve o mesmo registro (baixou falso)."""
    dados = b"resposta imutavel"
    sessao = SessaoFalsa([RespostaFalsa(dados, 200)])
    req = Requisicao(chave="chave/unica", url="http://exemplo.org/dados", arquivo="dados.json.gz")

    registro1, baixou1 = baixar(req, tmp_path, sessao=sessao, espera=0)
    assert baixou1 is True
    assert len(sessao.chamadas) == 1

    registro2, baixou2 = baixar(req, tmp_path, sessao=sessao, espera=0)
    assert baixou2 is False
    assert registro1 == registro2
    assert len(sessao.chamadas) == 1  # não chamou de novo


def test_novas_tentativas_http_500(tmp_path: Path) -> None:
    """4. HTTP 500 seguido de 200 resulta em sucesso, com 2 requisições; HTTP 500 em todas as tentativas levanta RuntimeError e não deixa arquivo nem registro."""
    # Caso de recuperação na 2ª tentativa
    sessao_recup = SessaoFalsa([RespostaFalsa(b"erro", 500), RespostaFalsa(b"ok final", 200)])
    req1 = Requisicao(chave="tentativas/recup", url="http://exemplo.org/recup", arquivo="recup.json.gz")
    registro, baixou = baixar(req1, tmp_path, sessao=sessao_recup, tentativas=3, espera=0)
    assert baixou is True
    assert registro["bytes"] == len(b"ok final")
    assert len(sessao_recup.chamadas) == 2

    # Caso de falha persistente
    sessao_falha = SessaoFalsa([RespostaFalsa(b"erro", 500), RespostaFalsa(b"erro", 502), RespostaFalsa(b"erro", 503)])
    req2 = Requisicao(chave="tentativas/falha", url="http://exemplo.org/falha", arquivo="falha.json.gz")
    with pytest.raises(RuntimeError, match="falhou depois de 3 tentativas"):
        baixar(req2, tmp_path, sessao=sessao_falha, tentativas=3, espera=0)

    assert not (tmp_path / req2.arquivo).exists()
    assert req2.chave not in ler_manifesto(tmp_path)


def test_validar_resposta_invalida_provoca_nova_tentativa(tmp_path: Path) -> None:
    """5. validar que levanta RespostaInvalida provoca nova tentativa, e nada é gravado enquanto a resposta for recusada."""
    chamadas_validar = 0

    def validador(conteudo: bytes) -> None:
        nonlocal chamadas_validar
        chamadas_validar += 1
        if conteudo == b"incompleto":
            raise RespostaInvalida("conteúdo incompleto")

    sessao = SessaoFalsa([RespostaFalsa(b"incompleto", 200), RespostaFalsa(b"completo", 200)])
    req = Requisicao(chave="validacao/teste", url="http://exemplo.org/val", arquivo="val.json.gz")

    registro, baixou = baixar(req, tmp_path, sessao=sessao, validar=validador, tentativas=3, espera=0)
    assert baixou is True
    assert chamadas_validar == 2
    assert len(sessao.chamadas) == 2
    assert ler_bruto(tmp_path, req.arquivo) == b"completo"

    # Se a validação sempre falhar:
    def validador_sempre_falha(c: bytes) -> None:
        raise RespostaInvalida("sempre recusa")

    sessao_falha = SessaoFalsa([RespostaFalsa(b"lixo", 200), RespostaFalsa(b"lixo", 200)])
    req_falha = Requisicao(chave="validacao/falha", url="http://exemplo.org/val_falha", arquivo="val_falha.json.gz")
    with pytest.raises(RuntimeError, match="falhou depois de 2 tentativas"):
        baixar(req_falha, tmp_path, sessao=sessao_falha, validar=validador_sempre_falha, tentativas=2, espera=0)

    assert not (tmp_path / req_falha.arquivo).exists()
    assert req_falha.chave not in ler_manifesto(tmp_path)


def test_http_404_sobe_imediatamente_na_primeira_tentativa(tmp_path: Path) -> None:
    """6. HTTP 404 sobe como requests.HTTPError na primeira tentativa."""
    sessao = SessaoFalsa([RespostaFalsa(b"nao encontrado", 404)])
    req = Requisicao(chave="erro/404", url="http://exemplo.org/404", arquivo="404.json.gz")

    with pytest.raises(requests.HTTPError) as exc_info:
        baixar(req, tmp_path, sessao=sessao, tentativas=5, espera=0)

    assert exc_info.value.response.status_code == 404
    assert len(sessao.chamadas) == 1
    assert not (tmp_path / req.arquivo).exists()
    assert req.chave not in ler_manifesto(tmp_path)


def test_compactar_false_grava_sem_gzip(tmp_path: Path) -> None:
    """7. compactar=False grava os bytes sem gzip."""
    dados_binarios = b"\x00\x01\x02\x03\xff"
    sessao = SessaoFalsa([RespostaFalsa(dados_binarios, 200)])
    req = Requisicao(chave="bin/raw", url="http://exemplo.org/bin", arquivo="arquivo.bin", compactar=False)

    registro, baixou = baixar(req, tmp_path, sessao=sessao, espera=0)
    assert baixou is True
    destino = tmp_path / req.arquivo
    assert destino.read_bytes() == dados_binarios
    assert ler_bruto(tmp_path, req.arquivo) == dados_binarios


def test_baixar_lote_mantem_registros_anteriores(tmp_path: Path) -> None:
    """8. baixar_lote mantém os registros anteriores do manifesto ao acrescentar um novo."""
    sessao1 = SessaoFalsa([RespostaFalsa(b"dado1", 200)])
    req1 = Requisicao(chave="lote/1", url="http://exemplo.org/1", arquivo="1.json.gz")
    baixar(req1, tmp_path, sessao=sessao1, espera=0)

    manifesto_antes = ler_manifesto(tmp_path)
    assert "lote/1" in manifesto_antes

    sessao2 = SessaoFalsa([RespostaFalsa(b"dado2", 200)])
    req2 = Requisicao(chave="lote/2", url="http://exemplo.org/2", arquivo="2.json.gz")
    baixar_lote([req2], tmp_path, sessao=sessao2, espera=0, avisar=None)

    manifesto_depois = ler_manifesto(tmp_path)
    assert "lote/1" in manifesto_depois
    assert "lote/2" in manifesto_depois
    assert manifesto_depois["lote/1"] == manifesto_antes["lote/1"]


def test_registrar_manual_arquivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        registrar_manual(tmp_path, "chave", "inexistente.zip", url="http", parametros={})


def test_registrar_manual_novo_arquivo(tmp_path: Path) -> None:
    arquivo = tmp_path / "manual.zip"
    arquivo.write_bytes(b"conteudo")
    registro, novo = registrar_manual(tmp_path, "chave1", "manual.zip", url="http://url", parametros={"a": "b"})
    assert novo is True
    assert registro["url"] == "http://url"
    assert registro["metodo"] == "MANUAL"
    assert registro["arquivo"] == "manual.zip"
    assert registro["bytes"] == 8
    assert registro["parametros"] == {"a": "b"}
    assert "baixado_em" in registro
    assert ler_manifesto(tmp_path)["chave1"] == registro


def test_registrar_manual_arquivo_existente_mesmo_hash(tmp_path: Path) -> None:
    arquivo = tmp_path / "manual2.zip"
    arquivo.write_bytes(b"conteudo2")
    registro1, novo1 = registrar_manual(tmp_path, "chave2", "manual2.zip", url="http", parametros={})
    assert novo1 is True
    
    registro2, novo2 = registrar_manual(tmp_path, "chave2", "manual2.zip", url="http", parametros={})
    assert novo2 is False
    assert registro1 == registro2


def test_registrar_manual_arquivo_existente_hash_diferente(tmp_path: Path) -> None:
    arquivo = tmp_path / "manual3.zip"
    arquivo.write_bytes(b"conteudo3")
    registrar_manual(tmp_path, "chave3", "manual3.zip", url="http", parametros={})
    
    arquivo.write_bytes(b"novo_conteudo3")
    with pytest.raises(RuntimeError, match="arquivo mudou depois de registrado"):
        registrar_manual(tmp_path, "chave3", "manual3.zip", url="http", parametros={})

