"""The lake HTTP contract, unchanged from the one data-gov's http_lake already consumes.

What changed against the financial host it is ported from: the data lives behind a
backend resolved from an entry point, and an operation the backend did not declare is
refused with 422 instead of being approximated. The routes, status codes and headers —
including `X-Content-SHA256`, `X-Source-SHA256`, `X-Delivery`, `X-Time-Column` and the
four `X-Availability-*` headers — are identical, because consumers depend on them.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
from datetime import date
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request, send_file,
                   url_for)

from .auth import check_bearer, load_token
from .operator_config import editable_config, pending_config, write_pending
from .errors import (REFUSAL_STATUS, HoldoutError, LakeError, UnparseableError,
                     UnsupportedError, classify)

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RETRY_AFTER = "30"


def _day(value):
    if not isinstance(value, str) or not DAY_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _day_range(start, end):
    lo, hi = _day(start), _day(end)
    if lo is None or hi is None or lo > hi:
        return None
    return lo, hi


def _lake_error(exc):
    """Map a backend refusal to the status the governance kernel already maps.

    A provider is packaged separately, so its exception classes are its own; the kind is
    classified rather than matched against this module's identities. An exception the host
    cannot classify is re-raised: a defect must not be served as a refusal.
    """
    kind = classify(exc)
    if kind is None:
        raise exc
    if kind == "HOLDOUT":
        return jsonify({"error": "holdout"}), 403
    if kind == "NOT_FOUND":
        return jsonify({"error": "unknown resource"}), 404
    if kind in ("UNSUPPORTED", "UNPARSEABLE"):
        return jsonify({"error": str(exc)}), REFUSAL_STATUS[kind]
    return jsonify({"error": "invalid from/to"}), 400


class _SlotFile(io.FileIO):
    """The open delivery; closing it returns the download slot exactly once."""

    def __init__(self, path, release):
        self._release = None
        super().__init__(path, "rb")
        self._release = release

    def close(self):
        release, self._release = self._release, None
        try:
            super().close()
        finally:
            if release is not None:
                release()


class _ReleasingHandle:
    """A retained delivery descriptor whose close returns the download slot once.

    send_file answers a retained handle in direct passthrough and the development server
    closes only the file wrapper, so `Response.call_on_close` cannot be the only release
    (observed 2026-09-13 in the financial host: two deliveries exhausted the slots for the
    life of the process).
    """

    def __init__(self, handle, release):
        self._handle = handle
        self._release = release

    def read(self, size=-1):
        return self._handle.read(size)

    @property
    def closed(self):
        return self._handle.closed

    def close(self):
        release, self._release = self._release, None
        try:
            self._handle.close()
        finally:
            if release is not None:
                release()

    def __getattr__(self, name):
        return getattr(self._handle, name)


def _fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def create_app(config: dict, backend, identity: dict | None = None) -> Flask:
    here = Path(__file__).resolve().parent
    app = Flask(__name__, template_folder=str(here / "templates"),
                static_folder=str(here / "static"), static_url_path="/static")
    app.secret_key = config.get("secret_key") or "x"
    identity = dict(identity or {})
    capabilities = set(identity.get("capabilities") or backend.capabilities())
    slots = threading.BoundedSemaphore(int(config.get("max_downloads") or 2))
    max_read_rows = int(config.get("max_read_rows") or 8000)
    max_span_days = int(config.get("max_span_days") or 366)
    if hasattr(backend, "sweep"):
        backend.sweep()

    def _auth():
        if check_bearer(request.headers.get("Authorization"), load_token(config)):
            return None
        return jsonify({"error": "unauthenticated"}), 401

    def _needs(capability):
        if capability in capabilities:
            return None
        return jsonify({"error": f"this store does not support {capability}"}), 422

    @app.get("/healthz")
    def healthz():
        return "ok\n", 200, {"Content-Type": "text/plain"}

    @app.get("/api/v1/host")
    def api_host():
        """What this host is running: kind, transport and the resolved provider identity."""
        denied = _auth()
        if denied:
            return denied
        return jsonify({"kind": config.get("kind") or "lake", "transport": config.get("transport") or "http",
                        "store_id": config.get("store_id"), "backend": identity,
                        "capabilities": sorted(capabilities)})

    @app.get("/api/v1/describe")
    def api_describe():
        denied = _auth() or _needs("describe")
        if denied:
            return denied
        meta = dict(backend.describe())
        meta.setdefault("lake_id", config.get("store_id"))
        meta.setdefault("kind", config.get("kind") or "lake")
        meta.setdefault("transport", config.get("transport") or "http")
        return jsonify(meta)

    @app.get("/api/v1/storage")
    def api_storage():
        denied = _auth() or _needs("storage")
        if denied:
            return denied
        return jsonify(backend.storage())

    @app.get("/api/v1/discover")
    def api_discover():
        denied = _auth() or _needs("discover")
        if denied:
            return denied
        return jsonify({"resources": backend.discover()})

    @app.get("/api/v1/coverage")
    def api_coverage():
        denied = _auth() or _needs("coverage")
        if denied:
            return denied
        try:
            return jsonify(backend.coverage(request.args.get("resource")))
        except Exception as exc:
            return _lake_error(exc)

    @app.get("/api/v1/read")
    def api_read():
        denied = _auth() or _needs("read")
        if denied:
            return denied
        resource = request.args.get("resource")
        start, end = request.args.get("from"), request.args.get("to")
        if not start or not end:
            return jsonify({"error": "from and to are required"}), 400
        days = _day_range(start, end)
        if days is None:
            return jsonify({"error": "invalid from/to"}), 400
        if (days[1] - days[0]).days > max_span_days:
            return jsonify({"error": "date span exceeds limit"}), 400
        holdout = getattr(backend, "params", {}).get("holdout_start")
        if holdout and end >= str(holdout)[:10]:
            return jsonify({"error": "holdout"}), 403
        try:
            payload = backend.read(resource, start=start, end=end)
        except Exception as exc:
            return _lake_error(exc)
        if len(payload.get("rows") or []) > max_read_rows:
            return jsonify({"error": "result too large; narrow the range"}), 400
        return jsonify(payload)

    def _range_or_400():
        start, end = request.args.get("from"), request.args.get("to")
        if (start is not None or end is not None) and _day_range(start, end) is None:
            return None, (jsonify({"error": "invalid from/to"}), 400)
        return (start, end), None

    @app.get("/api/v1/download")
    def api_download():
        denied = _auth() or _needs("download")
        if denied:
            return denied
        bounds, refusal = _range_or_400()
        if refusal:
            return refusal
        start, end = bounds
        resource = request.args.get("resource") or ""
        if not slots.acquire(blocking=False):
            return jsonify({"error": "download slots busy"}), 503, {"Retry-After": RETRY_AFTER}
        try:
            info = backend.download(resource, start=start, end=end)
            handle = _SlotFile(info["path"], slots.release)
        except Exception as exc:
            slots.release()
            return _lake_error(exc)
        except BaseException:
            slots.release()
            raise
        try:
            if backend.is_spool(info["path"]):
                os.unlink(info["path"])
            response = send_file(handle, mimetype="application/octet-stream", as_attachment=True,
                                 download_name=info["filename"], conditional=False, etag=False)
        except BaseException:
            handle.close()
            raise
        return _delivery_headers(response, info)

    @app.get("/api/v2/download")
    def api_governed_download():
        denied = _auth() or _needs("governed_download")
        if denied:
            return denied
        bounds, refusal = _range_or_400()
        if refusal:
            return refusal
        start, end = bounds
        resource = request.args.get("resource") or ""
        if not slots.acquire(blocking=False):
            return jsonify({"error": "download slots busy"}), 503, {"Retry-After": RETRY_AFTER}
        try:
            info = backend.governed_download(resource, start=start, end=end)
            handle = _ReleasingHandle(info["handle"], slots.release)
        except Exception as exc:
            slots.release()
            return _lake_error(exc)
        except BaseException:
            slots.release()
            raise
        try:
            response = send_file(handle, mimetype="application/octet-stream", as_attachment=True,
                                 download_name=info["filename"], conditional=False, etag=False)
            response.call_on_close(handle.close)
        except BaseException:
            handle.close()
            raise
        response = _delivery_headers(response, info)
        contract = str(info.get("availability_contract_sha256") or "")
        if len(contract) != 64:
            raise UnsupportedError("the backend delivered a governed body without a contract identity")
        response.headers["X-Availability-Contract-SHA256"] = contract
        # S2: the canonical contract itself, base64 so it survives a header. A backend that
        # does not publish it is not an error here; downstream the reference simply stays
        # unresolvable, which is reported as UNRESOLVED rather than filled in.
        canonical = info.get("availability_contract_canonical")
        if isinstance(canonical, str) and canonical:
            response.headers["X-Availability-Contract"] = base64.b64encode(
                canonical.encode("ascii")).decode("ascii")
        scope = info.get("availability") or {}
        lag = scope.get("completion_lag_max")
        response.headers["X-Availability-Label"] = str(scope.get("label") or "UNKNOWN")
        response.headers["X-Availability-Completion-Lag-Max"] = "" if lag is None else str(lag)
        response.headers["X-Timezone-Evidence"] = str(scope.get("timezone_evidence") or "UNKNOWN")
        response.headers["X-Availability-Use"] = str(scope.get("use_class") or "UNDECLARED")
        return response

    @app.post("/api/v1/metrics")
    def api_metrics():
        denied = _auth() or _needs("write_metrics")
        if denied:
            return denied
        try:
            return jsonify(backend.write_metrics(request.get_json(silent=True) or {}))
        except Exception as exc:
            return _lake_error(exc)

    def _delivery_headers(response, info):
        quoted = str(info["filename"]).replace("\\", "\\\\").replace('"', '\\"')
        response.headers["Content-Disposition"] = f'attachment; filename="{quoted}"'
        response.headers["Content-Length"] = str(info["bytes"])
        response.headers["X-Content-SHA256"] = info["sha256"]
        response.headers["X-Source-SHA256"] = info.get("source_sha256") or ""
        response.headers["X-Delivery"] = info.get("delivery") or ""
        response.headers["X-Time-Column"] = info.get("time_column") or ""
        return response

    # ---- operator console -------------------------------------------------
    # Read-mostly, on the interface the service already listens on, with no secret ever
    # rendered. Saving writes a *pending* file; activation stays the configuration load.
    def _page_context():
        return {"store_id": config.get("store_id"), "kind": config.get("kind") or "lake",
                "transport": config.get("transport") or "http", "identity": identity,
                "fmt_bytes": _fmt_bytes}

    @app.get("/")
    def console_home():
        meta, resources, storage, error = {}, [], {}, None
        try:
            if "describe" in capabilities:
                meta = backend.describe()
            if "storage" in capabilities:
                storage = backend.storage()
            if "discover" in capabilities:
                resources = backend.discover()
        except Exception as exc:  # the console states the failure instead of showing nothing
            error = f"{type(exc).__name__}: {exc}"
        return render_template("dashboard.html", meta=meta, resources=resources,
                               storage=storage, error=error, **_page_context())

    @app.get("/resource")
    def console_resource():
        resource = request.args.get("resource") or ""
        coverage, error = {}, None
        try:
            if "coverage" in capabilities:
                coverage = backend.coverage(resource)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        settings = (config.get("backend") or {}).get("settings") or {}
        contract = (settings.get("resource_contracts") or {}).get(resource)
        return render_template("resource.html", resource=resource, coverage=coverage,
                               contract=contract, error=error, **_page_context())

    @app.route("/settings", methods=["GET", "POST"])
    def console_settings():
        pending_path = config.get("operator_config_path")
        error = saved = None
        text = json.dumps(editable_config(config), indent=1, sort_keys=True)
        if request.method == "POST":
            text = request.form.get("configuration") or ""
            try:
                proposed = pending_config(config, text)
                if not pending_path:
                    raise ValueError("this service has no operator_config_path, so a pending "
                                     "configuration has nowhere to go")
                write_pending(pending_path, proposed)
                saved = True
            except ValueError as exc:
                error = str(exc)
        return render_template("settings.html", configuration=text, error=error, saved=saved,
                               pending_path=pending_path,
                               pending_exists=bool(pending_path and Path(pending_path).is_file()),
                               **_page_context())

    return app



def serve(config: dict, backend, identity: dict | None = None) -> int:
    app = create_app(config, backend, identity)
    host = config.get("web_host") or "127.0.0.1"
    port = int(config.get("web_port") or 5060)
    print(f"data-lake host ({config.get('store_id')}) → http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    return 0
