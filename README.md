# data-lake

A reusable **lake host**: the HTTP contract, the configuration, the console surface and the
backend seam. It holds no data, no financial knowledge and no governance decision.

Where the data lives is a separate, independently packaged distribution — a *provider* —
selected by entry point:

```json
{
  "store_id": "financial_files",
  "web_port": 5066,
  "backend": {
    "entry_point": "financial_files",
    "distribution": "financial-data-store",
    "settings": {"root_path": "/data/financial", "include_globs": ["market_data/**/*.csv"]}
  }
}
```

```bash
pip install .                      # the host
pip install ../financial-data/store  # a provider, as its own distribution
python -m data_lake_service.main --load_config host.json --print-identity
python -m data_lake_service.main --load_config host.json
```

`--print-identity` resolves the provider and prints what was resolved (distribution,
version, module, capabilities, the SHA-256 of the settings and the provider's own source
identity) without serving anything.

## What the host guarantees

* **One named distribution or a refusal.** A repository name in configuration is a
  provenance reference, never an import path. The entry point must belong to the
  distribution the configuration names; two distributions offering the same entry-point
  name is a refusal, not a race resolved by order. Nothing is installed or imported from
  JSON. See `data_lake_service/discovery.py` and `tests/test_discovery.py`.
* **The contract consumers already depend on.** Routes, status codes and headers are those
  of the financial host this was ported from, because data-gov's `lake_plugins/http_lake.py`
  reads them: `X-Content-SHA256`, `X-Source-SHA256`, `X-Delivery`, `X-Time-Column` and, for
  a governed delivery, `X-Availability-Contract-SHA256` plus the three availability headers.
* **No invented capability.** A backend declares what it supports; anything else is 422.
  A warehouse's query route does not exist here, and this host will not fabricate one.
* **A refusal is a refusal, a defect is a defect.** A provider is packaged separately, so
  its exception classes are its own; the host classifies the refusal kind (or by an explicit
  `refusal` attribute) and re-raises what it cannot classify instead of serving a 500 as a
  polite 403 — or the reverse, which is what the first parity run actually found.

## Tests

```bash
python -m pytest tests -q -m "not packaging"   # unit and contract tests
python -m pytest tests -q                      # adds a real install into a throwaway venv
python tools/compare_with_legacy_host.py --help  # the legacy/new parity harness
```

`tests/fixtures/example_store` is a provider packaged on its own, installed into a
throwaway virtual environment so that discovery is proven through a real installation
rather than a fabricated entry-point list.

## Status

Implemented and proven against a disposable provider and against the installed
`financial-data-store`; **not deployed**. The running services are untouched. Migration
sequence and scope exclusions: `data-gov/docs/STORE_PACKAGES_DESIGN.md`.
