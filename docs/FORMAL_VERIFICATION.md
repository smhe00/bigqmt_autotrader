# Formal Verification Gate

Date: 2026-09-17

Status: **MANDATORY PERMANENT GATE**

## 1. Objective

Order execution, recovery, risk authority and Host↔Bridge communication are safety-critical. Unit/fault/integration tests remain necessary, but finite safety protocols are also exhaustively model-checked in CI.

A safety-relevant implementation change must update the corresponding model or conformance contract and keep the gate green.

The gate combines:

1. **TLA+ / TLC exhaustive model checking** of finite abstractions.
2. **Independent exhaustive Python/FSM or protocol conformance**.
3. **JSON Schema / implementation constant drift checks** for Bridge API v1.
4. **Static production-surface auditing** of broker side effects and authority boundaries.
5. Runtime transaction/fault/replay/integration tests for layers outside the formal abstractions.

## 2. Meaning and boundary of “complete”

For each finite TLA+ abstraction, TLC explores the complete configured abstract state graph rather than sampling scenarios.

This establishes exhaustive properties of the **encoded abstraction**. It does not prove:

- CPython;
- SQLite;
- Windows/NTFS;
- QMT implementation internals;
- broker/counter infrastructure;
- the full numeric input space;
- physical hardware/network correctness.

Those layers remain subject to fault injection, replay, integration and rule-by-rule tests.

Safety invariants are unconditional within their models. Liveness is only claimed where explicit fairness assumptions are encoded.

## 3. Order / OMS models

### `formal/OrderFSM.tla`

Models the 14-state order lifecycle, including `ABORTED`, `UNKNOWN`, `RECONCILING` and `MANUAL_REVIEW`.

Checks:

- state typing;
- total/exclusive event classification;
- terminal absorption;
- UNKNOWN/RECONCILING rules;
- ambiguity non-regression;
- ABORTED entry constraints.

`tools/verify_fsm_exhaustive.py` independently checks all current/request state pairs against the frozen implementation contract.

### `formal/SubmitProtocol.tla`

Models:

- durable submit/cancel reservation;
- broker side effect;
- response loss;
- hard crash after broker call but before result persistence;
- restart;
- reconciliation;
- partial fill / fill.

Key properties:

- at-most-once broker side effect;
- durable reservation causality;
- no blind retry after ambiguity;
- restart convergence to UNKNOWN/reconciliation;
- cancel ambiguity safety.

### `formal/LeaderLease.tla`

Models competing OMS writers, lease expiry and fencing epochs.

Checks:

- at most one valid executor;
- current-owner fencing;
- authority loss after expiry.

### `formal/EvidenceReplay.tla`

Models duplicate and out-of-order broker evidence.

Checks:

- one aggregate effect per logical evidence identity;
- monotonic fill/lifecycle facts;
- terminal fill does not regress.

### `formal/PreSubmitRecovery.tla`

Models restart while an order is durable but still pre-side-effect。

Checks that orphan `CREATED/RISK_ACCEPTED` identities converge to `ABORTED` and cannot later become executable.

### `formal/RiskPrecedence.tla`

Models deterministic fail-close risk selection across Global → Account → Strategy → Security/Order precedence.

It proves the encoded precedence and fail-close semantics. Concrete Decimal/time boundaries remain covered by Python tests.

## 4. BigQMT Bridge API v1 models

The formal domain now includes Host↔Bridge communication itself.

Wire/semantic specification:

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)
- `schemas/bridge/v1/*.schema.json`

### `formal/BridgeCommandProtocol.tla`

Models the durable command lifecycle:

```text
ABSENT
  ↓
INBOX
  ↓
CLAIMED
  ├── PROCESSED
  ├── REJECTED
  └── UNKNOWN
```

It includes:

- immutable publication;
- same-ID/same-payload idempotency;
- same-ID/different-payload conflict;
- expiration;
- account/session gates;
- SHADOW behavior;
- simulation side effect;
- crash before/after result persistence;
- orphan/restart behavior.

Checked invariants include:

- `ExpiredNeverMutatesBroker`
- `WrongAccountNeverMutatesBroker`
- `WrongSessionNeverMutatesBroker`
- `ShadowNeverMutatesBroker`
- `SideEffectAtMostOnce`
- `ClaimedCrashNeverBlindReplays`
- `SameCommandIdSamePayloadIsIdempotent`
- `SameCommandIdDifferentPayloadIsConflict`
- `TerminalCommandStateIsExclusive`
- `CommandResultCannotCreateBrokerAck`

### `formal/BridgeEventProtocol.tla`

Models:

- terminal/account identity;
- session generation;
- sequence;
- duplicate;
- gap;
- session change;
- `needs_resync`;
- clean snapshot recovery.

Checked invariants include:

- duplicate does not re-apply read-model state;
- wrong identity does not enter the read model;
- unresolved gap implies `needs_resync`;
- unresolved session change implies `needs_resync`;
- only a clean snapshot may clear resync;
- accepted sequence does not regress within a session.

The concrete implementation allows a clean snapshot that is itself the first post-gap event to heal the gap in the same ingest action. Therefore the formal rule is “**unresolved gap requires resync**”, not “the final flag must stay true even after a clean snapshot”.

### `formal/BrokerEvidenceBoundary.tla`

Models the authority boundary between:

```text
command_result            = control-plane evidence
ORDER / DEAL / query      = broker lifecycle evidence
```

It proves:

- command results alone cannot promote OMS to broker lifecycle state;
- `SHADOW_ACCEPTED` cannot create `ACKNOWLEDGED`;
- only broker evidence sources can promote lifecycle state.

This model connects the Bridge protocol to `EvidenceReplay` and `OrderFSM`.

## 5. Implementation conformance

### Order FSM

`tools/verify_fsm_exhaustive.py` maintains an independent copy of the frozen FSM relation and exhaustively compares it to implementation behavior.

### Bridge event protocol

`tools/verify_bridge_protocol_exhaustive.py` contains an independent Host-ingress oracle and compares it against `QmtIngressBuffer` across a finite matrix covering:

- valid identity;
- wrong terminal instance;
- wrong account;
- two sessions;
- sequence 1/2/3;
- duplicate;
- gap;
- clean snapshot;
- session switch.

The same checker verifies command-spool:

- exact-frame idempotent republish;
- conflicting same command ID fails closed;
- expired publication fails closed.

### Bridge schema drift

`tools/verify_bridge_schema_contract.py` checks that JSON Schema constants remain aligned with implementation constants:

- manifest version;
- command protocol/transport version;
- event protocol/transport version;
- command types;
- event types;
- allowed execution modes.

It also asserts that Bridge API v1 Schema does not expose `LIVE` / `LIVE_ARMED`.

### Schema behavioral tests

`tests/qmt/test_bridge_api_contract.py` validates legal and illegal samples with JSON Schema Draft 2020-12.

## 6. Static broker-side-effect audit

`tools/audit_side_effect_calls.py` is a structural drift detector.

Production `galaxy` and `guojin` artifacts must continue to expose **zero broker mutation call surface**.

Only the separately reviewed, fingerprint-pinned `guojin_sim` calibration artifact may contain the bounded simulation mutation executor.

The static audit is not a substitute for runtime fencing, identity checks or broker reconciliation.

## 7. Toolchain

CI pins:

- `tla2tools.jar`: **v1.7.4**
- SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Java: Temurin 17

The JAR hash is checked before TLC executes.

## 8. Gate criteria

A safety-critical candidate cannot PASS unless the exact candidate has:

- full Python test suite green;
- FSM conformance green;
- Bridge protocol conformance green;
- Bridge Schema drift check green;
- broker-side-effect audit green;
- standalone deployment build check green;
- every configured TLC model green;
- no unresolved TLC counterexample;
- no safety-invariant waiver.

A TLC counterexample is treated as a design/model/implementation defect until resolved. The default response is to correct the defect, not weaken the invariant.

## 9. Current gate status

- **P0/G0: PASS**
- **P1 Offline OMS: PASS**
- **P2 Risk Engine: PASS**
- **P3 Big QMT read-only: PASS**
- **P4 SHADOW deployment: PASS**
- **P5 bounded Guojin simulation submit/cancel/fill calibration: PASS**
- **Production live trading: NO**
- **LIVE_CANARY: NOT ENABLED**

BigQMT Bridge API v1 formalization extends the permanent gate; it does not grant new broker mutation authority.

The next execution-safety checkpoint remains a separately reviewed broker ORDER/DEAL/query → OMS evidence-mapping contract.
