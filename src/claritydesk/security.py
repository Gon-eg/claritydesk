"""Security & sandboxing for sensitive business documents.

ClarityDesk's promise: a small business can audit a confidential HR policy or
contract without that file's *contents* leaving the local processing session.

Two concrete guarantees are implemented here:

1. `network_guard()` - a context manager that blocks all outbound network
   connections while document bytes are in memory. Any attempt to upload the
   document (or anything else) raises `EgressBlocked`. The only way to allow a
   destination is to pass an explicit allowlist, which the optional cloud
   vision provider must request - making any egress an auditable, opt-in event.

2. `LocalDocument` - validates that input is a real local file under a size
   cap, computes a content hash for the audit trail, and never logs content.
"""
from __future__ import annotations

import hashlib
import os
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

MAX_BYTES = 100 * 1024 * 1024  # 100 MB safety cap


class EgressBlocked(RuntimeError):
    """Raised when code tries to open a network connection inside network_guard."""


class DocumentTooLarge(ValueError):
    pass


def _host_allowed(address, allowlist: set[str]) -> bool:
    try:
        host = address[0]
    except Exception:
        return False
    if host in ("127.0.0.1", "::1", "localhost"):
        return True  # loopback is always fine (local model servers, etc.)
    return host in allowlist


@contextmanager
def network_guard(allow_hosts: Optional[list[str]] = None) -> Iterator[None]:
    """Block outbound sockets for the duration of the block.

    Loopback is always allowed. Any other destination must be explicitly listed
    in `allow_hosts`; otherwise `EgressBlocked` is raised. This is what lets the
    audit pipeline guarantee documents are processed locally.
    """
    allowlist = set(allow_hosts or [])
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address, *a, **kw):
        if not _host_allowed(address, allowlist):
            raise EgressBlocked(
                f"Blocked outbound connection to {address!r}. ClarityDesk "
                f"processes documents locally; add the host to an explicit "
                f"allowlist to permit egress."
            )
        return real_connect(self, address, *a, **kw)

    def guarded_connect_ex(self, address, *a, **kw):
        if not _host_allowed(address, allowlist):
            raise EgressBlocked(f"Blocked outbound connection to {address!r}.")
        return real_connect_ex(self, address, *a, **kw)

    socket.socket.connect = guarded_connect          # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex    # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect          # type: ignore[assignment]
        socket.socket.connect_ex = real_connect_ex    # type: ignore[assignment]


@dataclass
class LocalDocument:
    """A validated, local-only handle to a document under audit."""
    path: Path
    sha256: str
    size: int

    @classmethod
    def open(cls, path: str | os.PathLike, max_bytes: int = MAX_BYTES) -> "LocalDocument":
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Not a local file: {p}")
        size = p.stat().st_size
        if size > max_bytes:
            raise DocumentTooLarge(
                f"{p.name} is {size} bytes, exceeds cap of {max_bytes} bytes."
            )
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return cls(path=p, sha256=h.hexdigest(), size=size)

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
