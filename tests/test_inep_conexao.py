"""Tests for the INEP download server connection and custom certificate authority bundle."""

from __future__ import annotations

import hashlib
from pathlib import Path
import ssl

import requests
import requests.certs

from brmunipanel.inep.conexao import autoridades, criar_sessao, ler_certificado_intermediario


def test_certificado_intermediario_e_o_esperado() -> None:
    """Verifies that the shipped certificate contains one certificate block and matches the expected SHA-256 fingerprint."""
    conteudo = ler_certificado_intermediario()
    assert conteudo.count(b"BEGIN CERTIFICATE") == 1
    texto = conteudo.decode("ascii")
    der = ssl.PEM_cert_to_DER_cert(texto)
    esperado = "e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd"
    assert hashlib.sha256(der).hexdigest() == esperado


def test_autoridades_junta_as_padrao_e_o_intermediario() -> None:
    """Verifies that the temporary bundle combines default authorities with the intermediate certificate."""
    caminho = autoridades()
    assert caminho.exists()
    conteudo = caminho.read_bytes()
    intermediario = ler_certificado_intermediario()
    assert conteudo.endswith(intermediario)

    padrao_bytes = Path(requests.certs.where()).read_bytes()
    assert conteudo.count(b"BEGIN CERTIFICATE") == padrao_bytes.count(b"BEGIN CERTIFICATE") + 1

    caminho2 = autoridades()
    assert caminho2 == caminho


def test_criar_sessao_usa_o_arquivo_de_autoridades() -> None:
    """Verifies that criar_sessao returns a requests.Session configured with the bundled authorities file."""
    sessao = criar_sessao()
    assert isinstance(sessao, requests.Session)
    assert sessao.verify == str(autoridades())
