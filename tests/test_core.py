"""Tests for the common download, manifest, and retry core (brmunipanel.core)."""

from __future__ import annotations

import gzip
import hashlib
import json
import socket
import threading
import time
from pathlib import Path
from typing import Sequence

import pytest
import requests
import urllib3.util.connection

from brmunipanel.core import (
    Request,
    InvalidResponse,
    download,
    download_at_rate,
    download_batch,
    read_raw,
    read_manifest,
    record_file,
    record_manual,
    ipv4_only,
)


class FakeResponse:
    def __init__(self, content: bytes = b"conteudo de teste", status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 500:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)
        if self.status_code >= 500:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses: Sequence[FakeResponse | Exception] | None = None) -> None:
        self._responses = list(responses) if responses is not None else [FakeResponse()]
        self.calls: list[dict] = []

    def get(self, url: str, headers: dict | None = None, timeout: float = 300.0) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers, "timeout": timeout})
        return self._next()

    def post(self, url: str, data: str | None = None, headers: dict | None = None, timeout: float = 300.0) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, "data": data, "headers": headers, "timeout": timeout})
        return self._next()

    def _next(self) -> FakeResponse:
        if not self._responses:
            raise IndexError("No response left in the fake session")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_download_writes_gzip_and_read_raw_decompresses(tmp_path: Path) -> None:
    """1. download saves the file in gzip, and read_raw returns exactly the response bytes."""
    data = b"resposta original em texto ou json"
    session = FakeSession([FakeResponse(data, 200)])
    req = Request(key="test/1", url="http://example.org/1", file="test/1.json.gz", compress=True)

    record, downloaded = download(req, tmp_path, session=session, wait=0)

    assert downloaded is True
    target = tmp_path / req.file
    assert target.exists()
    assert gzip.decompress(target.read_bytes()) == data
    assert read_raw(tmp_path, req.file) == data


def test_manifest_records_expected_fields_get_and_post(tmp_path: Path) -> None:
    """2. The manifest records url, method, file, bytes, sha256 (of the response, not gzip), and downloaded_in; on POST, also body."""
    data_get = b"resposta get"
    session_get = FakeSession([FakeResponse(data_get, 200)])
    req_get = Request(key="source/get", url="http://example.org/get", file="source/get.json.gz")
    record_get, _ = download(req_get, tmp_path, session=session_get, wait=0)

    assert record_get["url"] == "http://example.org/get"
    assert record_get["method"] == "GET"
    assert record_get["file"] == "source/get.json.gz"
    assert record_get["bytes"] == len(data_get)
    assert record_get["sha256"] == hashlib.sha256(data_get).hexdigest()
    assert "downloaded_at" in record_get
    assert "body" not in record_get

    manifest = read_manifest(tmp_path)
    assert manifest["source/get"] == record_get

    # POST with body
    data_post = b"resposta post"
    session_post = FakeSession([FakeResponse(data_post, 200)])
    req_post = Request(
        key="source/post",
        url="http://example.org/post",
        file="source/post.json.gz",
        method="POST",
        body="param1=val1",
    )
    record_post, _ = download(req_post, tmp_path, session=session_post, wait=0)

    assert record_post["url"] == "http://example.org/post"
    assert record_post["method"] == "POST"
    assert record_post["file"] == "source/post.json.gz"
    assert record_post["body"] == "param1=val1"
    assert record_post["bytes"] == len(data_post)
    assert record_post["sha256"] == hashlib.sha256(data_post).hexdigest()
    assert "downloaded_at" in record_post

    manifest_current = read_manifest(tmp_path)
    assert manifest_current["source/post"] == record_post


def test_second_call_returns_record_without_new_request(tmp_path: Path) -> None:
    """3. Second call with the same key does not make a request and returns the same record (downloaded False)."""
    data = b"resposta imutavel"
    session = FakeSession([FakeResponse(data, 200)])
    req = Request(key="key/unique", url="http://example.org/data", file="data.json.gz")

    record1, downloaded1 = download(req, tmp_path, session=session, wait=0)
    assert downloaded1 is True
    assert len(session.calls) == 1

    record2, downloaded2 = download(req, tmp_path, session=session, wait=0)
    assert downloaded2 is False
    assert record1 == record2
    assert len(session.calls) == 1  # did not call again


def test_retries_http_500(tmp_path: Path) -> None:
    """4. HTTP 500 followed by 200 results in success, with 2 requests; HTTP 500 across all attempts raises RuntimeError and leaves no file or record."""
    # Recovery case on the 2nd attempt
    session_recovered = FakeSession([FakeResponse(b"erro", 500), FakeResponse(b"ok final", 200)])
    req1 = Request(key="attempts/recovered", url="http://example.org/recovered", file="recovered.json.gz")
    record, downloaded = download(req1, tmp_path, session=session_recovered, attempts=3, wait=0)
    assert downloaded is True
    assert record["bytes"] == len(b"ok final")
    assert len(session_recovered.calls) == 2

    # Persistent failure case
    session_failure = FakeSession([FakeResponse(b"erro", 500), FakeResponse(b"erro", 502), FakeResponse(b"erro", 503)])
    req2 = Request(key="attempts/failure", url="http://example.org/failure", file="failure.json.gz")
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        download(req2, tmp_path, session=session_failure, attempts=3, wait=0)

    assert not (tmp_path / req2.file).exists()
    assert req2.key not in read_manifest(tmp_path)


def test_validate_invalid_response_causes_retry(tmp_path: Path) -> None:
    """5. A validator that raises InvalidResponse triggers a new attempt, and nothing is saved while the response is rejected."""
    calls_validate = 0

    def validator(content: bytes) -> None:
        nonlocal calls_validate
        calls_validate += 1
        if content == b"incompleto":
            raise InvalidResponse("incomplete content")

    session = FakeSession([FakeResponse(b"incompleto", 200), FakeResponse(b"completo", 200)])
    req = Request(key="validation/test", url="http://example.org/val", file="val.json.gz")

    record, downloaded = download(req, tmp_path, session=session, validate=validator, attempts=3, wait=0)
    assert downloaded is True
    assert calls_validate == 2
    assert len(session.calls) == 2
    assert read_raw(tmp_path, req.file) == b"completo"

    # If validation always fails:
    def always_failing_validator(c: bytes) -> None:
        raise InvalidResponse("always rejects")

    session_failure = FakeSession([FakeResponse(b"lixo", 200), FakeResponse(b"lixo", 200)])
    req_failure = Request(key="validation/failure", url="http://example.org/val_failure", file="val_failure.json.gz")
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        download(req_failure, tmp_path, session=session_failure, validate=always_failing_validator, attempts=2, wait=0)

    assert not (tmp_path / req_failure.file).exists()
    assert req_failure.key not in read_manifest(tmp_path)


def test_http_404_raises_immediately_on_first_attempt(tmp_path: Path) -> None:
    """6. HTTP 404 raises immediately as requests.HTTPError on the first attempt."""
    session = FakeSession([FakeResponse(b"nao encontrado", 404)])
    req = Request(key="error/404", url="http://example.org/404", file="404.json.gz")

    with pytest.raises(requests.HTTPError) as exc_info:
        download(req, tmp_path, session=session, attempts=5, wait=0)

    assert exc_info.value.response.status_code == 404
    assert len(session.calls) == 1
    assert not (tmp_path / req.file).exists()
    assert req.key not in read_manifest(tmp_path)


def test_compress_false_writes_without_gzip(tmp_path: Path) -> None:
    """7. compress=False saves bytes without gzip."""
    binary_data = b"\x00\x01\x02\x03\xff"
    session = FakeSession([FakeResponse(binary_data, 200)])
    req = Request(key="bin/raw", url="http://example.org/bin", file="file.bin", compress=False)

    record, downloaded = download(req, tmp_path, session=session, wait=0)
    assert downloaded is True
    target = tmp_path / req.file
    assert target.read_bytes() == binary_data
    assert read_raw(tmp_path, req.file) == binary_data


def test_download_batch_keeps_previous_records(tmp_path: Path) -> None:
    """8. download_batch preserves previous manifest records when adding a new one."""
    session1 = FakeSession([FakeResponse(b"dado1", 200)])
    req1 = Request(key="batch/1", url="http://example.org/1", file="1.json.gz")
    download(req1, tmp_path, session=session1, wait=0)

    manifest_before = read_manifest(tmp_path)
    assert "batch/1" in manifest_before

    session2 = FakeSession([FakeResponse(b"dado2", 200)])
    req2 = Request(key="batch/2", url="http://example.org/2", file="2.json.gz")
    download_batch([req2], tmp_path, session=session2, wait=0, notify=None)

    manifest_after = read_manifest(tmp_path)
    assert "batch/1" in manifest_after
    assert "batch/2" in manifest_after
    assert manifest_after["batch/1"] == manifest_before["batch/1"]


def test_record_manual_nonexistent_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        record_manual(tmp_path, "key", "nonexistent.zip", url="http", parameters={})


def test_record_manual_new_file(tmp_path: Path) -> None:
    file = tmp_path / "manual.zip"
    file.write_bytes(b"conteudo")
    record, new = record_manual(tmp_path, "key1", "manual.zip", url="http://url", parameters={"a": "b"})
    assert new is True
    assert record["url"] == "http://url"
    assert record["method"] == "MANUAL"
    assert record["file"] == "manual.zip"
    assert record["bytes"] == 8
    assert record["parameters"] == {"a": "b"}
    assert "downloaded_at" in record
    assert read_manifest(tmp_path)["key1"] == record


def test_record_manual_existing_file_same_hash(tmp_path: Path) -> None:
    file = tmp_path / "manual2.zip"
    file.write_bytes(b"conteudo2")
    record1, new1 = record_manual(tmp_path, "key2", "manual2.zip", url="http", parameters={})
    assert new1 is True
    
    record2, new2 = record_manual(tmp_path, "key2", "manual2.zip", url="http", parameters={})
    assert new2 is False
    assert record1 == record2


def test_record_manual_existing_file_different_hash(tmp_path: Path) -> None:
    file = tmp_path / "manual3.zip"
    file.write_bytes(b"conteudo3")
    record_manual(tmp_path, "key3", "manual3.zip", url="http", parameters={})
    
    file.write_bytes(b"novo_conteudo3")
    with pytest.raises(RuntimeError, match="file changed after it was recorded"):
        record_manual(tmp_path, "key3", "manual3.zip", url="http", parameters={})


def test_certificate_error_raises_without_retry(tmp_path: Path) -> None:
    error_ssl = requests.exceptions.SSLError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate"
    )
    session = FakeSession([error_ssl])
    req = Request(key="test/cert", url="http://example.org/cert", file="cert.bin")

    with pytest.raises(RuntimeError, match="server certificate verification failed"):
        download(req, tmp_path, session=session, attempts=5, wait=0)

    assert len(session.calls) == 1
    assert not (tmp_path / req.file).exists()
    assert req.key not in read_manifest(tmp_path)


def test_tls_error_not_certificate_causes_retry(tmp_path: Path) -> None:
    error_ssl = requests.exceptions.SSLError("EOF occurred in violation of protocol")
    session = FakeSession([error_ssl, FakeResponse(b"ok", 200)])
    req = Request(key="test/tls", url="http://example.org/tls", file="tls.bin", compress=False)

    record, downloaded = download(req, tmp_path, session=session, attempts=3, wait=0)
    assert downloaded is True
    assert len(session.calls) == 2
    assert (tmp_path / req.file).read_bytes() == b"ok"
    assert read_raw(tmp_path, req.file) == b"ok"


def test_download_at_rate_writes_sorted_rows(tmp_path: Path) -> None:
    keys = ["req_e", "req_b", "req_d", "req_a", "req_c"]
    reqs = [Request(key=k, url=f"http://api.test/{k}", file="output.jsonl.gz") for k in keys]
    target = tmp_path / "output.jsonl.gz"

    class SortedSession:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            key = url.split("/")[-1]
            return FakeResponse(f"body_{key}".encode("utf-8"), 200)

    res = download_at_rate(reqs, target, rate=100.0, session=SortedSession(), notify=None, wait=0)

    assert target.exists()
    assert not (tmp_path / "output.jsonl.gz.in_progress").exists()
    assert res["rows"] == 5

    rows = [json.loads(row) for row in gzip.decompress(target.read_bytes()).decode("utf-8").splitlines()]
    assert len(rows) == 5
    assert [item["key"] for item in rows] == sorted(keys)
    for item in rows:
        assert item["http"] == 200
        assert item["url"] == f"http://api.test/{item['key']}"
        assert item["body"] == f"body_{item['key']}"


def test_download_at_rate_respects_the_rate(tmp_path: Path) -> None:
    times: list[float] = []
    lock = threading.Lock()

    class RateSession:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            with lock:
                times.append(time.monotonic())
            return FakeResponse(b"ok", 200)

    reqs = [Request(key=f"k{i}", url=f"http://api.test/k{i}", file="output.jsonl.gz") for i in range(6)]
    target = tmp_path / "output.jsonl.gz"
    download_at_rate(reqs, target, rate=20.0, session=RateSession(), notify=None, wait=0)

    assert len(times) == 6
    assert times[5] - times[0] >= 0.24


def test_download_at_rate_limits_concurrent(tmp_path: Path) -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()

    class ConcurrencySession:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            nonlocal active, max_active
            with lock:
                active += 1
                if active > max_active:
                    max_active = active
            time.sleep(0.1)
            with lock:
                active -= 1
            return FakeResponse(b"ok", 200)

    reqs = [Request(key=f"k{i}", url=f"http://api.test/k{i}", file="output.jsonl.gz") for i in range(6)]
    target = tmp_path / "output.jsonl.gz"
    download_at_rate(reqs, target, rate=100.0, concurrent=2, session=ConcurrencySession(), notify=None, wait=0)

    assert max_active == 2


def test_download_at_rate_pauses_on_429(tmp_path: Path) -> None:
    calls: list[float] = []
    lock = threading.Lock()

    class Session429:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            with lock:
                now = time.monotonic()
                first = len(calls) == 0
                calls.append(now)
            if first:
                return FakeResponse(b"calm down", 429)
            return FakeResponse(b"ok body", 200)

    reqs = [Request(key="r1", url="http://api.test/r1", file="output.jsonl.gz")]
    target = tmp_path / "output.jsonl.gz"
    res = download_at_rate(reqs, target, rate=100.0, pause_429=0.2, session=Session429(), notify=None, wait=0)

    assert target.exists()
    rows = [json.loads(row) for row in gzip.decompress(target.read_bytes()).decode("utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["key"] == "r1"
    assert rows[0]["http"] == 200
    assert rows[0]["body"] == "ok body"
    assert res["pauses_429"] == 1
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.2


def test_download_at_rate_resumes_from_partial(tmp_path: Path) -> None:
    target = tmp_path / "output.jsonl.gz"
    partial = tmp_path / "output.jsonl.gz.in_progress"
    partial.write_text(
        json.dumps({"key": "k1", "url": "http://api.test/k1", "http": 200, "body": "c1"}) + "\n"
        + json.dumps({"key": "k2", "url": "http://api.test/k2", "http": 200, "body": "c2"}) + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []
    lock = threading.Lock()

    class ResumeSession:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            with lock:
                calls.append(url)
            key = url.split("/")[-1]
            return FakeResponse(f"body_{key}".encode("utf-8"), 200)

    reqs = [Request(key=f"k{i}", url=f"http://api.test/k{i}", file="output.jsonl.gz") for i in (1, 2, 3, 4)]
    download_at_rate(reqs, target, rate=100.0, session=ResumeSession(), notify=None, wait=0)

    assert len(calls) == 2
    assert set(calls) == {"http://api.test/k3", "http://api.test/k4"}
    assert target.exists()
    rows = [json.loads(row) for row in gzip.decompress(target.read_bytes()).decode("utf-8").splitlines()]
    assert len(rows) == 4
    assert [item["key"] for item in rows] == ["k1", "k2", "k3", "k4"]


def test_download_at_rate_failure_keeps_partial(tmp_path: Path) -> None:
    class FailingSession:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            if "failure" in url:
                raise requests.ConnectionError("simulated failure")
            return FakeResponse(b"ok", 200)

    reqs = [
        Request(key="k1", url="http://api.test/k1", file="output.jsonl.gz"),
        Request(key="k2", url="http://api.test/failure", file="output.jsonl.gz"),
        Request(key="k3", url="http://api.test/k3", file="output.jsonl.gz"),
    ]
    target = tmp_path / "output.jsonl.gz"
    partial = tmp_path / "output.jsonl.gz.in_progress"

    with pytest.raises(RuntimeError, match="failed"):
        download_at_rate(reqs, target, rate=100.0, attempts=2, wait=0, session=FailingSession(), notify=None)

    assert not target.exists()
    assert partial.exists()
    partial_rows = [json.loads(row) for row in partial.read_text(encoding="utf-8").splitlines() if row.strip()]
    assert len(partial_rows) == 2
    assert {item["key"] for item in partial_rows} == {"k1", "k3"}


def test_download_at_rate_certificate_error(tmp_path: Path) -> None:
    class CertErrorSession:
        def get(self, url: str, headers: dict | None = None, timeout: float = 120.0) -> FakeResponse:
            raise requests.exceptions.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    reqs = [Request(key="k1", url="http://api.test/k1", file="output.jsonl.gz")]
    target = tmp_path / "output.jsonl.gz"

    with pytest.raises(RuntimeError, match="certificate"):
        download_at_rate(reqs, target, rate=100.0, session=CertErrorSession(), notify=None, wait=0)


def test_record_file(tmp_path: Path) -> None:
    file = tmp_path / "data.bin"
    content = b"amostra de teste"
    file.write_bytes(content)

    reg = record_file(
        tmp_path,
        "dca_test",
        "data.bin",
        url="http://api.test/dca",
        method="GET",
        parameters={"year": "2020", "ente": "123"},
    )

    assert reg["method"] == "GET"
    assert reg["parameters"] == {"year": "2020", "ente": "123"}
    assert reg["bytes"] == len(content)
    assert reg["sha256"] == hashlib.sha256(content).hexdigest()
    assert read_manifest(tmp_path)["dca_test"] == reg


def test_ipv4_only_restores() -> None:
    original = urllib3.util.connection.allowed_gai_family
    with ipv4_only():
        assert urllib3.util.connection.allowed_gai_family() == socket.AF_INET
    assert urllib3.util.connection.allowed_gai_family is original


def test_reuse_with_different_url_raises_error(tmp_path: Path) -> None:
    """A recorded key requested again with another URL raises, without a request and without touching the file."""
    session = FakeSession([FakeResponse(b"versao 1", 200)])
    req = Request(key="source/1", url="http://example.org/v1", file="source/1.json.gz")
    download(req, tmp_path, session=session, wait=0)
    written = (tmp_path / req.file).read_bytes()

    other = Request(key="source/1", url="http://example.org/v2", file="source/1.json.gz")
    with pytest.raises(RuntimeError, match=r"source/1: the request differs from the manifest record \(url\)"):
        download(other, tmp_path, session=session, wait=0)

    assert len(session.calls) == 1
    assert (tmp_path / req.file).read_bytes() == written
    assert read_manifest(tmp_path)["source/1"]["url"] == "http://example.org/v1"


def test_reuse_with_different_body_raises_error(tmp_path: Path) -> None:
    """A recorded POST requested again with another body raises."""
    session = FakeSession([FakeResponse(b"resposta", 200)])
    req = Request(key="source/post", url="http://example.org/post", file="post.json.gz", method="POST", body="a=1")
    download(req, tmp_path, session=session, wait=0)

    other = Request(key="source/post", url="http://example.org/post", file="post.json.gz", method="POST", body="a=2")
    with pytest.raises(RuntimeError, match=r"\(body\)"):
        download(other, tmp_path, session=session, wait=0)
    assert len(session.calls) == 1


def test_reuse_of_record_without_method_raises_error(tmp_path: Path) -> None:
    """A record written without the `method` field does not describe the request and raises."""
    data = b"PK\x03\x04conteudo"
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "a.zip").write_bytes(data)
    record = {
        "url": "http://example.org/a.zip",
        "file": "packages/a.zip",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"packages/a": record}), encoding="utf-8")

    req = Request(key="packages/a", url="http://example.org/a.zip", file="packages/a.zip", compress=False)
    session = FakeSession([])
    with pytest.raises(RuntimeError, match=r"\(method\)"):
        download(req, tmp_path, session=session, wait=0)
    assert session.calls == []


def test_reuse_with_modified_file_raises_error(tmp_path: Path) -> None:
    """A gzip file replaced by another valid gzip after the download raises, and is not downloaded again."""
    session = FakeSession([FakeResponse(b"original", 200)])
    req = Request(key="source/2", url="http://example.org/2", file="2.json.gz")
    download(req, tmp_path, session=session, wait=0)
    modified = gzip.compress(b"outro conteudo", mtime=0)
    (tmp_path / req.file).write_bytes(modified)

    with pytest.raises(RuntimeError, match=r"source/2: file 2\.json\.gz changed after it was recorded in the manifest"):
        download(req, tmp_path, session=session, wait=0)
    assert len(session.calls) == 1
    assert (tmp_path / req.file).read_bytes() == modified


def test_reuse_with_truncated_gzip_raises_error(tmp_path: Path) -> None:
    """A truncated gzip file raises an error that names the file."""
    session = FakeSession([FakeResponse(b"conteudo longo " * 100, 200)])
    req = Request(key="source/3", url="http://example.org/3", file="3.json.gz")
    download(req, tmp_path, session=session, wait=0)
    target = tmp_path / req.file
    target.write_bytes(target.read_bytes()[:20])

    with pytest.raises(RuntimeError, match=r"source/3: file 3\.json\.gz could not be decompressed"):
        download(req, tmp_path, session=session, wait=0)
    assert len(session.calls) == 1


def test_reuse_without_compression_checks_the_hash(tmp_path: Path) -> None:
    """An uncompressed file with one byte changed raises; the unchanged file is reused without a request."""
    session = FakeSession([FakeResponse(b"\x00\x01\x02\x03", 200)])
    req = Request(key="bin/1", url="http://example.org/bin", file="1.bin", compress=False)
    record, _ = download(req, tmp_path, session=session, wait=0)

    assert download(req, tmp_path, session=session, wait=0) == (record, False)
    (tmp_path / req.file).write_bytes(b"\x00\x01\x02\x04")
    with pytest.raises(RuntimeError, match=r"changed after it was recorded"):
        download(req, tmp_path, session=session, wait=0)
    assert len(session.calls) == 1


