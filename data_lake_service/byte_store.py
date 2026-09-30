"""Disposable governed byte store.

Not a deployed lake. ``write_metrics`` still stores a consumer report, and a
resource registration does not authorize a read or a write here. Every call
needs a grant supplied by the caller. Bytes are stored by SHA-256. A read
whose bytes do not match that digest is refused.
"""

from __future__ import annotations

import hashlib
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
