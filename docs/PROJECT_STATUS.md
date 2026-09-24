# Project Status

Updated: 2026-09-19

## 1. Summary

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| Host Python baseline | **CPython 3.12** |
| QMT-side syntax target | **Built-in Python 3.6 compatible** |
| Observed Guojin QMT runtime | **CPython 3.6.8 / QMT 2.1.19.0** |
| Observed Galaxy QMT terminal | **QMT 2.1.26.1** |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | **PASS — Production Runtime layer** |
| P7 Core / Runtime boundary | **PASS — isolated API/schema + permanent CI dependency Gate** |
| P7.1 Operational Core boundary | **PASS candidate — Runtime uses Core public API only** |
| P3 Big QMT read-only | **PASS** |
| P4 Big QMT execution bridge | **SHADOW DEPLOYMENT GATE PASS** |
| P5 Guojin simulation mutation calibration | **BOUNDED PASS** |
| BigQMT Bridge API v1 | **CONTRACT + FORMAL CI GATE** |
| Broker Evidence Contract v1 | **PROTOCOL + FORMAL CI GATE** |
| Guojin simulation raw status mapper | **PASS — `qmt-guojin-sim-20260917-v1`** |
| Production Guojin / Galaxy mapper | **NOT IMPLEMENTED / NOT AUTHORIZED** |
| Production-account live trading allowed | **NO** |
| Guojin LIVE_CANARY implementation | **`p6-guojin-live-canary-7`; ONE NAMED CASE ONLY — `00700.HGT BUY 100 @ 1.00 HKD`; SUBMIT/CANCEL FUSE 1/1** |
| Production broker mutation call surface | **GUOJIN: ONE PINNED LIVE_CANARY SURFACE; GALAXY/GENERIC: ZERO** |
| QMT submit/cancel implementation | **GUOJIN_SIM + PINNED GUOJIN LIVE_CANARY** |
| P2 execution-authority policy | **SIMULATION only** |

中文总览：

- [`PROJECT_OVERVIEW_ZH.md`](PROJECT_OVERVIEW_ZH.md)

正式协议：

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)
- [`BROKER_EVIDENCE_CONTRACT_V1_ZH.md`](BROKER_EVIDENCE_CONTRACT_V1_ZH.md)

## 2. Architecture boundary

```text
Strategy
  ↓ OrderIntent
Risk Engine
  ↓
OMS
  ↓
Host
  ↓ BigQMT Bridge API v1
Execution Bridge
  ↓
Big QMT / Broker

ORDER / DEAL / active query
  ↓
broker-specific mapper
  ↓
Broker Evidence Contract v1
  ↓
EvidenceReplay
  ↓
OMS FSM
```

Strategy code does not call QMT directly.

OMS owns durable identity, state, recovery, reconciliation and audit.

Risk owns deterministic pre-side-effect eligibility.

Execution Bridge is intentionally thin.

## 3. Broker-neutral account / terminal discovery

Bridge discovery is runtime evidence-based.

Confirmed account capabilities are transported separately from the selected OMS account stream. Missing/None/mismatched/exception results remain `UNCONFIRMED` or `DEGRADED`; they are never silently interpreted as an empty account.

Observed Galaxy account types:

- `STOCK`
- `HUGANGTONG`
- `SHENGANGTONG`

Galaxy linked-account ACCOUNT callbacks were observed reaching a selected STOCK model. The bridge suppresses positively identified non-selected account callbacks from the selected OMS stream.

## 4. Multi-terminal isolation

Current standalone instances:

```text
D:\BigQMTData\spool\
├── galaxy\
├── guojin\
└── guojin_sim\
```

Each instance publishes `instance.json`; Host validates it against matching-session `bridge_ready`.

Host pins terminal instance, account fingerprint/type, session, protocol/transport versions, bridge build, execution mode, trading flags and simulation limits where applicable.

Simulation mutation instances are hidden unless Host is explicitly started with simulation authorization.

## 5. P3 read plane

Verified:

- ACCOUNT/POSITION/ORDER/DEAL active query;
- callback subscription;
- ACCOUNT/POSITION/ORDER/DEAL callback transport;
- 300 s independent active reconcile;
- durable atomic file publication;
- Host session/account/sequence validation;
- duplicate/gap/session-change fail-closed behavior;
- Host-only restart recovery;
- filesystem/semantic quarantine;
- closed-day archive integrity;
- account semantic duplicate suppression.

Real Guojin V05 also proved:

- `1nSecond` command timer;
- `300nSecond` snapshot timer;
- Host→QMT→Host `REQUEST_SNAPSHOT`;
- healthy Host read model with zero backlog/quarantine.

## 6. P4 SHADOW execution plane and P6 Guojin exception

Production standalone artifacts:

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py` — SHADOW, mutation-free;
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py` — independently gated P6 LIVE_CANARY.

Galaxy and generic production safety remains:

```text
TRADING_ENABLED=False
execution_mode=SHADOW
live_submit=False
live_cancel=False
```

Guojin is the sole bounded exception: fingerprint-pinned and current-session-pinned.
Since `p6-guojin-live-canary-7` the build authorizes exactly ONE submit case —
`00700.HGT BUY 100 @ 1.00 HKD` (fixed non-marketable HGT route price) — with a
one-shot submit fuse (1) and one exact-token cancel reserve (1) per build/session.
GC001 (`204001.SH`) is a completed historical calibration (token-matched status-57
price-range rejection, funds fully restored) and is no longer authorized; `511880.SH`
remains a read-only diagnostic candidate and needs its own independent Gate/build
before any submit. Every mutation remains fail-closed behind instrument/account/
trading-window preflights and the single-case semantic gate. This does not grant
general production live-trading authority.

Command spool:

```text
commands/inbox
    → claimed
    → processed | rejected | unknown
```

Implemented command types:

- `SUBMIT_LIMIT`
- `CANCEL_ORDER`
- `REQUEST_SNAPSHOT`

Critical semantic:

```text
SHADOW_ACCEPTED != broker ACK
```

`command_result` cannot directly create `ACKNOWLEDGED/FILLED/CANCELLED`.

## 7. P5 Guojin simulation calibration

Simulation artifact:

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`

Safety properties include exact account fingerprint/session pinning, simulation-only authority, bounded submit/cancel fuses, exact broker-order-ID + broker-token cancel target, and no automatic blind retry.

Calibrated lifecycle evidence includes resting order + cancel, full fill, ORDER/DEAL callback, active ORDER/DEAL query, deterministic broker token preservation, Host outage replay, and command conflict/expiry/wrong-account/stale-session rejection.

After-hours testing also proved that QMT cancel API success does not imply immediate query-surface cancellation; duplicate cancel publication is therefore suppressed.

## 8. BigQMT Bridge API v1

API v1 formalizes Host↔Bridge without changing calibrated wire versions:

```text
Discovery Contract 1
Command Protocol   0.1
Event Protocol     0.2
File Transport     1
```

Permanent Gate includes JSON Schema, semantic contract, TLA+/TLC models and finite protocol conformance.

Details:

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)
- [`FORMAL_VERIFICATION.md`](FORMAL_VERIFICATION.md)

## 9. Broker Evidence Contract v1

The broker→OMS evidence semantics are now frozen independently of any specific QMT raw status code.

Schema:

```text
schemas/broker_evidence/v1/broker_evidence.schema.json
```

Allowed source classes:

```text
ORDER_CALLBACK
DEAL_CALLBACK
ACTIVE_ORDER_QUERY
ACTIVE_DEAL_QUERY
```

Standard evidence:

```text
ORDER_ACCEPTED  -> ACKNOWLEDGED
PARTIAL_FILL    -> PARTIALLY_FILLED
FULL_FILL       -> FILLED
ORDER_CANCELLED -> CANCELLED
ORDER_REJECTED  -> REJECTED
```

Critical exclusions:

```text
command_result
submit/cancel API return
unknown raw status
identity mismatch
```

do not become `BrokerEvidence`.

The contract also freezes:

- durable identity admission;
- source-event dedup and same-ID/different-digest conflict handling;
- cumulative, monotonic `filled_quantity`;
- no timestamp/source-priority overwrite rule;
- partial-fill + cancel semantics;
- terminal conflict → `MANUAL_REVIEW`.

Formal assets:

- `formal/BrokerEvidenceContract.tla`
- `formal/BrokerEvidenceContract.cfg`
- `tools/verify_broker_evidence_contract.py`
- `tests/qmt/test_broker_evidence_contract.py`

Details:

- [`BROKER_EVIDENCE_CONTRACT_V1_ZH.md`](BROKER_EVIDENCE_CONTRACT_V1_ZH.md)

## 10. Guojin simulation evidence mapper

The first broker-specific profile is implemented as
`qmt-guojin-sim-20260917-v1`. It is hard-pinned to the `guojin_sim` terminal
and its configured account fingerprint. Durable OMS registration of
`client_order_id + symbol + quantity` is required
before an exact `m_strRemark` token may be resolved.

Calibrated mappings are deliberately narrow:

```text
ORDER 50/51 + broker ID + zero fill -> ORDER_ACCEPTED
ORDER 54/51 + broker ID + zero fill -> ORDER_CANCELLED
ORDER 56/51 + exact full quantity   -> FULL_FILL
ORDER 57/51 + zero fill             -> ORDER_REJECTED
DEAL + exact token/trade/order IDs   -> cumulative PARTIAL_FILL/FULL_FILL
```

Callback and active-query sources remain distinct. Unknown status, incomplete
initial status 50, missing/unregistered token, wrong account/terminal,
broker-order-ID conflict, trade-ID conflict and quantity contradiction remain
quarantined. A real 2026-09-17 spool replay produced accepted then cancelled
evidence for broker order `4083`, with the initial no-broker-ID callback kept
in quarantine. A second trading-session run submitted at 14:57:29 and matched
in the 15:00 closing auction: broker order `5652`, trade `50043738`, 100 shares
at `4.532`. Callback and active-query replay independently produced FULL_FILL.

The generated `guojin_sim` V5 artifact is now build
`p5-simulation-calibration-8`. Its submit gate supports explicit BUY/SELL and
integer quantity `1..100` for six-digit `.SH`/`.SZ` securities and five-digit
`.HK`/`.HGT`/`.SGT` securities on the same manifest-pinned `STOCK` simulation account, while retaining
all simulation identity/session/token/price/fuse gates. This permits a bounded
GC001 sell-path and Hong Kong Connect routing calibration without enabling any
production artifact. It does not invent a second account: Guojin routes those
markets through the same bound `STOCK` account. Build-5 also emits the bounded
instrument-detail and exact-symbol tick evidence used by the live bridge so the
simulation route can be calibrated before mutation. The production artifacts
remain byte-for-byte unchanged by this update.

Build-7 uses Big QMT's read-only sector-membership API first, then fills an
empty or partial result from a bounded preferred Hong Kong calibration list.
It probes at most six underlying codes and 20 total diagnostic routes. Runtime
evidence records discovered and fallback codes separately. Discovery never
submits or broadens command authorization.

Build-7 was then loaded by the Guojin simulation terminal in session
`3a958aea1584464083756592bf912bd9`. Local sector-name queries remained empty,
so the bounded preferred fallback selected `00700`, `09988`, `01810`, `03690`,
`00941`, and `00981`. Instrument detail and exact-symbol quote callbacks passed
for all 20 routes (18 Hong Kong suffix routes plus two Shanghai probes). Every
Hong Kong underlying resolved consistently across `.HK/.HGT/.SGT` with
`HSGTFlag=5`. No order or cancel command was published by this calibration.

The first build-4 after-hours `00700.HK` probe reached `passorder` through that
bound STOCK account, but produced no ORDER/DEAL callback and no row in the
immediate clean active snapshot. It is therefore recorded as API-call-returned
with broker state not observed, never as ACK. Trading-session calibration is
still required and automatic retry remains forbidden.

The first production Guojin LIVE_CANARY build was armed on 2026-09-18. A
single authorized `00700.HK BUY 100 @ 1.00` call reached the QMT trade module,
which synchronously logged `下单代码 [HK00700] 不合法!`; immediate active query
remained `orders=[]`, `deals=[]`, with unchanged funds and positions. This is
recorded as a local zero-side-effect rejection, never broker ACK. Guojin's local
quote logs independently contain live `00700.SGT` records. Build
`p6-guojin-live-canary-2` therefore pinned `00700.SGT` and required a non-empty
SGT/00700 instrument-detail preflight before `passorder`. Its first authorized
command failed that preflight closed: `REJECTED_SAFETY_GATE`,
`live_side_effect=false`, zero `passorder` calls and no ORDER/DEAL. Build-3's
read-only startup probe found no instrument master for `.HK/.HGT/.SGT` in the
model runtime. Build-4 proved that `.HK/.HGT/.SGT` all return accepted tick subscription IDs,
while all three remain empty through instrument-master probe attempt 10. Subscription
acceptance is therefore non-discriminative. Build-5 introduced bounded quote callbacks
and publishes only normalized `instrument_tick_capabilities` evidence. Build-5 also
uses exact-key `get_full_tick([symbol])` as a read-only fallback when a broker QMT
distribution cannot load subscription callbacks; aliases never satisfy this gate. After the
broker login capability changed, exact instrument metadata observed `.SGT` as canonical
`HK/00700` with `HSGTFlag=5`. The previous canary build temporarily permitted two
explicit cases and added `204001.SH`/`511880.SH` to the read-only tick evidence set.
The current `p6-guojin-live-canary-7` Gate (task P6-T001) narrowed that back to exactly
one submit case — `00700.HGT BUY 100 @ 1.00 HKD` — with submit/cancel fuse 1/1; GC001 is
no longer authorized and 511880 stays read-only pending a separate Gate.

### Still pending

This Gate approves only the single bounded Guojin LIVE_CANARY case described
above; it does **not** approve a general Guojin production mapper or any Galaxy
mapper. `galaxy` remains SHADOW and mutation-free. Enabling the simulation
mapper in an operating Host also requires explicit durable OMS identity
registration; it is not auto-enabled by instance discovery.

### Runtime conformance

The broker-neutral runtime conformance Gate passed on 2026-09-17. The OMS now
accepts only validated `BrokerEvidenceV1`, persists the full v1 identity and
audit fields, fails terminal/identity conflicts closed to `MANUAL_REVIEW`, and
does not treat submit/cancel API returns as broker lifecycle facts.

Details:

- [`BROKER_EVIDENCE_RUNTIME_CONFORMANCE_RESULT_20260917_ZH.md`](BROKER_EVIDENCE_RUNTIME_CONFORMANCE_RESULT_20260917_ZH.md)

## 10. Formal verification

Permanent models:

- `OrderFSM`
- `SubmitProtocol`
- `LeaderLease`
- `EvidenceReplay`
- `PreSubmitRecovery`
- `RiskPrecedence`
- `BridgeCommandProtocol`
- `BridgeEventProtocol`
- `BrokerEvidenceBoundary`
- `BrokerEvidenceContract`

CI also runs:

- Python tests;
- FSM exhaustive conformance;
- Bridge protocol conformance;
- Bridge Schema drift check;
- Broker Evidence finite contract/schema conformance;
- broker side-effect static audit;
- standalone QMT deployment check.

No safety invariant waiver is permitted.

## 11. Market data direction

A future QMT Market Data Bridge is planned as a separate QMT strategy.

It may reuse discovery/versioning, envelope, terminal/session health principles, but must not inherit execution mutation authority.

Planned division:

```text
QMT Market Data Bridge -> quote/tick/bar/reference
Execution Bridge       -> account/order/deal/submit/cancel
```

This remains architecture direction only.

## 12. Core / Runtime boundary

Execution Core and Production Runtime are explicitly separated.

Core roots:

```text
core / domain / drivers / oms / qmt
```

cannot import Runtime roots:

```text
risk / market_data / operations / service / strategy_api / runtime / web
```

Core-only databases stop at schema 8; full Runtime remains schema 11. Existing schema 9..11 combined databases remain Core-readable without downgrade.

Permanent CI:

```bash
python tools/verify_core_dependency_boundary.py
python tools/verify_runtime_core_boundary.py
```

P7.1 additionally prohibits Runtime roots from importing `oms/`, `qmt/` or `drivers/` implementation modules directly. Runtime execution coupling must go through `bigqmt_autotrader.core.ExecutionPort` and other top-level Core public contracts.

Detailed design: [`CORE_RUNTIME_BOUNDARY_ZH.md`](CORE_RUNTIME_BOUNDARY_ZH.md).

## 13. Current checkpoint

**P0/P1/P2/P3 PASS. P4 SHADOW deployment PASS. P5 `p5-simulation-calibration-8` bounded simulation calibration PASS, including 20/20 read-only Stock Connect route evidence. Broker Evidence Runtime Conformance PASS. P6 `p6-guojin-live-canary-7` narrowed to one named one-shot LIVE_CANARY case (`00700.HGT BUY 100 @ 1.00 HKD`, fuse 1/1); Galaxy and generic deployments remain mutation-free.**

Next safety checkpoint:

> in a fresh `p6-guojin-live-canary-7` session, run `00700.HGT BUY 100 @ 1.00` exactly
> once, then fully reconcile ORDER/DEAL/query/BrokerEvidence before anything else.
> 511880 is NOT authorized in this build; its insufficient-funds probe needs a separate
> independent Gate/build after the HGT result passes review.

Gate evidence:

- `docs/P1_GATE_RESULT_20260912.md`
- `docs/P2_GATE_RESULT_20260913.md`
- `docs/P3_GATE_RESULT_20260915.md`
- `docs/P4_GATE_RESULT_20260915.md`
- `docs/P5_GATE_RESULT_20260916.md`
- `docs/BROKER_EVIDENCE_RUNTIME_CONFORMANCE_RESULT_20260917_ZH.md`
