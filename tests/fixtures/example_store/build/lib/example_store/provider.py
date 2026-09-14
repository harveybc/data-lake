"""An independently packaged provider: its own distribution, its own namespace, no host code."""

from __future__ import annotations

import hashlib
import io


class ExampleStore:
    """Implements the seam by duck typing, without importing the host package."""

    def __init__(self):
        self.params = {"greeting": "hello"}

    def capabilities(self):
        return ("describe", "discover", "governed_download")

    def set_params(self, **settings):
        self.params.update(settings)

    def source_identity(self):
        return {"kind": "packaged_fixture", "distribution": "example-lake-store"}

    def sweep(self):
        return None

    def _body(self):
        return (str(self.params.get("greeting")) + "\n").encode()

    def describe(self):
        return {"lake_id": "example", "title": "example store", "kind": "lake",
                "engine": "fixture", "transport": "http", "root_path": "fixture://"}

    def discover(self):
        body = self._body()
        return [{"resource_id": "greeting", "bytes": len(body),
                 "sha256": hashlib.sha256(body).hexdigest(), "time_column": ""}]

    def governed_download(self, resource_id, start=None, end=None):
        if resource_id != "greeting":
            raise FileNotFoundError(resource_id)
        body = self._body()
        return {"handle": io.BytesIO(body), "filename": "greeting.txt", "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "source_sha256": hashlib.sha256(body).hexdigest(),
                "delivery": "FIXTURE", "time_column": "",
                "availability_contract_sha256": hashlib.sha256(b"example-contract").hexdigest(),
                "availability": {"label": "EVENT_INSTANT", "completion_lag_max": None,
                                 "timezone_evidence": "UNKNOWN", "use_class": "OFFLINE_DAY_GRANULAR"}}

    def is_spool(self, path):
        return False


def backend():
    return ExampleStore()
