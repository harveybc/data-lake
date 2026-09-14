"""The HTTP contract the governance kernel already consumes, served by the new host.

The expectations are taken from data-gov's `lake_plugins/http_lake.py`: the routes it
calls, the status codes it maps and the headers it reads from a delivery.
"""

from __future__ import annotations

import hashlib

import pytest

from data_lake_service.config import load
from data_lake_service.testing.memory_store import MemoryStore
from data_lake_service.web import create_app

TOKEN = "test-token"
BODY = "time,value\n2024-01-01,1\n2024-01-02,2\n"
ROWS = [{"time": "2024-01-01", "value": 1}, {"time": "2024-01-02", "value": 2}]


@pytest.fixture()
def client(tmp_path):
    backend = MemoryStore()
    backend.set_params(store_id="memory", spool_dir=str(tmp_path / "spool"), holdout_start="2025-01-01",
                       resources={"prices": {"body": BODY, "rows": ROWS, "time_column": "time"}})
    config = load(None, {"service_token": TOKEN, "store_id": "memory"})
    app = create_app(config, backend, {"distribution": "data-lake-service", "version": "0.1.0",
                                       "capabilities": list(backend.capabilities())})
    app.config.update(TESTING=True)
    return app.test_client()


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_every_api_route_requires_the_service_token(client):
    for path in ("/api/v1/describe", "/api/v1/storage", "/api/v1/discover", "/api/v1/host",
                 "/api/v1/coverage?resource=prices", "/api/v1/download?resource=prices",
                 "/api/v2/download?resource=prices"):
        assert client.get(path).status_code == 401, path
    assert client.get("/healthz").status_code == 200


def test_describe_discover_and_storage(client):
    described = client.get("/api/v1/describe", headers=auth()).get_json()
    assert described["lake_id"] == "memory" and described["kind"] == "lake"
    resources = client.get("/api/v1/discover", headers=auth()).get_json()["resources"]
    assert [r["resource_id"] for r in resources] == ["prices"]
    assert client.get("/api/v1/storage", headers=auth()).get_json()["lake_bytes"] == len(BODY)


def test_the_host_route_names_the_resolved_provider(client):
    payload = client.get("/api/v1/host", headers=auth()).get_json()
    assert payload["backend"]["distribution"] == "data-lake-service"
    assert payload["kind"] == "lake" and payload["transport"] == "http"


def test_an_unknown_resource_is_404_and_a_bad_range_is_400(client):
    assert client.get("/api/v1/coverage?resource=nope", headers=auth()).status_code == 404
    assert client.get("/api/v1/read?resource=prices&from=2024-01-02&to=2024-01-01",
                      headers=auth()).status_code == 400
    assert client.get("/api/v1/download?resource=prices&from=not-a-day&to=2024-01-02",
                      headers=auth()).status_code == 400


def test_the_holdout_is_a_403_on_read_and_on_a_delivery(client):
    assert client.get("/api/v1/read?resource=prices&from=2024-12-31&to=2025-01-02",
                      headers=auth()).status_code == 403
    assert client.get("/api/v2/download?resource=prices&from=2024-12-31&to=2025-01-02",
                      headers=auth()).status_code == 403


def test_a_governed_delivery_carries_the_headers_the_kernel_reads(client):
    response = client.get("/api/v2/download?resource=prices", headers=auth())
    assert response.status_code == 200
    body = response.get_data()
    assert body == BODY.encode()
    assert response.headers["X-Content-SHA256"] == hashlib.sha256(body).hexdigest()
    assert response.headers["Content-Length"] == str(len(body))
    assert response.headers["X-Delivery"] == "MEMORY"
    assert response.headers["X-Time-Column"] == "time"
    assert len(response.headers["X-Availability-Contract-SHA256"]) == 64
    assert response.headers["X-Availability-Label"] == "WINDOW_END"
    assert response.headers["X-Availability-Completion-Lag-Max"] == "1h"
    assert response.headers["X-Timezone-Evidence"] == "PRODUCER_STATEMENT"
    assert response.headers["X-Availability-Use"] == "OFFLINE_DAY_GRANULAR"
    assert 'filename="prices.csv"' in response.headers["Content-Disposition"]


def test_an_ungoverned_delivery_keeps_the_v1_headers(client):
    response = client.get("/api/v1/download?resource=prices", headers=auth())
    assert response.status_code == 200
    assert response.get_data() == BODY.encode()
    assert response.headers["X-Content-SHA256"] == hashlib.sha256(BODY.encode()).hexdigest()


def test_the_download_slots_are_returned_after_every_delivery(client):
    """Two slots; a consumer that reads and closes each body may deliver indefinitely."""
    for _ in range(5):
        for path in ("/api/v2/download?resource=prices", "/api/v1/download?resource=prices"):
            response = client.get(path, headers=auth())
            assert response.status_code == 200, path
            assert response.get_data() == BODY.encode()
            response.close()


def test_an_undeclared_operation_is_422_not_an_invented_answer(tmp_path):
    class NoDownloads(MemoryStore):
        declared_capabilities = ("describe", "discover")

    backend = NoDownloads()
    backend.set_params(resources={"prices": {"body": BODY, "rows": ROWS, "time_column": "time"}})
    app = create_app(load(None, {"service_token": TOKEN}), backend,
                     {"capabilities": list(backend.capabilities())})
    app.config.update(TESTING=True)
    client = app.test_client()
    assert client.get("/api/v2/download?resource=prices", headers=auth()).status_code == 422
    assert client.get("/api/v1/query?sql=select+1", headers=auth()).status_code == 404
    assert client.get("/api/v1/describe", headers=auth()).status_code == 200


def test_a_providers_own_exception_classes_are_classified_not_missed(tmp_path):
    """A provider is packaged separately: its HoldoutError is not this module's HoldoutError.

    Found by the legacy/new parity run on 2026-09-14: the financial provider's own
    `HoldoutError` escaped the host and became a 500 where the legacy host answered 403.
    """
    class ProviderHoldout(RuntimeError):
        pass

    class ProviderRefusal(RuntimeError):
        refusal = "UNSUPPORTED"

    ProviderHoldout.__name__ = "HoldoutError"

    class Foreign(MemoryStore):
        def governed_download(self, resource_id, start=None, end=None):
            raise ProviderHoldout("holdout")

        def coverage(self, resource_id):
            raise ProviderRefusal("no contract for this resource")

        def read(self, resource_id, start=None, end=None):
            raise RuntimeError("a defect, not a refusal")

    backend = Foreign()
    backend.set_params(resources={"prices": {"body": BODY, "rows": ROWS, "time_column": "time"}})
    app = create_app(load(None, {"service_token": TOKEN}), backend,
                     {"capabilities": list(backend.capabilities())})
    app.config.update(TESTING=True)
    client = app.test_client()
    assert client.get("/api/v2/download?resource=prices", headers=auth()).status_code == 403
    assert client.get("/api/v1/coverage?resource=prices", headers=auth()).status_code == 422
    with pytest.raises(RuntimeError, match="a defect, not a refusal"):
        client.get("/api/v1/read?resource=prices&from=2024-01-01&to=2024-01-02", headers=auth())
