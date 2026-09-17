# P5 Guojin Simulation Mutation Gate

Date: 2026-09-16

Runtime result: **PASS**. See `P5_GATE_RESULT_20260916.md` for the bounded
submit/cancel/fill evidence. This document remains the permanent safety
contract for that calibration surface.

## Authorization and scope

The operator authorized broker mutation only for the Guojin simulated account
represented by terminal instance `guojin_sim`. Galaxy and Guojin
production-account instances remain permanently disabled at the generated
source level.

This gate exists only to calibrate QMT ORDER/DEAL callbacks, active-query rows,
raw status codes, and exact `userOrderId` to `m_strRemark` preservation. It does
not authorize production trading, LIVE_CANARY, automated strategy execution,
or an OMS broker-evidence status mapper.

## QMT API contract

The reviewed simulation artifact uses the documented built-in-Python calls:

```python
passorder(23, 1101, account_id, symbol, 11, price, 100,
          "BIGQMT_SIM_CAL", 2, broker_token, ContextInfo)

cancel(broker_order_id, account_id, "STOCK", ContextInfo)
```

`23` is stock buy, `1101` is single-security/single-account share quantity,
`11` is specified limit price, and quick-trade `2` dispatches immediately.
QMT documents that `userOrderId` is exposed as `m_strRemark` in ORDER and DEAL
objects. It also documents `cancel()` as returning whether a cancel signal was
sent, not whether cancellation completed.

Reference:

- https://miniqmt.com/qmtapi/QMT_Python_API_Doc.html

QMT run mode and account type are separate concepts. The simulation brokerage
account must be used in the QMT model-trading mode that permits trading API
calls; QMT's signal-only simulation run mode does not execute `passorder`.

## Independent authorization layers

The mutation path opens only when every layer agrees:

1. Generated artifact is exactly
   `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`.
2. `TERMINAL_INSTANCE_ID == "guojin_sim"`.
3. Runtime account fingerprint exactly equals the pinned observed simulation
   fingerprint; raw account ID is not stored in source or Host commands.
4. Runtime account type is `STOCK`.
5. Manifest and `bridge_ready` both declare
   `execution_mode=SIMULATION_CALIBRATION`, `simulation_only=true`, and the
   reviewed fixed limits.
6. Host is started with `--allow-simulation-mutation`; without it the instance
   is not discoverable/selectable.
7. Publisher is `simulation_probe` with the exact confirmation phrase
   `AUTHORIZE_SIMULATION_CALIBRATION`.
8. Command embeds the current QMT session ID and expires in at most 30 seconds.
9. QMT validates the deterministic broker token again before any API call.

## Hard limits

- submit side: BUY only;
- security: six-digit `.SH` or `.SZ` A-share symbol only;
- side: explicit `BUY` or `SELL`;
- quantity: integer `1..100` units;
- symbol: any six-digit `.SH` / `.SZ` security code accepted by the bound
  simulation STOCK account;
- price: explicit positive limit price;
- maximum submit calls per QMT session: 2,000;
- maximum cancel calls per QMT session: 2,000;
- these are finite runaway-loop fuses, not a target activity level; each
  calibration run must still issue only the reviewed commands it needs;
- cancel target: exactly one active-query ORDER whose broker order ID and
  `m_strRemark` both match the command;
- no blind retry after a claimed-command crash or broker API exception.

An asynchronous submit call returning normally produces
`SIMULATION_SUBMIT_CALL_RETURNED`, not ACKNOWLEDGED. A cancel returning `True`
produces `SIMULATION_CANCEL_SIGNAL_SENT`, not CANCELLED. Unknown outcomes remain
UNKNOWN and are never replayed.

## Deployment and calibration sequence

1. Stop only the old `guojin_sim` strategy.
2. Replace its source with the generated simulation artifact.
3. Confirm the QMT terminal is connected to the authorized simulated brokerage
   account and start the strategy in the mode that permits broker API calls.
4. Verify the new manifest/build and start Host:

```powershell
python -m bigqmt_autotrader.qmt.host `
  --instance-id guojin_sim `
  --allow-simulation-mutation
```

5. Select an A-share and two reviewed prices from the fresh simulated-account
   snapshot/market context: one intended to rest for cancel calibration, then
   one intended to fill for DEAL calibration.
6. Publish the resting 100-share BUY through `simulation_probe`, observe the
   exact ORDER token and broker order ID, then cancel that exact order.
7. Publish the fill-calibration 100-share BUY and collect ORDER/DEAL callback
   plus active-query convergence.

Current build `p5-simulation-calibration-3` removes the original BUY-only and
exactly-100 restrictions inside the dedicated simulation artifact. It maps
`BUY -> passorder opType 23` and `SELL -> opType 24`; the Host publisher also
requires an explicit side. The account fingerprint, current QMT session,
simulation-only mode, 100-unit per-command ceiling, finite session fuses,
price bounds, exact broker token and cancel identity checks remain mandatory.
Production artifacts are unchanged.
8. Run `calibration_probe --details`; do not enable an evidence mapper until
   all acceptance criteria in
   `P4_ORDER_DEAL_BROKER_TOKEN_CALIBRATION.md` pass.

## Static and regression enforcement

CI regenerates every standalone file and fails on drift. AST audits require:

- zero `passorder`/`cancel` calls in the template, Galaxy artifact, and Guojin
  production-account artifact;
- exactly one `passorder` and one `cancel` call, both inside the reviewed
  simulation executor, in the `guojin_sim` artifact;
- Python 3.6 syntax compatibility for every QMT deployment;
- command-result separation from OMS broker evidence.

## Calibrated runtime facts

The authorized `guojin_sim` run completed both planned paths in QMT session
`876fe6929be643e386d0e86b8b52f566`:

- resting BUY: broker order `10951`, exact token preserved, raw terminal status
  `54`, zero fill, cancel signal sent;
- fill BUY: broker order `10968`, exact token preserved in ORDER and DEAL, raw
  terminal status `56`, 100 filled at `4.544`, trade `50037292`;
- active-query snapshot sequence `63` converged to the same two ORDER rows and
  one DEAL row with `query_errors=[]`;
- the read-only probe matched all 7 ORDER/DEAL callback observations to the two
  registered durable client identities;
- ORDER/DEAL stayed quarantined and no OMS broker-evidence mapper was enabled.

Raw status numbers above are recorded observations, not a general semantic
mapping or authority to enter an OMS terminal state.

The same trading session also passed negative-path checks for terminal-order
cancel, token/order mismatch, stale session, wrong account, expiry, malformed
transport, publisher validation, per-session submit exhaustion, and Host outage
recovery. See `P5_GATE_RESULT_20260916.md`. None produced a new broker mutation;
the command spool finished with zero `unknown` commands.
