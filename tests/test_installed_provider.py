"""Discovery through a real installation, not a fabricated entry-point list.

Design step 3 ("test plugin discovery in installed wheels") is only honest if a provider
is packaged and installed separately from the host. This builds a wheel of the fixture in
`tests/fixtures/example_store`, installs it with the host into a throwaway virtual
environment, and resolves it through the CLI. It is slow and network-free; deselect with
`-m "not packaging"` when iterating.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "example_store"

pytestmark = pytest.mark.packaging


def _run(*argv, **kwargs):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=900, **kwargs)
    assert proc.returncode == 0, f"{argv}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return proc


@pytest.fixture(scope="module")
def venv(tmp_path_factory):
    root = tmp_path_factory.mktemp("venv")
    _run(sys.executable, "-m", "venv", "--system-site-packages", str(root))
    python = root / "bin" / "python"
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_NO_BUILD_ISOLATION="1")
    _run(str(python), "-m", "pip", "install", "--no-deps", "-q", str(REPO), env=env)
    _run(str(python), "-m", "pip", "install", "--no-deps", "-q", str(FIXTURE), env=env)
    return python


def test_the_installed_provider_is_resolved_by_name_and_distribution(venv, tmp_path):
    config = tmp_path / "host.json"
    config.write_text(json.dumps({
        "store_id": "example", "backend": {"entry_point": "example_files",
                                           "distribution": "example-lake-store",
                                           "settings": {"greeting": "governed"}}}))
    proc = _run(str(venv), "-m", "data_lake_service.main", "--load_config", str(config), "--print-identity")
    identity = json.loads(proc.stdout)
    assert identity["distribution"] == "example-lake-store"
    assert identity["version"] == "0.3.1"
    assert identity["module"] == "example_store.provider:backend"
    assert identity["capabilities"] == ["describe", "discover", "governed_download"]
    assert identity["source_identity"]["kind"] == "packaged_fixture"
    assert len(identity["settings_sha256"]) == 64


def test_the_wrong_distribution_name_is_refused_after_a_real_install(venv, tmp_path):
    config = tmp_path / "wrong.json"
    config.write_text(json.dumps({"backend": {"entry_point": "example_files",
                                              "distribution": "financial-data-store"}}))
    proc = subprocess.run([str(venv), "-m", "data_lake_service.main", "--load_config", str(config),
                           "--print-identity"], capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0
    assert "belongs to distribution 'example-lake-store'" in (proc.stderr + proc.stdout)


def test_an_uninstalled_provider_is_refused_after_a_real_install(venv, tmp_path):
    config = tmp_path / "absent.json"
    config.write_text(json.dumps({"backend": {"entry_point": "financial_files",
                                              "distribution": "financial-data-store"}}))
    proc = subprocess.run([str(venv), "-m", "data_lake_service.main", "--load_config", str(config),
                           "--print-identity"], capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0
    assert "no installed distribution registers" in (proc.stderr + proc.stdout)
