"""A disposable provider: bytes held in memory, so the host can be built and tested alone.

It is deliberately not a file lake and not financial: it exists to exercise the contract,
including a governed delivery with a contract identity and an availability scope. Nothing
here is a default for production; a host with this backend serves test data and says so.
"""

from __future__ import annotations

import hashlib
import io
import uuid

from ..backends import LakeBackendBase
from ..errors import HoldoutError, UnsupportedError


class MemoryStore(LakeBackendBase):
    declared_capabilities = ("describe", "storage", "discover", "coverage", "read",
                             "download", "governed_download")
    backend_params = {
        "store_id": "memory",
        "title": "in-memory test store",
        "holdout_start": None,
        "resources": {},          # resource_id -> {"body": bytes|str, "rows": [...], "time_column": str}
        "availability": {"label": "WINDOW_END", "completion_lag_max": "1h",
                         "timezone_evidence": "PRODUCER_STATEMENT", "use_class": "OFFLINE_DAY_GRANULAR"},
        "spool_dir": None,
    }

    def source_identity(self):
        return {"kind": "in_repository", "module": __name__, "distribution": "data-lake-service"}

    def _resource(self, resource_id):
        resources = self.params.get("resources") or {}
        if resource_id not in resources:
            raise FileNotFoundError(f"unknown resource {resource_id!r}")
        return resources[resource_id]

    def _body(self, resource_id):
        body = self._resource(resource_id).get("body") or b""
        return body.encode() if isinstance(body, str) else bytes(body)

    def _contract_sha256(self, resource_id):
        scope = self.params.get("availability") or {}
        payload = f"{resource_id}|" + "|".join(f"{k}={scope.get(k)}" for k in sorted(scope))
        return hashlib.sha256(payload.encode()).hexdigest()

    # -- operations ----------------------------------------------------
    def describe(self):
        return {"lake_id": self.params.get("store_id"), "title": self.params.get("title"),
                "description": "disposable in-memory store", "kind": "lake",
                "engine": "memory", "transport": "http",
                "root_path": "memory://", "resources": len(self.params.get("resources") or {})}

    def storage(self):
        total = sum(len(self._body(r)) for r in (self.params.get("resources") or {}))
        return {"host_total": 0, "host_used": 0, "host_free": 0, "lake_bytes": total, "root": "memory://"}

    def discover(self):
        out = []
        for resource_id, spec in (self.params.get("resources") or {}).items():
            body = self._body(resource_id)
            out.append({"resource_id": resource_id, "bytes": len(body),
                        "time_column": spec.get("time_column") or "",
                        "sha256": hashlib.sha256(body).hexdigest()})
        return out

    def coverage(self, resource_id):
        spec = self._resource(resource_id)
        days = sorted({str(row.get(spec.get("time_column") or "time"))[:10] for row in (spec.get("rows") or [])})
        return {"resource_id": resource_id, "first_day": days[0] if days else None,
                "last_day": days[-1] if days else None, "days": len(days)}

    def read(self, resource_id, start=None, end=None):
        spec = self._resource(resource_id)
        column = spec.get("time_column") or "time"
        rows = [r for r in (spec.get("rows") or [])
                if (start is None or str(r.get(column))[:10] >= start)
                and (end is None or str(r.get(column))[:10] <= end)]
        return {"resource_id": resource_id, "time_column": column, "rows": rows}

    def _deliver(self, resource_id, start, end):
        spec = self._resource(resource_id)
        holdout = self.params.get("holdout_start")
        if holdout and end and str(end) >= str(holdout)[:10]:
            raise HoldoutError("holdout")
        body = self._body(resource_id)
        return spec, body

    def download(self, resource_id, start=None, end=None):
        spec, body = self._deliver(resource_id, start, end)
        spool = self.params.get("spool_dir")
        if not spool:
            raise UnsupportedError("this store needs a spool_dir to serve an ungoverned download")
        from pathlib import Path

        path = Path(spool)
        path.mkdir(parents=True, exist_ok=True)
        part = path / f"{uuid.uuid4().hex}.part"
        part.write_bytes(body)
        return {"path": str(part), "filename": f"{resource_id}.csv", "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "source_sha256": hashlib.sha256(self._body(resource_id)).hexdigest(),
                "delivery": "MEMORY", "time_column": spec.get("time_column") or ""}

    def governed_download(self, resource_id, start=None, end=None):
        spec, body = self._deliver(resource_id, start, end)
        return {"handle": io.BytesIO(body), "filename": f"{resource_id}.csv", "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "source_sha256": hashlib.sha256(self._body(resource_id)).hexdigest(),
                "delivery": "MEMORY", "time_column": spec.get("time_column") or "",
                "availability_contract_sha256": self._contract_sha256(resource_id),
                "availability": dict(self.params.get("availability") or {})}

    def is_spool(self, path) -> bool:
        spool = self.params.get("spool_dir")
        return bool(spool) and str(path).startswith(str(spool))


def backend():
    return MemoryStore()
