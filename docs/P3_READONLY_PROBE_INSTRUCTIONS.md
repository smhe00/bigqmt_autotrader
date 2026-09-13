# P3 Read-Only Probe Instructions — Guojin QMT 2.1.19.0

Date: 2026-09-13

Target: **Guojin Big QMT 2.1.19.0**

Probe: `qmt_side/P3_READONLY_PROBE.py`

## Safety boundary

This probe is read-only. It:

- never calls `passorder`;
- never calls cancel/task-mutation APIs;
- never prints the raw account ID;
- never prints cash, position quantity, order/trade IDs, prices or PnL values;
- never prints exception text or filesystem paths;
- only inspects runtime/API presence and calls `get_trade_detail_data()` for `ACCOUNT`, `POSITION`, `ORDER`, and `DEAL` schema discovery.

The existing execution bridge remains fail-closed. Running the probe does **not** enable trading.

## Run procedure

1. In Guojin QMT 2.1.19.0, create a temporary built-in-Python strategy/model.
2. Paste the complete contents of `qmt_side/P3_READONLY_PROBE.py` into that strategy.
3. Bind the normal A-share stock account to the model in QMT using the normal UI. Do not type the account ID into the source code.
4. Run the strategy in the normal model-trading environment while QMT is already logged in. Do not run it as a historical backtest for this probe.
5. Let it execute through `init` / `after_init` / the first `handlebar`. The probe stops after at most three attempts.
6. In the QMT strategy log, copy **only** lines beginning with:

   `P3_PROBE_JSON=`

7. Send those lines back for P3 field/API calibration.

## Expected output categories

The probe may emit:

- `runtime` — embedded Python version/implementation;
- `capabilities` — presence of read-only and mutation API names (mutation APIs are never invoked);
- `context_schema` — public `ContextInfo` attribute names only;
- `account_binding` — account attribute name, account type, and a one-way truncated SHA-256 identifier instead of the raw account ID;
- `query_schema` — row count and first-object `m_*` field names for `ACCOUNT`, `POSITION`, `ORDER`, `DEAL`;
- callback schema events if QMT naturally delivers account/position/order/deal callbacks during the run.

## If the account is not visible

If the final line is `probe_incomplete` with reason `bound_account_not_visible_after_retries`, stop there and send the probe lines back. Do not add an account ID to the source and do not change QMT settings merely to make the probe pass. The adapter will be adjusted to the actual Guojin build behavior.

## What not to send

Do not send:

- QMT login credentials;
- raw account number;
- passwords/tokens;
- userdata paths;
- screenshots containing account balances or positions;
- the entire QMT application log.

Only the `P3_PROBE_JSON=` lines are required.
