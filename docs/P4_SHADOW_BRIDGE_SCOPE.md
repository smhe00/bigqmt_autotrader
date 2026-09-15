# P4 Big QMT Shadow Bridge Scope

## Current state

**P4: SHADOW CODE GATE PASS — round-trip and OMS reconciliation implemented; live broker mutation not implemented.**

The purpose of the first P4 checkpoint is to calibrate the asynchronous execution plumbing against Guojin QMT without creating broker side effects.

## Timing model

The P4 critical path is not the periodic full snapshot:

```text
OMS/Host
  -> durable command spool
  -> QMT command_tick via run_time every 1 second
  -> SHADOW command processing
  -> command_result event
  -> atomic event spool
  -> Host poll every 0.2 second
```

Broker callbacks remain event-driven. A separate 300-second QMT `run_time` task performs full ACCOUNT/POSITION/ORDER/DEAL reconciliation.

## Command protocol

Host commands use command protocol `0.1` and command transport `1`.

Supported types:

- `SUBMIT_LIMIT`
- `CANCEL_ORDER`
- `REQUEST_SNAPSHOT`

Order commands carry:

- account fingerprint only; raw broker account identifiers are forbidden
- durable `client_order_id`
- deterministic broker token `BQ` + 20 SHA-256 hex characters; total length 22, below the calibrated QMT `userOrderId` / `m_strRemark` `<24` boundary
- explicit creation and expiry timestamps
- immutable payload

## Durable command state machine

```text
Host fsync + atomic rename
        |
        v
commands/inbox
        |
        | QMT atomic claim
        v
commands/claimed
   |       |        |
   |       |        +--> malformed/expired -> rejected
   |       |
   |       +--> restart orphan -> unknown (NEVER blindly replay)
   |
   +--> successful SHADOW processing -> processed
```

A command ID may be published again only if the complete serialized frame is identical. Reusing the same command ID with different content is a hard conflict.

## Shadow semantics

`SUBMIT_LIMIT` and `CANCEL_ORDER` currently return:

```text
result_status = SHADOW_ACCEPTED
live_side_effect = false
```

No QMT trading mutation function is called.

`REQUEST_SNAPSHOT` is a real read-only action and returns:

```text
result_status = SNAPSHOT_EMITTED
live_side_effect = false
```

A `command_result` is transport/execution-plane evidence only. It is **not** broker order evidence and cannot promote an OMS order to ACKNOWLEDGED or CANCELLED.

Command results are durably journaled by `QmtCommandResultJournal`, keyed by both `command_id` and QMT `(session_id, sequence)`. Conflicting identity reuse fails closed. For an order already in `UNKNOWN`, `SHADOW_ACCEPTED` may only begin conservative `RECONCILING`; all broker lifecycle selection still requires calibrated ORDER/DEAL callback or query evidence.

## OMS integration

`QmtShadowDriver` publishes a durable command after the OMS has reserved the submit/cancel attempt. A successful publication deliberately raises the existing outcome-unknown signal back to the OMS. A later `SHADOW_ACCEPTED` command result may begin `RECONCILING`, but only calibrated broker callback/query evidence can select a broker lifecycle state.

This prevents `SHADOW_ACCEPTED` from being mistaken for a broker acknowledgement and preserves the existing no-blind-resend recovery model.

The Host composition point is explicit:

```python
QmtHostIngestion(command_result_sink=OmsQmtCommandResultSink(oms))
```

The command-result API does not accept a requested broker status, so there is no execution-plane route to `ACKNOWLEDGED`.

## ORDER/DEAL broker-token calibration layer

`QmtBrokerTokenCalibration` provides a non-mutating observation layer for the next real-QMT calibration:

- register only durable `(account_fingerprint, client_order_id)` identities;
- recompute the deterministic 22-character `BQ...` token locally;
- match only an exact callback/query `remark` value;
- classify missing, malformed, unregistered and cross-account tokens without guessing;
- retain ORDER/DEAL in semantic quarantine because calibration records never become broker evidence.

The detailed runbook and acceptance gate are in `P4_ORDER_DEAL_BROKER_TOKEN_CALIBRATION.md`.

## V05 QMT bridge

Deploy one standalone instance file:

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`

Both are generated from `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05.py` and are:

- Python 3.6 compatible
- execution mode `SHADOW`
- `TRADING_ENABLED=False`
- `live_submit=False`
- `live_cancel=False`
- independent 1-second command timer
- independent 300-second full snapshot timer
- callback events are flushed immediately
- claimed-command restart recovery is conservative UNKNOWN
- no socket/thread/process dependency
- no live broker mutation call surface
- fixed to an instance-specific spool leaf with no environment-variable setup

## Runtime probe

Safe read-only timer test:

```powershell
python -m bigqmt_autotrader.qmt.shadow_probe `
  --spool-dir D:\BigQMTData\spool\galaxy `
  --account-fingerprint <sha256:...> `
  snapshot
```

Safe shadow order transport test:

```powershell
python -m bigqmt_autotrader.qmt.shadow_probe `
  --spool-dir D:\BigQMTData\spool\galaxy `
  --account-fingerprint <sha256:...> `
  submit `
  --client-order-id p4-shadow-001 `
  --symbol 000001.SZ `
  --side BUY `
  --quantity 100 `
  --limit-price 1.00
```

The second command still has **zero broker trading side effect** under V05; it validates command identity, 1-second consumption, durable claim/process and return-event flow only.

## Explicitly out of scope for this checkpoint

- `passorder`
- real cancel
- LIVE_CANARY / LIVE_ARMED
- treating QMT callback status codes as calibrated broker lifecycle evidence
- automatic resend after UNKNOWN

Those require a separate, explicitly authorized mutation gate after ORDER/DEAL and status-code calibration. The current code contains no real broker mutation call.
