# P3 Guojin QMT Read-Only Calibration — 2026-09-14

Target terminal: **Guojin QMT 2.1.19.0**

QMT built-in runtime observed: **CPython 3.6.8**

Adapter: `qmt_side/BIGQMT_EXECUTION_BRIDGE.py`

## Result

**ACTIVE-QUERY PATH: PASS**

A real Guojin model-trading calibration run produced a successful read-only `snapshot` with:

- `ACCOUNT`: 1 row;
- `POSITION`: 2 rows;
- `ORDER`: 0 rows;
- `DEAL`: 0 rows;
- `query_errors`: empty;
- `dropped_events`: 0.

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

ORDER and DEAL field schemas were not observed because the account had no rows in those query families during this calibration run.

## Lifecycle calibration

A separate minimal model-trading sanity strategy confirmed that Guojin QMT 2.1.19.0 enters the normal built-in-Python lifecycle:

- top-level module code executes;
- `init(ContextInfo)` executes;
- `handlebar(ContextInfo)` executes repeatedly over main-chart bars.

The model-trading log explicitly reported `start simulation mode` before the lifecycle callbacks.

## What this proves

The following P3 assumptions are now calibrated against the real Guojin terminal:

1. QMT built-in Python is 3.6.8 on this installation.
2. The model-trading lifecycle supports `init` / `handlebar`.
3. Model-trading account context can expose the account binding required by the adapter.
4. `get_trade_detail_data()` can return ACCOUNT and POSITION facts without mutation calls.
5. The current normalizers successfully extract the required ACCOUNT and POSITION fields on this build.
6. Safe logging works without emitting raw account IDs or financial values.
7. No query errors occurred in the successful snapshot.

## Still unverified

This calibration does **not** yet prove:

- `ContextInfo.set_account(account)` callback subscription on this exact run;
- `account_callback`, `position_callback`, `order_callback`, `deal_callback` delivery;
- ORDER field normalization with real order rows;
- DEAL field normalization with real deal rows;
- reconnect/restart behavior;
- localhost transport to the Python 3.12 host;
- host ingestion into OMS evidence/reconciliation.

No real order submission or cancellation was invoked or authorized.

## P3 next step

Proceed with host-side localhost transport and ingestion for the already-calibrated snapshot envelope, while keeping callback evidence as an independent pending calibration item. The host must continue to treat missing or ambiguous broker facts fail-closed.

P4 trading mutation capability remains out of scope.
