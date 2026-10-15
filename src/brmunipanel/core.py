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

MANIFEST = "manifest.json"
USER_AGENT = "Mozilla/5.0 (compatible; brmunipanel/0.1)"


class InvalidResponse(Exception):
    """The response arrived with HTTP 200, but the content is not what was expected (error page, empty table, etc.)."""


@dataclass(frozen=True)
class Request:
    """A request and the raw file it generates, relative to the source folder."""

    key: str
    url: str
    file: str
    method: str = "GET"
    body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    compress: bool = True


def read_manifest(folder: Path) -> dict[str, dict]:
    path = Path(folder) / MANIFEST
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".partial")
    temp.write_bytes(content)
    os.replace(temp, path)


def _write_manifest(folder: Path, manifest: dict[str, dict]) -> None:
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    _write_atomic(Path(folder) / MANIFEST, text.encode("utf-8"))


def read_raw(folder: Path, file: str) -> bytes:
    """Returns the bytes of the original response, decompressing when the file was saved in gzip."""
    content = (Path(folder) / file).read_bytes()
    return gzip.decompress(content) if file.endswith(".gz") else content


def _send_request(req: Request, session: requests.Session, timeout: float) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, **req.headers}
    if req.method == "POST":
        return session.post(req.url, data=req.body, headers=headers, timeout=timeout)
    return session.get(req.url, headers=headers, timeout=timeout)


def _check_record(folder: Path, req: Request, record: dict) -> None:
    """Raises when the manifest record no longer describes `req` or the file on disk no longer matches it."""
    expected = {"url": req.url, "method": req.method, "file": req.file, "body": req.body}
    different = [field for field, value in expected.items() if record.get(field) != value]
    if different:
        raise RuntimeError(f"{req.key}: the request differs from the manifest record ({', '.join(different)})")
    written = (folder / req.file).read_bytes()
    try:
        content = gzip.decompress(written) if req.compress else written
    except (OSError, EOFError) as error:
        raise RuntimeError(f"{req.key}: file {req.file} could not be decompressed ({error})") from error
    if len(content) != record.get("bytes") or hashlib.sha256(content).hexdigest() != record.get("sha256"):
        raise RuntimeError(f"{req.key}: file {req.file} changed after it was recorded in the manifest")


def download(
    req: Request,
    folder: Path,
    *,
    session: requests.Session | None = None,
    validate: Callable[[bytes], None] | None = None,
    attempts: int = 5,
    wait: float = 10.0,
    timeout: float = 300.0,
) -> tuple[dict, bool]:
    """Downloads `req` into `folder` and records it in the manifest. Returns the record and whether a download occurred.

    Network errors, HTTP 429 and 5xx, and responses rejected by `validate` are retried, with waiting time
    doubled on each attempt. Other HTTP errors and a failed certificate verification are raised immediately,
    because retrying does not resolve them.

    A key already in the manifest whose file exists is reused only when the record matches the request and the file
    still has the recorded size and hash; otherwise an error is raised and nothing is downloaded or overwritten.
    """
    folder = Path(folder)
    manifest = read_manifest(folder)
    target = folder / req.file
    if req.key in manifest and target.exists():
        _check_record(folder, req, manifest[req.key])
        return manifest[req.key], False

    session = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(wait * 2 ** (attempt - 1))
        try:
            response = _send_request(req, session, timeout)
            if response.status_code == 429 or response.status_code >= 500:
                raise InvalidResponse(f"HTTP {response.status_code}")
            response.raise_for_status()
            content = response.content
            if validate is not None:
                validate(content)
            break
        except requests.exceptions.SSLError as error:
            if "CERTIFICATE_VERIFY_FAILED" in str(error):
                raise RuntimeError(f"{req.key}: server certificate verification failed ({error})") from error
            last_error = error
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError, InvalidResponse) as error:
            last_error = error
    else:
        raise RuntimeError(f"{req.key}: failed after {attempts} attempts ({last_error})") from last_error

    written = gzip.compress(content, mtime=0) if req.compress else content
    _write_atomic(target, written)
    record = {
        "url": req.url,
        "method": req.method,
        "file": req.file,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if req.body is not None:
        record["body"] = req.body
    manifest = read_manifest(folder)
    manifest[req.key] = record
    _write_manifest(folder, manifest)
    return record, True


def record_manual(folder: Path, key: str, file: str, *, url: str, parameters: dict[str, str]) -> tuple[dict, bool]:
    """Records in the manifest a file that is already in `folder`, downloaded manually. Returns the record and whether it is new."""
    folder = Path(folder)
    target = folder / file
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")

    content = target.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()

    manifest = read_manifest(folder)

    if key in manifest:
        if manifest[key].get("sha256") == sha256:
            return manifest[key], False
        raise RuntimeError(f"{key}: file changed after it was recorded")

    mtime = target.stat().st_mtime
    downloaded_in = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")

    record = {
        "url": url,
        "method": "MANUAL",
        "file": file,
        "bytes": len(content),
        "sha256": sha256,
        "downloaded_at": downloaded_in,
        "parameters": parameters,
    }

    manifest[key] = record
    _write_manifest(folder, manifest)

    return record, True


@contextmanager
def ipv4_only():
    """Resolves host names to IPv4 addresses only while the block runs, then restores the previous behaviour."""
    original = urllib3.util.connection.allowed_gai_family
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
    try:
        yield
    finally:
        urllib3.util.connection.allowed_gai_family = original


def download_at_rate(
    reqs: Sequence[Request],
    target: Path,
    *,
    rate: float = 4.0,
    concurrent: int = 8,
    session: requests.Session | None = None,
    validate: Callable[[bytes], None] | None = None,
    attempts: int = 5,
    wait: float = 10.0,
    pause_429: float = 30.0,
    timeout: float = 120.0,
    notify: Callable[[str], None] | None = print,
) -> dict:
    """Downloads many small GET responses at a fixed rate into one gzip JSON Lines file.

    A request starts every 1/`rate` seconds, without waiting for the previous one, with at most `concurrent`
    in flight. Each line holds the request key, URL, HTTP status and the response body as received. Lines are
    appended to `<target>.em_andamento` as responses arrive, so an interrupted run resumes from the keys already there.
    Network errors and HTTP 5xx are retried with doubled waits; HTTP 429 pauses new requests for `pause_429`
    seconds and retries; a failed certificate verification is raised at once. When every key is present, the lines
    are sorted by key, compressed into `target` and the partial file is removed.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".in_progress")
    done = set()
    if partial.exists():
        for row in partial.read_text(encoding="utf-8").splitlines():
            if row.strip():
                done.add(json.loads(row)["key"])
    pending = [r for r in reqs if r.key not in done]
    session = session or requests.Session()
    lock = threading.Lock()
    slots = threading.Semaphore(concurrent)
    state = {"pause_until": 0.0, "failures": {}, "pauses_429": 0}

    def wait_pause() -> None:
        while True:
            remaining = state["pause_until"] - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(remaining)

    def run(req: Request) -> None:
        try:
            last = None
            for attempt in range(attempts):
                if attempt:
                    time.sleep(wait * 2 ** (attempt - 1))
                wait_pause()
                try:
                    response = session.get(req.url, headers={"User-Agent": USER_AGENT, **req.headers}, timeout=timeout)
                    if response.status_code == 429:
                        with lock:
                            state["pause_until"] = max(state["pause_until"], time.monotonic() + pause_429)
                            state["pauses_429"] += 1
                        last = InvalidResponse("HTTP 429")
                        continue
                    if response.status_code >= 500:
                        raise InvalidResponse(f"HTTP {response.status_code}")
                    response.raise_for_status()
                    content = response.content
                    if validate is not None:
                        validate(content)
                    row = json.dumps({"key": req.key, "url": req.url, "http": response.status_code, "body": content.decode("utf-8")}, ensure_ascii=False)
                    with lock:
                        with open(partial, "a", encoding="utf-8") as file:
                            file.write(row + "\n")
                    return
                except requests.exceptions.SSLError as error:
                    if "CERTIFICATE_VERIFY_FAILED" in str(error):
                        raise RuntimeError(f"{req.key}: server certificate verification failed ({error})") from error
                    last = error
                except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError, InvalidResponse) as error:
                    last = error
            with lock:
                state["failures"][req.key] = str(last)
        finally:
            slots.release()

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrent) as pool:
        futures = []
        for n, req in enumerate(pending):
            scheduled = start + n / rate
            now = time.monotonic()
            if scheduled > now:
                time.sleep(scheduled - now)
            wait_pause()
            slots.acquire()
            futures.append(pool.submit(run, req))
        for future in futures:
            future.result()

    if notify is not None:
        notify(f"{target.name}: {len(pending)} requests in {time.monotonic() - start:.1f}s, {len(done)} were already in the partial file, "
               f"{len(state['failures'])} failures, {state['pauses_429']} 429 responses")
    if state["failures"]:
        example = next(iter(state["failures"].items()))
        raise RuntimeError(f"{target.name}: {len(state['failures'])} requests failed; run again to continue. Example: {example}")
    rows = [json.loads(row) for row in partial.read_text(encoding="utf-8").splitlines() if row.strip()]
    rows.sort(key=lambda d: d["key"])
    text = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in rows).encode("utf-8")
    _write_atomic(target, gzip.compress(text, mtime=0))
    partial.unlink()
    return {"rows": len(rows), "pauses_429": state["pauses_429"]}


def record_file(folder: Path, key: str, file: str, *, url: str, method: str, parameters: dict[str, str]) -> dict:
    """Records in the manifest a file that the library itself wrote to `folder`."""
    folder = Path(folder)
    content = (folder / file).read_bytes()
    record = {
        "url": url,
        "method": method,
        "file": file,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parameters": parameters,
    }
    manifest = read_manifest(folder)
    manifest[key] = record
    _write_manifest(folder, manifest)
    return record


def download_batch(
    reqs: Iterable[Request],
    folder: Path,
    *,
    interval: float = 0.0,
    notify: Callable[[str], None] | None = print,
    **options,
) -> list[dict]:
    """Downloads requests in sequence, in the same HTTP session, skipping those already in the manifest."""
    session = options.pop("session", None) or requests.Session()
    records = []
    for req in reqs:
        start = time.monotonic()
        record, downloaded = download(req, folder, session=session, **options)
        records.append(record)
        if notify is not None:
            status = f"downloaded in {time.monotonic() - start:.1f}s" if downloaded else "already in the manifest"
            notify(f"{req.key}: {record['bytes']:,} bytes, {status}")
        if downloaded and interval:
            time.sleep(interval)
    return records
