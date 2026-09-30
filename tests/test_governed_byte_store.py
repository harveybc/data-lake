"""Disposable governed byte store. Not a deployed lake and not a registration."""

from __future__ import annotations

import hashlib

import pytest

from data_lake_service.backends import CAPABILITIES, LakeBackendBase
from data_lake_service.byte_store import ByteStoreRefusal, GovernedByteStore
from data_lake_service.errors import UnsupportedError


def test_capabilities_are_declared_and_not_implied_by_write_metrics() -> None:
    assert "byte_upload" in CAPABILITIES
    assert "byte_read" in CAPABILITIES
    assert "write_metrics" in CAPABILITIES
    base = LakeBackendBase()
    with pytest.raises(UnsupportedError, match="write_metrics"):
        base.write_metrics({"metrics": {"MAE": 0.1}})
    with pytest.raises(UnsupportedError, match="byte_upload"):
        base.put_bytes(b"abc", grant="g")
    store = GovernedByteStore(":memory:", grants={"granted-test"})
    described = store.describe()
    assert described["label"] == "DISPOSABLE_BYTE_STORE_NOT_DEPLOYED_LAKE"
    assert described["deployed_lake"] is False
    assert described["registration_authorizes_delivery"] is False
    assert described["capabilities"] == ["byte_upload", "byte_read"]
    with pytest.raises(UnsupportedError, match="consumer report"):
        store.write_metrics({"metrics": {"MAE": 0.1}})
    assert store._conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_round_trip_checks_the_hash_and_refuses_a_mismatch() -> None:
    store = GovernedByteStore(":memory:", grants={"granted-test"})
    payload = b"verified-bytes"
    digest = store.put_bytes(payload, grant="granted-test")
    assert digest == hashlib.sha256(payload).hexdigest()
    assert store.get_bytes(digest, grant="granted-test") == payload
    assert store.put_bytes(payload, grant="granted-test") == digest
    store._conn.execute("UPDATE objects SET content=? WHERE digest=?", (b"short", digest))
    with pytest.raises(ByteStoreRefusal, match="HASH_MISMATCH"):
        store.get_bytes(digest, grant="granted-test")


def test_missing_grant_writes_nothing() -> None:
    with pytest.raises(ByteStoreRefusal, match="GRANT_REQUIRED"):
        GovernedByteStore(":memory:", grants=set())
    store = GovernedByteStore(":memory:", grants={"granted-test"})
    with pytest.raises(ByteStoreRefusal, match="GRANT_REFUSED"):
        store.put_bytes(b"abc", grant="")
    with pytest.raises(ByteStoreRefusal, match="GRANT_REFUSED"):
        store.get_bytes("ab" * 32, grant="other")
    assert store._conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_refuses_postgres_and_uses_a_file_backend(tmp_path) -> None:
    with pytest.raises(ByteStoreRefusal, match="POSTGRES_REFUSED"):
        GovernedByteStore("postgresql://example/lake", grants={"granted-test"})
    path = tmp_path / "bytes.sqlite"
    store = GovernedByteStore(path, grants={"granted-test"})
    digest = store.put_bytes(b"on-disk", grant="granted-test")
    store._conn.close()
    again = GovernedByteStore(path, grants={"granted-test"})
    assert again.get_bytes(digest, grant="granted-test") == b"on-disk"
    assert again.describe()["deployed_lake"] is False
