#!/usr/bin/env python3
"""Design step 6: the same fixture through the legacy financial host and the new lake host.

Both hosts serve the same disposable data root and the same producer contract. Nothing
production is touched: a temporary root, temporary spool/cuts directories, ports given on
the command line, and both processes are stopped at the end.

What is compared: status code, body bytes and every header the governance kernel reads.
A difference is reported, never explained away; identity fields that must differ (the
store id and the host's own metadata) are compared separately and listed as `declared`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = "parity-lake-token"
RESOURCE = "market_data/a.csv"
CONTRACT = {"event_time_column": "event_time", "available_time_column": "available_at",
            "timezone": "NAIVE_WALL_CLOCK", "time_unit": None, "frequency": "1d",
            "availability": {"label": "WINDOW_END", "completion_lag_max": "1h",
                             "timezone_evidence": "PRODUCER_STATEMENT",
                             "use_class": "OFFLINE_DAY_GRANULAR"}}
BODY = ("event_time,available_at,value\n"
        "2024-12-28,2024-12-29,1\n"
        "2024-12-29,2024-12-30,2\n"
        "2024-12-30,2025-01-02,3\n")

READ_HEADERS = ("X-Content-SHA256", "X-Source-SHA256", "X-Delivery", "X-Time-Column",
                "X-Availability-Contract-SHA256", "X-Availability-Label",
                "X-Availability-Completion-Lag-Max", "X-Timezone-Evidence",
                "X-Availability-Use", "Content-Disposition", "Content-Length")

ROUTES = [("describe", "/api/v1/describe", {}),
          ("storage", "/api/v1/storage", {}),
          ("discover", "/api/v1/discover", {}),
          ("coverage", "/api/v1/coverage", {"resource": RESOURCE}),
          ("read", "/api/v1/read", {"resource": RESOURCE, "from": "2024-12-28", "to": "2024-12-30"}),
          ("download", "/api/v1/download", {"resource": RESOURCE}),
          ("governed_download", "/api/v2/download", {"resource": RESOURCE,
                                                     "from": "2024-12-28", "to": "2024-12-30"}),
          ("download_holdout", "/api/v2/download", {"resource": RESOURCE,
                                                    "from": "2024-12-30", "to": "2025-01-05"}),
          ("unknown_resource", "/api/v1/coverage", {"resource": "market_data/absent.csv"}),
          ("bad_range", "/api/v1/download", {"resource": RESOURCE, "from": "nope", "to": "2024-12-30"})]

#: Routes whose body legitimately names the host's own identity rather than the data.
IDENTITY_ROUTES = {"describe", "storage"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fixture(root: Path) -> Path:
    source = root / RESOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(BODY, encoding="utf-8")
    return source


def request(port: int, path: str, params: dict) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    if params:
        from urllib.parse import urlencode

        url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as handle:
            body = handle.read()
            headers = {k: handle.headers.get(k) for k in READ_HEADERS if handle.headers.get(k) is not None}
            return {"status": handle.status, "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body), "headers": headers,
                    "json": _json(body, handle.headers.get("Content-Type"))}
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return {"status": exc.code, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                "headers": {}, "json": _json(body, exc.headers.get("Content-Type"))}


def _json(body: bytes, content_type):
    if content_type and "json" in content_type:
        try:
            return json.loads(body.decode())
        except ValueError:
            return None
    return None


def wait_for(port: int, deadline: float = 40.0):
    start = time.monotonic()
    while time.monotonic() - start < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as handle:
                if handle.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def start(argv, cwd, env, log: Path):
    handle = log.open("wb")
    proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=handle, stderr=subprocess.STDOUT,
                            start_new_session=True)
    return proc, handle


def stop(proc):
    if proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-repo", type=Path, required=True, help="financial-data/lake")
    parser.add_argument("--legacy-python", default=sys.executable)
    parser.add_argument("--new-python", required=True, help="interpreter with the host and provider installed")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    work = args.work
    work.mkdir(parents=True, exist_ok=True)
    root = work / "root"
    fixture(root)
    legacy_port, new_port = free_port(), free_port()
    shared = {"root_path": str(root), "include_globs": ["market_data/**/*.csv"],
              "holdout_start": "2025-01-01", "resource_contracts": {RESOURCE: CONTRACT}}
    legacy_config = work / "legacy.json"
    legacy_config.write_text(json.dumps({**shared, "web_port": legacy_port, "lake_id": "financial_files",
                                         "cuts_dir": str(work / "legacy_cuts"),
                                         "spool_dir": str(work / "legacy_spool")}))
    new_config = work / "new.json"
    new_config.write_text(json.dumps({
        "store_id": "financial_files", "web_port": new_port, "service_token": TOKEN,
        "backend": {"entry_point": "financial_files", "distribution": "financial-data-store",
                    "settings": {**shared, "lake_id": "financial_files",
                                 "cuts_dir": str(work / "new_cuts"),
                                 "spool_dir": str(work / "new_spool")}}}))
    env = dict(os.environ, DATA_GOV_LAKE_TOKEN=TOKEN, OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("PYTHONPATH", None)
    legacy, legacy_log = start([args.legacy_python, "-m", "app.main", "--load_config", str(legacy_config)],
                               args.legacy_repo, env, work / "legacy.log")
    new, new_log = start([args.new_python, "-m", "data_lake_service.main", "--load_config", str(new_config)],
                         work, env, work / "new.log")
    report = {"schema": "lake_host_parity.v1", "resource": RESOURCE, "routes": {},
              "legacy_port": legacy_port, "new_port": new_port}
    try:
        if not wait_for(legacy_port):
            raise SystemExit(f"the legacy host did not start: {(work / 'legacy.log').read_text()[-2000:]}")
        if not wait_for(new_port):
            raise SystemExit(f"the new host did not start: {(work / 'new.log').read_text()[-2000:]}")
        for name, path, params in ROUTES:
            legacy_answer = request(legacy_port, path, params)
            new_answer = request(new_port, path, params)
            comparable = {"status": legacy_answer["status"] == new_answer["status"],
                          "bytes": legacy_answer["sha256"] == new_answer["sha256"],
                          "headers": legacy_answer["headers"] == new_answer["headers"]}
            report["routes"][name] = {
                "path": path, "params": params, "legacy": legacy_answer, "new": new_answer,
                "identical": all(comparable.values()),
                "identity_route": name in IDENTITY_ROUTES,
                "same": comparable}
    finally:
        stop(legacy)
        stop(new)
        legacy_log.close()
        new_log.close()
    data_routes = {k: v for k, v in report["routes"].items() if not v["identity_route"]}
    report["summary"] = {
        "routes_compared": len(report["routes"]),
        "data_routes_identical": sum(1 for v in data_routes.values() if v["identical"]),
        "data_routes": len(data_routes),
        "identity_routes_status_equal": sum(1 for k, v in report["routes"].items()
                                            if v["identity_route"] and v["same"]["status"]),
        "differences": sorted(k for k, v in data_routes.items() if not v["identical"])}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=1))
    return 0 if not report["summary"]["differences"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
