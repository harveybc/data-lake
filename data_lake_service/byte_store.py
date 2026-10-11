"""Disposable governed byte store.

Not a deployed lake. ``write_metrics`` still stores a consumer report, and a
resource registration does not authorize a read or a write here. Every call
needs a grant supplied by the caller. Bytes are stored by SHA-256. A read
whose bytes do not match that digest is refused.
"""

from __future__ import annotations

import hashlib
import os
import threading
import sqlite3
from pathlib import Path

from .backends import LakeBackendBase
from .errors import LakeError, UnsupportedError


class ByteStoreRefusal(LakeError):
    """A grant or a hash check failed. The bytes are not returned as verified."""


class GovernedByteStore(LakeBackendBase):
    """SQLite byte store for a disposable test. ``deployed_lake`` stays false."""

    LABEL = "DISPOSABLE_BYTE_STORE_NOT_DEPLOYED_LAKE"
    declared_capabilities = ("byte_upload", "byte_read")

    def __init__(self, path: str | Path = ":memory:", *, grants: set[str]):
        super().__init__()
        if not grants or any(not isinstance(item, str) or not item for item in grants):
            raise ByteStoreRefusal("GRANT_REQUIRED")
        text = str(path)
        if text.lower().startswith("postgres"):
            raise ByteStoreRefusal("POSTGRES_REFUSED")
        self._grants = set(grants)
        self._memory = text == ":memory:"
        if text != ":memory:":
            Path(text).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(text, check_same_thread=False, isolation_level=None)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS objects (
                   digest TEXT PRIMARY KEY,
                   content BLOB NOT NULL
               )"""
        )

    def describe(self) -> dict:
        return {
            "label": self.LABEL,
            "deployed_lake": False,
            "registration_authorizes_delivery": False,
            "capabilities": list(self.capabilities()),
            "backend": "sqlite-memory" if self._memory else "sqlite-file",
        }

    def write_metrics(self, report: dict):
        raise UnsupportedError("write_metrics stores a consumer report, not resource bytes")

    def put_bytes(self, content: bytes, *, grant: str) -> str:
        self._require(grant)
        if not isinstance(content, (bytes, bytearray)):
            raise ByteStoreRefusal("BYTES_REQUIRED")
        payload = bytes(content)
        digest = hashlib.sha256(payload).hexdigest()
        row = self._conn.execute(
            "SELECT content FROM objects WHERE digest=?",
            (digest,),
        ).fetchone()
        if row is not None:
            stored = bytes(row[0])
            if stored != payload or hashlib.sha256(stored).hexdigest() != digest:
                raise ByteStoreRefusal("HASH_MISMATCH")
            return digest
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                "INSERT INTO objects (digest, content) VALUES (?, ?)",
                (digest, payload),
            )
            readback = self._conn.execute(
                "SELECT content FROM objects WHERE digest=?",
                (digest,),
            ).fetchone()
            blob = bytes(readback[0]) if readback is not None else b""
            if blob != payload or hashlib.sha256(blob).hexdigest() != digest:
                raise ByteStoreRefusal("HASH_MISMATCH")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return digest

    def get_bytes(self, digest: str, *, grant: str) -> bytes:
        self._require(grant)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ByteStoreRefusal("NOT_A_SHA256")
        row = self._conn.execute(
            "SELECT content FROM objects WHERE digest=?",
            (digest,),
        ).fetchone()
        if row is None:
            raise ByteStoreRefusal("MISSING")
        blob = bytes(row[0])
        if hashlib.sha256(blob).hexdigest() != digest:
            raise ByteStoreRefusal("HASH_MISMATCH")
        return blob

    def _require(self, grant: str) -> None:
        if not isinstance(grant, str) or grant not in self._grants:
            raise ByteStoreRefusal("GRANT_REFUSED")


#: The grant a host passes after its own bearer check succeeded. A store configured with
#: explicit grants may refuse it; the default file store accepts exactly this one.
HOST_BEARER_GRANT = "host-bearer-authenticated"
_HEX64 = frozenset("0123456789abcdef")


def _is_sha256(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


class FileByteStore(LakeBackendBase):
    """Durable content-addressed directory: one immutable file per SHA-256.

    Writes go to a temporary file in the target directory, are fsynced, made read-only and
    hard-linked into place (an existing object is never replaced), then the directory is
    fsynced and the object is read back and hashed before the digest is answered. A stored
    copy that no longer hashes to its name is refused on read and on a retried write.

    ``deployed_lake`` is whatever the operator's host configuration declares (default
    false). The store does not decide that it is a deployment, and a registration in
    data-gov does not authorize a read or a write here.
    """

    LABEL = "LAKE_CAS_FILE_STORE"
    declared_capabilities = ("describe", "storage", "byte_upload", "byte_read")
    backend_params = {"root": None, "deployed": False, "grants": None,
                      "max_object_bytes": 64 * 1024 * 1024}

    def _root(self) -> Path:
        root = self.params.get("root")
        if not root:
            raise ByteStoreRefusal("ROOT_REQUIRED")
        if str(root).lower().startswith("postgres"):
            raise ByteStoreRefusal("POSTGRES_REFUSED")
        return Path(str(root)).expanduser()

    def _grants(self) -> set:
        grants = self.params.get("grants")
        return set(grants) if grants else {HOST_BEARER_GRANT}

    def _require(self, grant) -> None:
        if not isinstance(grant, str) or grant not in self._grants():
            raise ByteStoreRefusal("GRANT_REFUSED")

    def path_of(self, digest: str) -> Path:
        if not _is_sha256(digest):
            raise ByteStoreRefusal("NOT_A_SHA256")
        return self._root() / "sha256" / digest[:2] / digest[2:4] / digest

    def describe(self) -> dict:
        return {
            "label": self.LABEL,
            "deployed_lake": bool(self.params.get("deployed")),
            "registration_authorizes_delivery": False,
            "capabilities": list(self.capabilities()),
            "backend": "file-cas",
            "chain_verified": False,
        }

    def storage(self) -> dict:
        root = self._root()
        files = [p for p in (root / "sha256").rglob("*") if p.is_file()] if root.exists() else []
        return {"objects": len(files), "bytes": sum(p.stat().st_size for p in files)}

    def write_metrics(self, report: dict):
        raise UnsupportedError("write_metrics stores a consumer report, not resource bytes")

    def exists(self, digest: str, *, grant: str) -> bool:
        self._require(grant)
        return self.path_of(digest).is_file()

    def put_bytes(self, content: bytes, *, grant: str) -> str:
        self._require(grant)
        if not isinstance(content, (bytes, bytearray)):
            raise ByteStoreRefusal("BYTES_REQUIRED")
        payload = bytes(content)
        limit = int(self.params.get("max_object_bytes") or 0)
        if limit and len(payload) > limit:
            raise ByteStoreRefusal("OBJECT_TOO_LARGE")
        digest = hashlib.sha256(payload).hexdigest()
        final = self.path_of(digest)
        if final.is_file():
            if self._read_verified(final, digest) != payload:  # pragma: no cover - collision
                raise ByteStoreRefusal("HASH_MISMATCH")
            return digest
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.parent / f".{digest}.tmp{os.getpid()}.{threading.get_ident()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o444)
            try:
                os.link(tmp, final)
            except FileExistsError:
                pass  # a concurrent writer won; its bytes are verified below
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        dir_fd = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        if self._read_verified(final, digest) != payload:  # pragma: no cover - collision
            raise ByteStoreRefusal("HASH_MISMATCH")
        return digest

    def get_bytes(self, digest: str, *, grant: str) -> bytes:
        self._require(grant)
        path = self.path_of(digest)
        if not path.is_file():
            raise ByteStoreRefusal("MISSING")
        return self._read_verified(path, digest)

    @staticmethod
    def _read_verified(path: Path, digest: str) -> bytes:
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != digest:
            raise ByteStoreRefusal("HASH_MISMATCH")
        return blob


def file_backend():
    """Entry point ``cas_file_store``."""
    return FileByteStore()
