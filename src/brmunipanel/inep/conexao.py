"""Connection to the INEP download server.

The server at download.inep.gov.br sends its own certificate without the intermediate certificate that
signed it, so the default verification of `requests` fails. This module reads the intermediate certificate
shipped with the package and builds a session that accepts it in addition to the default certificate
authorities. Certificate verification stays on.
"""

from __future__ import annotations

import atexit
import os
import tempfile
from functools import lru_cache
from importlib import resources
from pathlib import Path

import requests
import requests.certs

CERTIFICADO_INTERMEDIARIO = "rnp_icpedu_gr46_ov_tls_ca_2025.pem"


def ler_certificado_intermediario() -> bytes:
    """Returns the PEM bytes of the intermediate certificate shipped with the package."""
    return (resources.files("brmunipanel.inep") / "certificados" / CERTIFICADO_INTERMEDIARIO).read_bytes()


def _remover(caminho: str) -> None:
    try:
        os.remove(caminho)
    except OSError:
        pass


@lru_cache(maxsize=1)
def autoridades() -> Path:
    """Writes, once per process, a file with the default certificate authorities plus the intermediate certificate.

    `requests` takes the accepted authorities from a single file, so the two sources are joined in a
    temporary file, removed when the process ends.
    """
    padrao = Path(requests.certs.where()).read_bytes()
    descritor, caminho = tempfile.mkstemp(prefix="brmunipanel_inep_", suffix=".pem")
    with os.fdopen(descritor, "wb") as arquivo:
        arquivo.write(padrao.rstrip(b"\r\n") + b"\n" + ler_certificado_intermediario())
    atexit.register(_remover, caminho)
    return Path(caminho)


def criar_sessao() -> requests.Session:
    """Returns a session that verifies the INEP server against the default authorities plus the shipped certificate."""
    sessao = requests.Session()
    sessao.verify = str(autoridades())
    return sessao
