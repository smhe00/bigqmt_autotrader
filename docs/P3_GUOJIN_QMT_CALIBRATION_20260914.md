# P3 Guojin QMT Read-Only Calibration — 2026-09-14

Target terminal: **Guojin QMT 2.1.19.0**

QMT built-in runtime observed: **CPython 3.6.8**

Current Guojin adapter: `qmt_side/BIGQMT_EXECUTION_BRIDGE_V04.py`

Current bridge build after calibration hardening: `p3-file-spool-2`

## Result

**QMT-SIDE READ-ONLY PATH: PASS**

Real Guojin model-trading calibration has now confirmed the built-in lifecycle, account binding, active queries, callback subscription, ACCOUNT callback delivery, and durable file-spool publication without broker mutation calls.

### Latest active-query snapshot

The latest real run produced:

- `ACCOUNT`: 1 row;
- `POSITION`: 8 rows;
- `ORDER`: 1 row;
- `DEAL`: 2 rows;
- `query_errors`: empty;
- `dropped_events`: 0;
- `transport_failures`: 0;
- file-spool publication successful.

The account identifier was emitted only as a SHA-256 fingerprint; no raw account ID was logged.

Observed normalized ACCOUNT fields:

- `available_cash`
- `balance`
- `instrument_value`
- `status`
- `stock_value`
- `trading_date`

Observed normalized POSITION fields:

- `frozen_quantity`
- `last_price`
- `market_value`
- `on_road_quantity`
- `open_price`
- `quantity`
- `sellable_quantity`
- `symbol`
- `trading_day`

Observed normalized ORDER fields from a real row:

- `average_fill_price`
- `broker_order_id`
- `cancel_info`
- `cancelled_quantity`
- `error_code`
- `filled_quantity`
- `insert_date`
- `insert_time`
- `limit_price`
- `operation`
- `order_ref`
- `original_quantity`
- `remaining_quantity`
- `remark`
- `status_code`
- `submit_status_code`
- `symbol`

Observed normalized DEAL fields from real rows:

- `broker_order_id`
- `commission`
- `operation`
- `order_ref`
- `price`
- `quantity`
- `remark`
- `symbol`
- `trade_amount`
- `trade_date`
- `trade_id`
- `trade_time`

These observations prove field availability and normalization shape on this broker build. They do **not** yet prove the semantic mapping of Guojin ORDER status codes to canonical OMS `OrderStatus`; that mapping remains fail-closed.

## Lifecycle and callback calibration

The model-trading run confirmed:

- top-level module code executes before account globals are injected;
- `init(ContextInfo)` later receives usable model-trading account bindings;
- `ContextInfo.set_account(account)` succeeds;
- callback subscription reports true;
- `handlebar(ContextInfo)` executes in the normal model-trading lifecycle;
- QMT explicitly reports `start simulation mode`;
- ACCOUNT callbacks are delivered on this installation.

The observed ACCOUNT callback cadence was approximately every five seconds even after market close. Repeated payloads are therefore noise-prone. The bridge now performs content-based ACCOUNT callback deduplication: changed account state is emitted immediately, identical callbacks are suppressed, and an identical heartbeat may be retained only after 300 seconds if no newer full snapshot already refreshed the account state.

The Python 3.12 Host independently marks repeated ACCOUNT facts as semantic duplicates while still advancing protocol sequence/timestamp state. This second layer is defensive and does not hide sequence gaps.

## File-spool calibration

The calibrated Guojin built-in runtime cannot load the `_socket` extension, so TCP is not the production path. The V04 bridge successfully initializes the durable local file spool and publishes events with zero transport failures.

The bridge and Host now both log their fully resolved spool root/inbox path. This makes it possible to verify directly that QMT and `python -m bigqmt_autotrader.qmt.host` are using the same directory. `BIGQMT_SPOOL_DIR` or Host `--spool-dir` can be used to pin an explicit production path.

## What this proves

The following P3 assumptions are calibrated against the real Guojin terminal:

1. QMT built-in Python is 3.6.8 on this installation.
2. The model-trading lifecycle supports top-level module execution plus `init` / `handlebar`.
3. Model-trading account context exposes the account binding required by the adapter.
4. `get_trade_detail_data()` returns ACCOUNT, POSITION, ORDER, and DEAL facts without mutation calls.
5. The current normalizers extract real ACCOUNT, POSITION, ORDER, and DEAL rows on this build.
6. `ContextInfo.set_account(account)` succeeds and ACCOUNT callback delivery is observed.
7. File-spool initialization and event publication succeed with no observed transport failure.
8. Safe logging does not expose the raw account ID or financial values.
9. No query errors occurred in the successful snapshot.

## Still unverified / pending calibration

P3 is not yet fully gated because the following remain:

- real Python 3.12 Host consumption of this exact Guojin spool run;
- reconnect/restart behavior across QMT and Host processes;
- POSITION callback delivery calibration;
- ORDER callback delivery calibration;
- DEAL callback delivery calibration;
- Guojin ORDER `status_code` / `submit_status_code` semantic mapping;
- durable `remark` / broker-token correlation to OMS `client_order_id` on real rows;
- ORDER/DEAL evidence ingestion into OMS reconciliation after the mapper is explicitly calibrated.

No real order submission or cancellation was invoked or authorized.

## P3 next step

Run `python -m bigqmt_autotrader.qmt.host` against the same resolved spool directory shown in the QMT `bridge_ready` log and verify `bridge_ready -> snapshot -> callback` ingestion end-to-end. Then calibrate ORDER/DEAL status semantics from observed broker rows before enabling any OMS evidence mapping.

P4 trading mutation capability remains out of scope.