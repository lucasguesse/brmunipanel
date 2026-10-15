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

INTERMEDIATE_CERTIFICATE = "rnp_icpedu_gr46_ov_tls_ca_2025.pem"


def read_intermediate_certificate() -> bytes:
    """Returns the PEM bytes of the intermediate certificate shipped with the package."""
    return (resources.files("brmunipanel.inep") / "certificates" / INTERMEDIATE_CERTIFICATE).read_bytes()


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@lru_cache(maxsize=1)
def certificate_authorities() -> Path:
    """Writes, once per process, a file with the default certificate authorities plus the intermediate certificate.

    `requests` takes the accepted authorities from a single file, so the two sources are joined in a
    temporary file, removed when the process ends.
    """
    default = Path(requests.certs.where()).read_bytes()
    descriptor, path = tempfile.mkstemp(prefix="brmunipanel_inep_", suffix=".pem")
    with os.fdopen(descriptor, "wb") as file:
        file.write(default.rstrip(b"\r\n") + b"\n" + read_intermediate_certificate())
    atexit.register(_remove, path)
    return Path(path)


def create_session() -> requests.Session:
    """Returns a session that verifies the INEP server against the default authorities plus the shipped certificate."""
    session = requests.Session()
    session.verify = str(certificate_authorities())
    return session
