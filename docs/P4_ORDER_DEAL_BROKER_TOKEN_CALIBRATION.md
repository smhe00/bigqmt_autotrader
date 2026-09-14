# P4 ORDER/DEAL + m_strRemark Broker-Token Calibration

## Purpose and safety boundary

This checkpoint validates whether Guojin QMT preserves the deterministic Host `broker_token` in ORDER and DEAL `m_strRemark` fields and records the associated raw status/fill fields. It does not enable trading or translate status codes into OMS lifecycle evidence.

Hard invariants:

- `TRADING_ENABLED=False`
- `live_submit=false`
- `live_cancel=false`
- no real broker mutation API call
- `SHADOW_ACCEPTED != broker ACK`
- ORDER/DEAL events remain quarantined until a separately reviewed status mapping is approved
- an unknown or malformed remark is never matched by symbol, quantity, price, time proximity or row order

## Safe correlation code

`QmtBrokerTokenCalibration` is initialized on the Host and populated only from durable OMS identities:

```python
calibration = QmtBrokerTokenCalibration()
token = calibration.register(account_fingerprint, client_order_id)
ingestion = QmtHostIngestion(calibration_observer=calibration)
```

The observer can classify an existing ORDER/DEAL row or callback as:

- `MATCHED_KNOWN_TOKEN`
- `MISSING_REMARK`
- `MALFORMED_REMARK`
- `UNREGISTERED_TOKEN`
- `ACCOUNT_MISMATCH`

Observation never supplies an `EvidenceMapper`, so the same event remains in semantic quarantine and cannot update OMS order state.

## Runtime calibration procedure

Because V05 cannot create a real order, obtain ORDER/DEAL samples only from an independently authorized manual/simulation action or an already-existing broker record. Do not change V05 and do not ask the Host to submit or cancel.

Read-only report command:

```powershell
python -m bigqmt_autotrader.qmt.calibration_probe `
  --spool-dir D:\BigQMTData\spool `
  --expected-account-fingerprint <sha256:...> `
  --client-order-id <known-durable-client-order-id>
```

The probe reads `processed` and `inbox` without moving, rewriting or deleting files. Add `--include-archives` only when historical archives are intentionally in scope; add `--details` when row-level calibration output is required.

## Current read-only baseline — 2026-09-15

At 2026-09-15 07:40 UTC+08, the probe scanned the current `D:\BigQMTData\spool` without registered order identities:

- 29 event frames across 2 QMT sessions;
- 54 ORDER/DEAL rows, all sourced from snapshots;
- 0 ORDER/DEAL callback rows;
- all 54 rows classified `MISSING_REMARK`;
- `broker_evidence_mapping_enabled=false`;
- `live_submit=false`, `live_cancel=false`.

The repeated historical rows include one ORDER and two DEAL rows with a common broker order ID, but no `m_strRemark`. They cannot prove broker-token preservation and therefore do not advance the calibration Gate.

For every observed ORDER and DEAL record, retain:

- QMT `session_id`, `sequence`, source and timestamp;
- exact `remark` bytes after JSON decoding;
- `broker_order_id`, `order_ref`, `trade_id`;
- ORDER `status_code`, `submit_status_code`, quantities and error/cancel fields;
- DEAL quantity, price and trade time;
- the pre-registered expected broker token and client order ID.

## Acceptance gate before an evidence mapper may exist

All of the following require reviewer approval:

1. Exact token round-trip is observed in both ORDER and DEAL paths for the same broker order.
2. Callback and active-query rows agree on token and broker-order identity.
3. Repeated callbacks and snapshots demonstrate stable identity and dedup behavior.
4. Every relevant raw ORDER status pair is labelled from real observations; no undocumented code is inferred.
5. Partial fill, full fill, rejection, cancellation, and callback-loss/query-recovery paths have fixtures.
6. Unknown token, missing remark, account mismatch, conflicting broker ID, overfill and status regression all fail closed.
7. A code review confirms command results remain separate from broker evidence.

Until all seven pass, `broker_evidence_mapping_enabled` remains false, ORDER/DEAL remain quarantined, and P4 remains SHADOW only.
