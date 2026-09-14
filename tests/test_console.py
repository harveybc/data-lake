"""The operator console: what it shows, what it refuses, and what saving actually does.

The rule under test is the one the governance stack already applies to data-gov's console:
a pending file is not an authorization and not a deployment. The console may prepare a
configuration; only the service's own configuration load activates it.
"""

from __future__ import annotations

import json

import pytest

from data_lake_service.config import load
from data_lake_service.operator_config import editable_config, pending_config, write_pending
from data_lake_service.testing.memory_store import MemoryStore
from data_lake_service.web import create_app

TOKEN = "console-token"
SECRET = "do-not-render-this"
BODY = "time,value\n2024-01-01,1\n"
CONTRACT = {"event_time_column": "time", "available_time_column": "time",
            "timezone": "NAIVE_WALL_CLOCK", "time_unit": None, "frequency": "1d"}


@pytest.fixture()
def app(tmp_path):
    backend = MemoryStore()
    backend.set_params(store_id="memory", spool_dir=str(tmp_path / "spool"),
                       resources={"prices": {"body": BODY, "rows": [{"time": "2024-01-01", "value": 1}],
                                             "time_column": "time"}})
    config = load(None, {"service_token": SECRET, "store_id": "memory", "title": "console demo",
                         "operator_config_path": str(tmp_path / "pending.json"),
                         "backend": {"entry_point": "memory_store", "distribution": "data-lake-service",
                                     "settings": {"resource_contracts": {"prices": CONTRACT},
                                                  "root_path": "/data/demo"}}})
    application = create_app(config, backend, {"entry_point": "memory_store", "distribution": "data-lake-service",
                                               "version": "0.1.0", "module": "m:backend",
                                               "capabilities": list(backend.capabilities()),
                                               "settings_sha256": "a" * 64, "source_identity": {}})
    application.config.update(TESTING=True)
    return application, config, tmp_path


def test_the_inventory_page_names_the_provider_and_its_resources(app):
    application, _config, _tmp = app
    page = application.test_client().get("/")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "memory" in body and "data-lake-service" in body
    assert "prices" in body
    assert 'name="viewport"' in body and "width=device-width" in body


def test_the_console_never_renders_a_secret(app):
    application, _config, _tmp = app
    for path in ("/", "/settings", "/resource?resource=prices"):
        body = application.test_client().get(path).get_data(as_text=True)
        assert SECRET not in body, path


def test_the_resource_page_shows_coverage_and_the_producer_contract(app):
    application, _config, _tmp = app
    body = application.test_client().get("/resource?resource=prices").get_data(as_text=True)
    assert "event_time_column" in body and "2024-01-01" in body


def test_a_resource_without_a_contract_says_so_instead_of_implying_one(app):
    application, config, _tmp = app
    config["backend"]["settings"]["resource_contracts"] = {}
    body = application.test_client().get("/resource?resource=prices").get_data(as_text=True)
    assert "declares no availability contract" in body


def test_saving_writes_a_pending_file_and_changes_nothing_active(app):
    application, config, tmp_path = app
    before = json.dumps(config, sort_keys=True, default=str)
    proposal = editable_config(config)
    proposal["web_port"] = 5099
    response = application.test_client().post("/settings", data={"configuration": json.dumps(proposal)})
    assert response.status_code == 200
    assert "pending" in response.get_data(as_text=True)
    written = json.loads((tmp_path / "pending.json").read_text())
    assert written["web_port"] == 5099
    assert json.dumps(config, sort_keys=True, default=str) == before, "the active configuration moved"


def test_invalid_configuration_is_refused_with_a_reason_and_writes_nothing(app):
    application, _config, tmp_path = app
    client = application.test_client()
    for text, reason in [("{not json", "invalid JSON"),
                         ('{"backend": {}}', "entry_point and distribution"),
                         ('{"backend": {"entry_point": "a", "distribution": "b"}, "web_port": 0}', "port number"),
                         ('{"backend": {"entry_point": "a", "distribution": "b"}, "lakes": []}',
                          "fields this console does not edit")]:
        page = client.post("/settings", data={"configuration": text})
        assert reason in page.get_data(as_text=True), text
    assert not (tmp_path / "pending.json").exists()


def test_a_redacted_value_cannot_be_saved_back(app):
    application, config, tmp_path = app
    config["backend"]["settings"]["service_token"] = SECRET
    proposal = editable_config(config)
    assert proposal["backend"]["settings"]["service_token"] == "<redacted>"
    page = application.test_client().post("/settings", data={"configuration": json.dumps(proposal)})
    assert "redacted" in page.get_data(as_text=True)
    assert not (tmp_path / "pending.json").exists()


def test_the_pending_write_is_atomic(tmp_path):
    destination = tmp_path / "nested" / "pending.json"
    write_pending(destination, {"a": 1})
    assert json.loads(destination.read_text()) == {"a": 1}
    assert not list(destination.parent.glob(".pending-*")), "a temporary file survived"


def test_a_backend_that_cannot_answer_is_reported_not_hidden(tmp_path):
    class Broken(MemoryStore):
        def discover(self):
            raise RuntimeError("inventory unavailable")

    backend = Broken()
    backend.set_params(resources={})
    application = create_app(load(None, {"store_id": "broken"}), backend,
                             {"capabilities": list(backend.capabilities())})
    application.config.update(TESTING=True)
    body = application.test_client().get("/").get_data(as_text=True)
    assert "inventory unavailable" in body


def test_the_editable_projection_keeps_only_what_the_console_edits(app):
    _application, config, _tmp = app
    projected = pending_config(config, json.dumps(editable_config(config)))
    assert set(projected) <= {"backend", "store_id", "title", "description", "kind", "engine",
                              "transport", "web_host", "web_port", "max_downloads",
                              "max_read_rows", "max_span_days"}
    assert "principals" not in projected and "policies" not in projected
