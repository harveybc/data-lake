# AGENTS.md — data-lake

Guidance for AI coding agents working in this repository. See [agents.md](https://agents.md).

## Project overview

`data-lake` is a **host**: it serves the lake HTTP contract and resolves the store behind
it from a Python entry point. It contains no data, no market or financial knowledge, no
schema and no governance decision. Policy, deliveries, receipts and accounting live in
[data-gov](https://github.com/harveybc/data-gov); the data lives in a *provider*
distribution such as `financial-data-store`.

It is not a database, not a scheduler and not a governance kernel. If a change would teach
this repository what a particular dataset means, it belongs in a provider instead.

## Quickstart

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install .
python -m data_lake_service.main --load_config examples/config/memory_demo.json --print-identity
python -m data_lake_service.main --load_config examples/config/memory_demo.json
curl -H "Authorization: Bearer $DATA_GOV_LAKE_TOKEN" http://127.0.0.1:5068/api/v1/discover
```

`examples/config/memory_demo.json` uses `memory_store`, the disposable provider shipped
with the host, so a fresh install serves something without any other distribution. It is a
demo and never production data. `examples/config/financial_files.json` is the real shape,
and needs `financial-data-store` installed:

```bash
pip install "git+https://github.com/harveybc/financial-data.git#subdirectory=store"
```

## Tests

```bash
python -m pytest tests -q -m "not packaging"   # unit + HTTP contract
python -m pytest tests -q                      # adds a real install into a throwaway venv
```

The `packaging` tests build the host and `tests/fixtures/example_store` as separate
distributions, install both into a temporary virtual environment and resolve the provider
through the CLI. Discovery tested only against a fabricated entry-point list proves nothing
about a wheel; keep those tests real.

`tools/compare_with_legacy_host.py` compares this host against the financial host it
replaces, over a disposable data root — status, body bytes and every header the governance
kernel reads. See `docs/PARITY.md`.

## Layout

| Path | Purpose |
|---|---|
| `data_lake_service/web.py` | the HTTP contract: routes, status codes, delivery and availability headers |
| `data_lake_service/backends.py` | the backend interface and the capability vocabulary |
| `data_lake_service/discovery.py` | entry-point resolution, refusals and the identity recorded |
| `data_lake_service/config.py` | host configuration; provider settings pass through opaquely |
| `data_lake_service/auth.py` | bearer check against the governance kernel's service token |
| `data_lake_service/testing/` | the disposable in-memory provider used by the host's own tests |
| `tests/fixtures/example_store/` | a provider packaged on its own, for the installation tests |
| `tools/` | the legacy/new parity harness |

## Conventions and constraints

- **The contract is not ours to change.** data-gov's `lake_plugins/http_lake.py` reads
  these routes and headers. Changing a status code or a header name breaks every governed
  consumer; if one must change, change it there first, with its tests.
- **A capability is declared, never assumed.** A backend lists what it supports; anything
  else answers 422. Do not add a fallback that approximates a missing operation.
- **A refusal is a refusal; a defect is a defect.** Providers are separate distributions,
  so their exception classes are their own. `errors.classify` maps refusal kinds and
  re-raises what it cannot classify. Never widen it into a catch-all that turns a bug into
  a polite 403.
- **No data-specific defaults.** Roots, globs, contracts and time columns belong to the
  provider's `settings`, which the host hashes and passes through without interpreting.
- **Provenance is recorded, not trusted.** The host records the distribution, version,
  module, settings digest and the provider's own source identity; it never installs code
  named in JSON.

## Do not touch

- **Running services.** Deployments of this host and of the adapters it replaces may be
  serving live governed traffic. Do not start, stop or restart them as part of a change.
- **Production data roots.** Tests use temporary directories. Never point a test
  configuration at a real data root, and never write into one.
- **Secrets.** No tokens, machine names, private paths or account identifiers in this
  repository. `DATA_GOV_LAKE_TOKEN` comes from the environment or a token file.
