# Project Status

Updated: 2026-09-17

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
| P2 Risk engine | **PASS** |
| P3 Big QMT read-only | **PASS** |
| P4 Big QMT execution bridge | **SHADOW DEPLOYMENT GATE PASS** |
| P5 Guojin simulation mutation calibration | **BOUNDED PASS** |
| BigQMT Bridge API v1 | **CONTRACT + FORMAL CI GATE** |
| Production-account live trading allowed | **NO** |
| LIVE_CANARY | **NOT ENABLED** |
| Production Guojin/Galaxy broker mutation call surface | **ZERO** |
| QMT submit/cancel implementation | **GUOJIN_SIM ONLY** |
| P2 execution-authority policy | **SIMULATION only** |

中文总览：

- [`PROJECT_OVERVIEW_ZH.md`](PROJECT_OVERVIEW_ZH.md)

Host↔Bridge 正式契约：

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)

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
BrokerEvidenceMapper
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

Galaxy linked-account ACCOUNT callbacks were observed reaching a selected STOCK model. The bridge now suppresses positively identified non-selected account callbacks from the selected OMS stream.

## 4. Multi-terminal isolation

Current standalone instances:

```text
D:\BigQMTData\spool\
├── galaxy\
├── guojin\
└── guojin_sim\
```

Each instance publishes `instance.json`; Host validates it against matching-session `bridge_ready`.

Host pins:

- terminal instance;
- account fingerprint;
- account type;
- session;
- protocol/transport versions;
- bridge build;
- execution mode;
- trading flags;
- simulation limits where applicable.

Simulation mutation instances are hidden unless Host is explicitly started with simulation authorization.

## 5. P3 read plane

Verified:

- ACCOUNT/POSITION/ORDER/DEAL active query;
- callback subscription;
- ACCOUNT callback;
- POSITION callback;
- event-driven ORDER/DEAL callback transport;
- 300 s independent active reconcile;
- durable atomic file publication;
- Host session/account/sequence validation;
- duplicate/gap/session-change fail-closed behavior;
- Host-only restart recovery;
- filesystem/semantic quarantine;
- closed-day archive integrity;
- account semantic duplicate suppression;
- `dropped_events=0` / `transport_failures=0` in calibrated runs.

Real Guojin V05 also proved:

- `1nSecond` command timer;
- `300nSecond` snapshot timer;
- Host→QMT→Host `REQUEST_SNAPSHOT`;
- healthy Host read model with zero backlog/quarantine.

## 6. P4 SHADOW execution plane

Production standalone artifacts:

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GALAXY.py`
- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN.py`

Production safety:

```text
TRADING_ENABLED=False
execution_mode=SHADOW
live_submit=False
live_cancel=False
```

No broker mutation call surface exists in these production artifacts.

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

SHADOW submit/cancel produce local control-plane results only.

Critical semantic:

```text
SHADOW_ACCEPTED != broker ACK
```

`command_result` cannot directly create `ACKNOWLEDGED/FILLED/CANCELLED`.

## 7. P5 Guojin simulation calibration

Simulation artifact:

- `qmt_side/BIGQMT_EXECUTION_BRIDGE_V05_GUOJIN_SIM.py`

Safety properties:

- exact account fingerprint pin;
- `simulation_only=true`;
- `execution_mode=SIMULATION_CALIBRATION`;
- only reviewed A-share BUY calibration shape;
- finite submit/cancel per-session fuse;
- exact broker-order-ID + broker-token cancel target;
- current QMT session pin;
- explicit Host + publisher simulation authorization;
- no automatic blind retry.

Calibrated lifecycle evidence includes:

- resting order + cancel;
- full fill;
- ORDER callback;
- DEAL callback;
- active ORDER/DEAL query;
- deterministic `BQ...` token preserved across ORDER/DEAL;
- Host outage replay;
- command conflict/expiry/wrong-account/stale-session rejection.

After-hours testing additionally proved:

- QMT cancel API success does not imply immediate query-surface state change;
- repeated cancel can therefore be unsafe;
- simulation publisher now prevents duplicate cancel publication for the exact account/client/broker-order identity;
- query lag cannot trigger automatic re-cancel.

Same-evening closeout revalidated Host-offline event persistence and restart recovery with zero backlog/quarantine.

## 8. BigQMT Bridge API v1

API v1 formalizes the existing Host↔Bridge contract without changing already calibrated wire versions:

```text
Discovery Contract 1
Command Protocol   0.1
Event Protocol     0.2
File Transport     1
```

Three layers:

1. JSON Schema wire contract;
2. semantic contract;
3. TLA+/TLC safety contract.

Schemas:

```text
schemas/bridge/v1/
├── instance.schema.json
├── command.schema.json
├── event.schema.json
└── command_result.schema.json
```

New formal models:

- `BridgeCommandProtocol`
- `BridgeEventProtocol`
- `BrokerEvidenceBoundary`

New permanent checks:

- Bridge ingress finite conformance matrix;
- command-spool idempotency/conflict/expiry;
- Schema ↔ implementation constant drift;
- Schema legal/illegal sample tests.

Details:

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)
- [`FORMAL_VERIFICATION.md`](FORMAL_VERIFICATION.md)

## 9. Broker evidence boundary

Current read-only calibration projection recognizes broker tokens only when `remark` exactly matches:

```text
BQ[0-9a-f]{20}
```

It preserves raw broker order/trade identity and raw QMT status fields.

The system still deliberately does **not** guess production-grade:

```text
QMT raw status → OMS lifecycle status
```

A separately reviewed broker evidence mapper remains the next execution-safety gate.

Until that gate passes:

- ORDER/DEAL may be observed/calibrated;
- untrusted lifecycle interpretation is quarantined;
- `command_result` remains control-plane only.

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

CI also runs:

- Python tests;
- FSM exhaustive conformance;
- Bridge protocol conformance;
- Bridge Schema drift check;
- broker side-effect static audit;
- standalone QMT deployment check.

No safety invariant waiver is permitted.

## 11. Market data direction

A future QMT Market Data Bridge is planned as a separate QMT strategy.

It may reuse:

- discovery/versioning;
- envelope;
- terminal/session health principles.

It must not inherit execution mutation authority.

Planned division:

```text
QMT Market Data Bridge → quote/tick/bar/reference
Execution Bridge       → account/order/deal/submit/cancel
```

This is currently **architecture direction only**, not implemented functionality.

## 12. Current checkpoint

**P0/P1/P2/P3 PASS. P4 SHADOW deployment PASS. P5 bounded Guojin simulation submit/cancel/fill calibration PASS. BigQMT Bridge API v1 is the formal Host↔Bridge contract. Production live trading remains disabled and unimplemented.**

Next safety checkpoint:

> calibrated replay-safe broker ORDER/DEAL/query → OMS evidence mapping.

Gate evidence:

- `docs/P1_GATE_RESULT_20260912.md`
- `docs/P2_GATE_RESULT_20260913.md`
- `docs/P3_GATE_RESULT_20260915.md`
- `docs/P4_GATE_RESULT_20260915.md`
- `docs/P5_GATE_RESULT_20260916.md`
