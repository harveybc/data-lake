# Parity with the host this one replaces

`tools/compare_with_legacy_host.py` starts the legacy financial host and this host over the
same disposable data root, the same producer contract and the same availability block, then
compares status, body bytes and every header the governance kernel reads.

Run on 2026-09-14 (`LAKE_HOST_PARITY.json` in the predictor evidence directory):

| | |
|---|---|
| routes compared | 10 |
| data routes identical (status, bytes, headers) | 8 of 8 |
| identity routes (`describe`, `storage`) | status equal; bodies name their own host, as they must |
| differences | none |

The first run of this harness found one, and it was real: the financial provider raises its
own `HoldoutError`, which is not the host's class, so a holdout refusal left the host as a
500 where the legacy host answered 403. The host now classifies refusals structurally
(`data_lake_service/errors.py::classify`) and the case is a regression test.

Beyond route parity, the full Flow v3 campaign was executed through this host with the
provider installed as a separate distribution — campaign, governed delivery, confirmation,
terminal and reconciliation — with the governance configuration unchanged:
`data-gov/tools/verify_flow_v3_e2e.py --new-lake-python … --new-warehouse-python …`.
