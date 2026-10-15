"""Tests for the INEP download server connection and custom certificate authority bundle."""

from __future__ import annotations

import hashlib
from pathlib import Path
import ssl

import requests
import requests.certs

from brmunipanel.inep.connection import certificate_authorities, create_session, read_intermediate_certificate


def test_intermediate_certificate_is_the_expected_one() -> None:
    """Verifies that the shipped certificate contains one certificate block and matches the expected SHA-256 fingerprint."""
    content = read_intermediate_certificate()
    assert content.count(b"BEGIN CERTIFICATE") == 1
    text = content.decode("ascii")
    der = ssl.PEM_cert_to_DER_cert(text)
    expected = "e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd"
    assert hashlib.sha256(der).hexdigest() == expected


def test_authorities_join_the_default_and_the_intermediate() -> None:
    """Verifies that the temporary bundle combines default authorities with the intermediate certificate."""
    path = certificate_authorities()
    assert path.exists()
    content = path.read_bytes()
    intermediate = read_intermediate_certificate()
    assert content.endswith(intermediate)

    default_bytes = Path(requests.certs.where()).read_bytes()
    assert content.count(b"BEGIN CERTIFICATE") == default_bytes.count(b"BEGIN CERTIFICATE") + 1

    path2 = certificate_authorities()
    assert path2 == path


def test_create_session_uses_the_authorities_file() -> None:
    """Verifies that create_session returns a requests.Session configured with the bundled authorities file."""
    session = create_session()
    assert isinstance(session, requests.Session)
    assert session.verify == str(certificate_authorities())
