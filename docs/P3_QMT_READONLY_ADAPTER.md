# P3 QMT Read-Only Adapter — Guojin QMT 2.1.19.0

Date: 2026-09-13

Target terminal: **Guojin QMT 2.1.19.0**

QMT script: `qmt_side/BIGQMT_EXECUTION_BRIDGE.py`

Host baseline: **CPython 3.12**

QMT-side syntax target: **built-in Python 3.6 compatible**

## Scope

This is the first P3 QMT-side implementation candidate. It is strictly read-only.

It uses the documented QMT built-in-Python contracts:

- model-trading globals `account` and `accountType`;
- `ContextInfo.set_account(account)` for account event subscription;
- `get_trade_detail_data(account, accountType, dataType)` for `account`, `position`, `order`, and `deal` snapshots;
- `account_callback`, `position_callback`, `order_callback`, and `deal_callback` for event evidence.

Official reference root: `https://dict.thinktrader.net/innerApi/`.

## Safety boundary

The P3 adapter:

- does **not** call `passorder`;
- does **not** call `order_lots`;
- does **not** call cancel/task-mutation APIs;
- does **not** use threads, processes or subprocesses;
- does **not** enable live trading;
- leaves `submit_limit_order()` and `cancel_order()` hard-disabled with `E_TRADING_DISABLED`;
- never prints the raw account ID;
- never prints cash balances, position quantities, order IDs, trade IDs, prices or PnL to the QMT log.

The full normalized read-only facts are temporarily retained only in a bounded in-memory queue (`MAX_QUEUED_EVENTS = 512`). The localhost host transport is intentionally deferred until Guojin 2.1.19.0 calibration is complete.

## Normalized facts

### ACCOUNT

The adapter currently normalizes:

- status;
- total balance;
- available cash;
- total instrument value;
- stock market value;
- trading date.

### POSITION

The adapter currently normalizes:

- `symbol` as `instrument.exchange`;
- total quantity;
- sellable quantity;
- frozen quantity;
- on-road quantity;
- market value;
- latest price;
- open/cost price field;
- trading day.

### ORDER

The adapter currently normalizes:

- symbol;
- `m_strOrderRef`;
- `m_strOrderSysID`;
- `m_strRemark`;
- order status / submit status codes;
- original / filled / remaining / cancelled quantity;
- limit price and average fill price;
- insert date/time;
- error code / cancel information;
- operation label.

Status codes are intentionally kept as raw QMT integer codes in P3 until the Guojin build is calibrated. The QMT adapter must not guess terminal-state semantics.

### DEAL

The adapter currently normalizes:

- symbol;
- trade ID;
- order ref / broker order ID;
- remark;
- price / quantity;
- trade date/time;
- commission / trade amount;
- operation label.

## Event envelope

Every queued fact has:

```text
protocol_version
session_id
sequence
timestamp_ms
event_type
source
account_fingerprint
account_type
payload
```

The raw account ID is replaced by:

```text
sha256:<full hex digest>
```

computed from `accountType:account`.

## Safe log format

QMT log messages emitted by the adapter start with:

```text
BIGQMT_RO_STATUS=
```

These log lines contain only safe diagnostics such as:

- bridge readiness;
- embedded Python version;
- whether callback subscription succeeded;
- snapshot row counts;
- which normalized fields were present;
- query error type names;
- queue depth / dropped-event count.

They do not contain the normalized financial values themselves.

## Guojin 2.1.19.0 calibration procedure

1. Open the QMT strategy editor and create a temporary model.
2. Replace the model source with the complete contents of `qmt_side/BIGQMT_EXECUTION_BRIDGE.py`.
3. Save/compile the strategy.
4. In **Model Trading**, add this model and select the normal A-share `STOCK` account using the QMT UI. Do not hard-code the account ID in source.
5. Select a normal main-chart stock, for example `000001.SZ`. The exact symbol is not important for this read-only bridge.
6. Select **simulation-signal mode** rather than real-trading mode for the calibration run. The script itself contains no order mutation calls, but this keeps the terminal-side run mode conservative as well.
7. Start the model.
8. Copy only log lines beginning with `BIGQMT_RO_STATUS=` and return them for review.
9. Stop the model after the initial `bridge_ready` and `snapshot` lines have appeared. On a non-trading day, account/order/position snapshots can still be useful; naturally occurring callbacks are not required for the first calibration.

## Expected first-run output

A successful run should normally produce at least:

```text
BIGQMT_RO_STATUS={..."status":"bridge_ready"...}
BIGQMT_RO_STATUS={..."status":"snapshot"...}
```

`bridge_ready` should report:

- Python runtime version;
- `callback_subscription: true` if `ContextInfo.set_account(account)` succeeds;
- read-only capabilities;
- `trading_enabled: false`.

`snapshot` should report row counts and normalized field names for the four query families.

## Fail-closed behavior

If account binding, `set_account`, or a query fails, the adapter emits only a safe error code and Python exception **type**, not exception text. This avoids leaking local paths, account IDs, or terminal details into logs.

Examples include:

- `ACCOUNT_BINDING_UNAVAILABLE`;
- `SET_ACCOUNT_UNAVAILABLE`;
- `SET_ACCOUNT_FAILED`;
- `INITIAL_SNAPSHOT_FAILED`;
- per-query `query_errors` entries with `data_type` and `error_type` only.

## P3 exit boundary

This file alone does **not** complete P3. P3 remains IN PROGRESS until:

1. Guojin QMT 2.1.19.0 runtime and field behavior are calibrated;
2. the host-side localhost transport / ingestion path is implemented;
3. callback + active-query facts flow into the host reconciliation path;
4. reconnect/startup behavior is tested;
5. no-trading/mutation static gates remain green.

P4 real limit-order/cancel capability remains out of scope and requires a separate gate.
