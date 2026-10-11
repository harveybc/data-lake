"""Content-addressed object routes over a durable file byte store (temporary directory)."""

from __future__ import annotations

import hashlib
import os

import pytest

from data_lake_service.byte_store import ByteStoreRefusal, FileByteStore, HOST_BEARER_GRANT
from data_lake_service.web import create_app

TOKEN = "test-token"


@pytest.fixture()
def store(tmp_path):
    backend = FileByteStore()
    backend.set_params(root=str(tmp_path / "cas"), deployed=False)
    return backend


@pytest.fixture()
def client(store):
    app = create_app({"service_token": TOKEN, "store_id": "doin_archive_cas"}, store,
                     {"distribution": "data-lake-service", "capabilities": list(store.capabilities())})
    return app.test_client()


def _auth():
    return {"Authorization": "Bearer " + TOKEN}


def test_file_store_put_get_is_content_addressed_and_durable(store, tmp_path):
    digest = store.put_bytes(b"hello", grant=HOST_BEARER_GRANT)
    assert digest == hashlib.sha256(b"hello").hexdigest()
    assert store.get_bytes(digest, grant=HOST_BEARER_GRANT) == b"hello"
    assert store.put_bytes(b"hello", grant=HOST_BEARER_GRANT) == digest  # retry, not a new object
    # A fresh instance over the same root reads the same bytes (survives a restart).
    again = FileByteStore()
    again.set_params(root=str(tmp_path / "cas"))
    assert again.get_bytes(digest, grant=HOST_BEARER_GRANT) == b"hello"
    assert not [p for p in (tmp_path / "cas").rglob("*.tmp*")]
    described = store.describe()
    assert described["label"] == "LAKE_CAS_FILE_STORE"
    assert described["deployed_lake"] is False
    assert described["registration_authorizes_delivery"] is False


def test_file_store_refuses_corrupt_bytes_missing_and_bad_grant(store, tmp_path):
    digest = store.put_bytes(b"payload", grant=HOST_BEARER_GRANT)
    path = store.path_of(digest)
    os.chmod(path, 0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(ByteStoreRefusal, match="HASH_MISMATCH"):
        store.get_bytes(digest, grant=HOST_BEARER_GRANT)
    with pytest.raises(ByteStoreRefusal, match="HASH_MISMATCH"):
        store.put_bytes(b"payload", grant=HOST_BEARER_GRANT)  # stored copy disagrees: refused
    with pytest.raises(ByteStoreRefusal, match="MISSING"):
        store.get_bytes("0" * 64, grant=HOST_BEARER_GRANT)
    with pytest.raises(ByteStoreRefusal, match="NOT_A_SHA256"):
        store.get_bytes("../etc", grant=HOST_BEARER_GRANT)
    with pytest.raises(ByteStoreRefusal, match="GRANT_REFUSED"):
        store.get_bytes(digest, grant="someone-else")


def test_object_routes_require_the_token(client):
    digest = hashlib.sha256(b"x").hexdigest()
    assert client.put(f"/api/v1/objects/{digest}", data=b"x").status_code == 401
    assert client.get(f"/api/v1/objects/{digest}").status_code == 401


def test_object_routes_put_get_and_refusals(client):
    data = b'{"schema":"doin.external_payload_body.v1"}'
    digest = hashlib.sha256(data).hexdigest()
    first = client.put(f"/api/v1/objects/{digest}", data=data, headers=_auth())
    assert first.status_code == 201 and first.get_json() == {"digest": digest, "size": len(data), "stored": True}
    again = client.put(f"/api/v1/objects/{digest}", data=data, headers=_auth())
    assert again.status_code == 200 and again.get_json()["stored"] is False
    got = client.get(f"/api/v1/objects/{digest}", headers=_auth())
    assert got.status_code == 200 and got.data == data
    assert got.headers["X-Content-SHA256"] == digest
    wrong = client.put(f"/api/v1/objects/{'a' * 64}", data=data, headers=_auth())
    assert wrong.status_code == 400 and "HASH_MISMATCH" in wrong.get_json()["error"]
    assert client.get(f"/api/v1/objects/{'b' * 64}", headers=_auth()).status_code == 404
    assert client.get("/api/v1/objects/not-a-digest", headers=_auth()).status_code == 400


def test_object_routes_are_422_when_not_declared(tmp_path):
    from data_lake_service.testing.memory_store import backend as memory_backend

    app = create_app({"service_token": TOKEN}, memory_backend(), {})
    client = app.test_client()
    digest = hashlib.sha256(b"x").hexdigest()
    assert client.put(f"/api/v1/objects/{digest}", data=b"x", headers=_auth()).status_code == 422
    assert client.get(f"/api/v1/objects/{digest}", headers=_auth()).status_code == 422
