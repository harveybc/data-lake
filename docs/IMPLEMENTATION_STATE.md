# Implementation state

This file is the persistent state of the work, updated at every milestone. Chat memory is
not state. Stages and vocabulary come from the work-plan amendment
`predictor/docs/integracion_workplan_2026_09_10/09_ADOPCION_DATA_LAKE_DATA_WAREHOUSE_2026_09_14.md`.

States: `PENDING` | `IMPLEMENTED` | `PROVEN_DISPOSABLE` | `PUBLISHED` | `DEPLOYED` |
`PROVEN_PRODUCTION`.

| stage | criterion | state |
|---|---|---|
| 1. Create | repository with README, AGENTS.md, requirements, tests and persistent state, published at a real URL | `PUBLISHED` — https://github.com/harveybc/data-lake |
| 2. Implement | host installable as a wheel; provider installable from its own repository; discovery proven through a real install | `PROVEN_DISPOSABLE` — `tests/test_installed_provider.py`, and the clone-and-install check in `docs/PARITY.md` |
| 3. Integrate | parity with the adapter it replaces: inventory, bytes, availability, cuts, receipts, outcomes, retries | `PROVEN_DISPOSABLE` — 8/8 data routes identical, `docs/PARITY.md` |
| 4. Interface | AdminLTE configuration and inventory views, resource metadata, desktop and mobile | `PROVEN_DISPOSABLE` — `tests/test_console.py` (10) and `tools/console_screenshots.py`: six pages driven in a real browser at 1440×900 and 390×844, every asset served by this host, zero horizontal overflow; receipt and PNGs in `docs/console/` |
| 5. Put into use | controlled transition over the same data and IDs; governed micro-run through both hosts with exact reconciliation | `PENDING` |
| 6. Adopt | consumer configurations updated; new campaigns use this route by default | `PENDING` |

## Requirements this host must satisfy

1. Serve, unchanged, the routes and headers that data-gov's `lake_plugins/http_lake.py`
   consumes: `/api/v1/describe`, `/storage`, `/discover`, `/coverage`, `/read`,
   `/download`, `/api/v2/download`, `/api/v1/metrics`; `X-Content-SHA256`,
   `X-Source-SHA256`, `X-Delivery`, `X-Time-Column`, `X-Availability-Contract-SHA256`,
   `X-Availability-Label`, `X-Availability-Completion-Lag-Max`, `X-Timezone-Evidence`,
   `X-Availability-Use`.
2. Resolve exactly one installed distribution for the configured entry point, or refuse
   with a named reason; record what was resolved.
3. Refuse an undeclared capability with 422 rather than approximating it.
4. Map a provider's refusal to the status the kernel already maps, and re-raise anything it
   cannot classify.
5. Hold no dataset knowledge: everything data-specific travels in `backend.settings`.

## Acceptance scenarios

| scenario | expected |
|---|---|
| unauthenticated request to any API route | 401 |
| governed delivery of a contracted resource | 200, bytes match `X-Content-SHA256`, 64-hex contract identity, four availability headers |
| range reaching into the holdout | 403 |
| unknown resource | 404 |
| malformed `from`/`to` | 400 |
| operation the backend does not declare | 422 |
| provider raises its own `HoldoutError` | 403, not 500 |
| provider raises an unrelated `RuntimeError` | propagates as a defect, never a refusal |
| console shows a secret | never: values are redacted, and a redacted value cannot be saved back |
| console saves a configuration | a pending file is written atomically; the active configuration does not move |
| two distributions registering the same entry point | startup refusal naming both |
| configured distribution not the owner of the entry point | startup refusal naming the real owner |
| repeated deliveries | download slots returned; no exhaustion after the second |

## Test matrix

| layer | file | what it proves |
|---|---|---|
| discovery | `tests/test_discovery.py` | the resolution rules and every refusal, with the identity recorded |
| contract | `tests/test_http_contract.py` | routes, status codes, headers, slots, capability refusals, foreign exception classes |
| installation | `tests/test_installed_provider.py` | a provider built and installed as a separate wheel, resolved through the CLI |
| console | `tests/test_console.py` | what the console shows, what it refuses, and that saving writes a *pending* file without moving the active configuration |
| browser | `tools/console_screenshots.py` | desktop and mobile rendering, local assets only, no horizontal overflow |
| parity | `tools/compare_with_legacy_host.py` | the legacy adapter and this host answer identically on the same fixture |
| end to end | `data-gov/tools/verify_flow_v3_e2e.py --new-lake-python …` | a full governed campaign through this host |
