# P3 QMT Read-Only Adapter — Guojin QMT 2.1.19.0

Date: 2026-09-14

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

- module-load environment detection;
- bridge readiness;
- embedded Python version;
- whether callback subscription succeeded;
- snapshot row counts;
- which normalized fields were present;
- query error type names;
- queue depth / dropped-event count.

They do not contain the normalized financial values themselves.

### Module-load diagnostic

The bridge now emits `module_loaded` immediately when QMT executes the source file, before `init()` is required. Its payload includes only:

```text
python_version
account_injected
account_type_injected
query_available
model_lifecycle_entered
```

Interpretation:

- all three injection flags false: ordinary script/editor load, not a usable model-trading account environment;
- account/accountType true but query false: model environment partially injected, QMT build/runtime difference must be calibrated;
- all three true: active read-only query is possible immediately, even before `init()`;
- later `bridge_ready`: `init()` has entered and callback subscription has been attempted.

If all three are true at module load, the bridge performs one read-only `ACCOUNT/POSITION/ORDER/DEAL` snapshot immediately. It still does not subscribe callbacks until `init(ContextInfo)` provides a ContextInfo object.

## Guojin 2.1.19.0 calibration procedure

### A. Editor/load sanity check

1. Replace the strategy source with the latest `qmt_side/BIGQMT_EXECUTION_BRIDGE.py`.
2. Save/compile.
3. If you use the editor's ordinary Run action, expect at least one `BIGQMT_RO_STATUS=...module_loaded...` line.
4. This run is diagnostic only. It is not sufficient to validate P3 model-trading integration.

### B. Model Trading calibration

The official QMT documentation states that live/model strategies must be run from the **Model Trading** interface.

1. Open **Model Trading**.
2. Create/add a strategy-trading instance using this model.
3. Select the normal A-share `STOCK` account using the QMT UI. Do not hard-code the account ID in source.
4. Select a normal main-chart stock, for example `000001.SZ`, and an ordinary period such as `1m` or `1d`.
5. Select **simulation-signal mode** rather than real-trading mode for calibration.
6. Start the model-trading instance.
7. Copy only log lines beginning with `BIGQMT_RO_STATUS=` and return them for review.
8. Stop after `module_loaded` plus either `snapshot`/`top_level_snapshot_ok`, or `bridge_ready` plus `snapshot`, have appeared.

A model-trading run should expose `account` and `accountType`. The documented `handlebar` mechanism is driven by the selected main-chart historical bars and live quote updates.

## Expected output patterns

### Ordinary editor load

Typical diagnostic result:

```text
BIGQMT_RO_STATUS={..."status":"module_loaded"..."account_injected":false...}
```

### Model Trading with globals available before init

Possible result:

```text
BIGQMT_RO_STATUS={..."status":"module_loaded"..."account_injected":true..."query_available":true...}
BIGQMT_RO_STATUS={..."status":"snapshot"...}
BIGQMT_RO_STATUS={..."status":"top_level_snapshot_ok"...}
```

### Full model lifecycle

Once `init()` runs, expect additionally:

```text
BIGQMT_RO_STATUS={..."status":"bridge_ready"...}
```

`bridge_ready` reports:

- Python runtime version;
- `callback_subscription: true` if `ContextInfo.set_account(account)` succeeds;
- read-only capabilities;
- `trading_enabled: false`.

`snapshot` reports row counts and normalized field names for the four query families.

## Fail-closed behavior

If account binding, `set_account`, or a query fails, the adapter emits only a safe error code and Python exception **type**, not exception text. This avoids leaking local paths, account IDs, or terminal details into logs.

Examples include:

- `ACCOUNT_BINDING_UNAVAILABLE`;
- `SET_ACCOUNT_UNAVAILABLE`;
- `SET_ACCOUNT_FAILED`;
- `INITIAL_SNAPSHOT_FAILED`;
- `TOP_LEVEL_SNAPSHOT_FAILED`;
- per-query `query_errors` entries with `data_type` and `error_type` only.

## P3 exit boundary

This file alone does **not** complete P3. P3 remains IN PROGRESS until:

1. Guojin QMT 2.1.19.0 runtime and field behavior are calibrated;
2. the host-side localhost transport / ingestion path is implemented;
3. callback + active-query facts flow into the host reconciliation path;
4. reconnect/startup behavior is tested;
5. no-trading/mutation static gates remain green.

P4 real limit-order/cancel capability remains out of scope and requires a separate gate.
