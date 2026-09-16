# P5 Guojin Simulation Calibration Gate Result — 2026-09-16

## Decision

**GUOJIN_SIM BOUNDED MUTATION CALIBRATION: PASS**

**ORDER/DEAL + `m_strRemark` PRESERVATION: PASS IN GUOJIN SIMULATION**

**OMS BROKER-EVIDENCE STATUS MAPPING: STILL DISABLED**

**GALAXY/GUOJIN PRODUCTION MUTATION: PERMANENTLY DISABLED**

This result closes the bounded runtime-calibration checkpoint only. It does not
authorize production trading, a live canary, automatic strategy execution, or
promotion of raw QMT status codes into OMS broker evidence.

## Runtime identity and safety evidence

- terminal instance: `guojin_sim`;
- bridge build: `p5-simulation-calibration-1`;
- QMT session: `876fe6929be643e386d0e86b8b52f566`;
- account type: `STOCK`;
- account fingerprint matched the source-pinned authorized simulation account;
- execution mode: `SIMULATION_CALIBRATION`;
- `simulation_only=true`;
- Host required `--allow-simulation-mutation`;
- generated Galaxy and Guojin production artifacts still contain zero
  `passorder`/`cancel` calls.

The fresh read model was healthy with no query errors or transport quarantine
before mutation. The command spool had no inbox, claimed, rejected, or unknown
commands.

## Cancel-path observation

A 100-share BUY for `510300.SH` at limit `4.400` was intentionally placed below
the observed market and then cancelled.

| Fact | Observed value |
| --- | --- |
| client order ID | `simcal-510300-cancel-20260916-01` |
| broker token / exact `m_strRemark` | `BQ81ab7c6ddc8e40932700` |
| broker order ID | `10951` |
| initial callback | status `50`, submit status `51`, filled `0` |
| terminal callback | status `54`, submit status `51`, filled `0` |
| command results | `SIMULATION_SUBMIT_CALL_RETURNED`, then `SIMULATION_CANCEL_SIGNAL_SENT` |

The cancel executor queried active orders and required the exact pair
`(broker_order_id=10951, m_strRemark=BQ81ab7c6ddc8e40932700)` before sending the
cancel signal. No DEAL was emitted for this order.

## Fill-path observation

The second and final submit allowed in the QMT session was a 100-share BUY for
`510300.SH` at limit `4.600`.

| Fact | Observed value |
| --- | --- |
| client order ID | `simcal-510300-fill-20260916-01` |
| broker token / exact `m_strRemark` | `BQ07a45d26d31b03b3a1ed` |
| broker order ID | `10968` |
| terminal ORDER callback | status `56`, submit status `51`, filled `100` |
| DEAL | trade ID `50037292`, quantity `100`, price `4.544` |
| command result | `SIMULATION_SUBMIT_CALL_RETURNED` |

Both the terminal ORDER callback and DEAL callback preserved the same exact
22-character broker token in `m_strRemark`.

The next independent active-query snapshot (sequence `63`) converged with no
query errors: two ORDER rows, one DEAL row, the same broker IDs/tokens/status
codes, and `510300.SH` quantity increased from 100 to 200. Only the original
100 was sellable on the trade date, consistent with the expected A-share/ETF
same-day sellability boundary.

## Independent read-only calibration report

`calibration_probe --details` scanned the spool without moving or changing any
file and reported:

- 818 event frames scanned;
- 7 callback ORDER/DEAL observations;
- all 7 classified `MATCHED_KNOWN_TOKEN`;
- zero guessed, malformed, missing, unregistered, or account-mismatched token
  associations in the calibration sample;
- `broker_evidence_mapping_enabled=false`;
- `live_submit=false` and `live_cancel=false` in the observer.

ORDER/DEAL events remained in semantic quarantine by design. A command API
return was not treated as broker ACK, and the observed raw status codes were
not translated into OMS states.

## Gate boundary

This calibration proves exact token transport and a bounded Guojin simulation
submit/cancel/fill lifecycle. It does not yet prove that the same status codes
or callback ordering apply to a production account. Any future OMS evidence
mapper needs a separately reviewed status contract, replay/idempotency tests,
active-query convergence rules, and a new explicit Gate. Production mutation
remains out of scope.

## Trading-session robustness matrix

A second pass during the continuous trading session exercised normal and
abnormal control paths without resetting the QMT session or expanding its
mutation allowance.

| Scenario | Observed result | Broker mutation |
| --- | --- | --- |
| snapshot request | `SNAPSHOT_EMITTED` | none |
| identical durable command republish | same stored path; one QMT execution | none |
| same command ID with different content | Host `QmtCommandConflict` | none |
| cancel fully filled order `10968` | `SIMULATION_CANCEL_NOT_CANCELLABLE` | none |
| repeat cancel terminal order `10951` | `SIMULATION_CANCEL_NOT_CANCELLABLE` | none |
| wrong client/token for broker order | `REJECTED_SAFETY_GATE` | none |
| nonexistent broker order | `REJECTED_SAFETY_GATE` | none |
| third submit in a two-submit session | `REJECTED_SAFETY_GATE` | none |
| stale QMT session authorization | `REJECTED_SAFETY_GATE` | none |
| wrong account fingerprint | parser `COMMAND_REJECTED` | none |
| expired durable command | `REJECTED_EXPIRED` | none |
| malformed JSON / unsupported transport | parser `COMMAND_REJECTED` | none |
| incomplete `.tmp` publication | ignored until removed | none |
| publisher wrong confirmation / quantity / symbol / TTL / price | rejected before inbox | none |
| Host without simulation opt-in | startup rejected | none |
| Host stopped while QMT handles snapshot | QMT completed; Host replayed on restart | none |

The final command directories contained 10 processed, 8 rejected, zero inbox,
zero claimed, and zero unknown commands. Host recovery selected snapshot
sequence `156`, replayed through command-result sequence `196`, and remained
healthy with zero pending event frames.

Further broker-facing order variants require a fresh QMT strategy session
because the hard two-submit session allowance was correctly exhausted. That
reset is an explicit operator action; it is not performed automatically.

Post-gate operational update: build `p5-simulation-calibration-2` raises the
finite `guojin_sim` session fuses to 2,000 submit calls and 2,000 cancel calls
for extended simulation testing. The historical two-submit evidence above is
unchanged. Host manifest validation and the QMT-side anti-tamper gate both
require the new values; production `guojin` and `galaxy` remain mutation-free.

## After-hours broker findings

Build `p5-simulation-calibration-2` was restarted as QMT session
`95f8c96efcf84a2e8badfabf0822ab28`. A `510300.SH` BUY 100 order at the bridge
ceiling price `100000` reached the Guojin simulation counter and was rejected
with raw status `57`, error `2147483647`, and counter detail `[120279]` stating
that a Shanghai order price must be below `10000`. The deterministic broker
token remained intact.

A second BUY 100 at `4.400` was accepted after normal trading hours as broker
order `13423`, raw status `50`, with 100 remaining and CNY 440 frozen. QMT
`cancel()` returned `True`, but repeated active snapshots continued to expose
raw status `50`. Two QMT cancel calls returned a sent signal while the query
surface remained unchanged; a later manual terminal cancel then produced
counter error `-61 / [251013] cannot cancel repeatedly`. This proves that a
successful cancel signal can establish broker-side cancel-pending state before
the query surface changes.

The simulation publisher now fails closed if any command-spool state already
contains a cancel for the exact account, client order ID, and broker order ID.
New cancel command IDs are deterministic for that identity. A lagging active
query alone therefore cannot cause an automatic or operator CLI recancel; the
order must reconcile or be resolved manually.
