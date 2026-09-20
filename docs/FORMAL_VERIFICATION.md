# Formal Verification Gate

Date: 2026-09-17

Status: **MANDATORY PERMANENT GATE**

## 1. Objective

Order execution, recovery, risk authority, Host↔Bridge communication, and broker-evidence admission are safety-critical.

The gate combines:

1. **TLA+ / TLC exhaustive model checking** of finite abstractions.
2. **Independent exhaustive Python/FSM/protocol conformance**.
3. **JSON Schema / contract drift checks**.
4. **Static production-surface auditing** of broker side effects and authority boundaries.
5. Runtime transaction/fault/replay/integration tests for layers outside the formal abstractions.

A safety-relevant implementation or protocol change must update the corresponding model or conformance contract and keep the gate green.

## 2. Meaning and boundary of “complete”

TLC explores the complete configured abstract state graph of each model. This proves properties of the encoded abstraction, not CPython, SQLite, Windows/NTFS, QMT internals, broker infrastructure, or the full numeric input space.

Those layers remain subject to fault injection, replay, integration, and rule-by-rule tests.

## 3. Order / OMS models

### `formal/OrderFSM.tla`

Models the 14-state order lifecycle including `ABORTED`, `UNKNOWN`, `RECONCILING`, and `MANUAL_REVIEW`.

### `formal/SubmitProtocol.tla`

Models durable submit/cancel reservation, broker side effects, response loss, hard crash before result persistence, restart, reconciliation, partial fill, and fill.

Key properties include at-most-once broker side effect and no blind retry after ambiguity.

### `formal/LeaderLease.tla`

Models competing OMS writers, lease expiry, and fencing epochs.

### `formal/EvidenceReplay.tla`

Models duplicate and out-of-order broker evidence, monotonic lifecycle/fill facts, and replay safety.

### `formal/PreSubmitRecovery.tla`

Models restart while an order is durable but still pre-side-effect.

### `formal/RiskPrecedence.tla`

Models deterministic fail-close risk selection across Global → Account → Strategy → Security/Order precedence.

## 4. BigQMT Bridge API v1 models

Wire/semantic specification:

- [`BRIDGE_API_V1_ZH.md`](BRIDGE_API_V1_ZH.md)
- `schemas/bridge/v1/*.schema.json`

### `formal/BridgeCommandProtocol.tla`

Models durable command publication/claim/terminal states, expiry, account/session gates, SHADOW behavior, simulation side effects, crash/orphan handling, idempotency, and conflicts.

### `formal/BridgeEventProtocol.tla`

Models terminal/account identity, session generation, sequence, duplicate, gap, session switch, `needs_resync`, and clean-snapshot recovery.

### `formal/BrokerEvidenceBoundary.tla`

Models the authority boundary:

```text
command_result            = control-plane evidence
ORDER / DEAL / query      = potential broker lifecycle evidence
```

It proves command results alone cannot promote OMS lifecycle state.

## 5. Broker Evidence Contract v1

Formal specification:

- [`BROKER_EVIDENCE_CONTRACT_V1_ZH.md`](BROKER_EVIDENCE_CONTRACT_V1_ZH.md)
- `schemas/broker_evidence/v1/broker_evidence.schema.json`
- `formal/BrokerEvidenceContract.tla`
- `tools/verify_broker_evidence_contract.py`

This layer is intentionally broker-neutral. It does **not** encode Guojin/Galaxy raw status numbers. Broker-specific mappers must be calibrated separately and may emit `BrokerEvidence v1` only after the contract gates pass.

### `formal/BrokerEvidenceContract.tla`

Finite abstraction covers:

- control-plane results versus broker evidence;
- account/client/broker identity admission;
- calibrated versus unknown raw status;
- source authority for ORDER/DEAL/query;
- exact duplicate replay;
- same-ID/different-semantic-digest conflict;
- cumulative filled quantity;
- ACK/PARTIAL/FILL/CANCEL/REJECT aggregation;
- terminal conflicts;
- fill/cancel races.

Checked invariants include:

- `CommandResultCannotCreateBrokerEvidence`
- `IdentityMismatchNeverMutatesOms`
- `UnknownRawStatusCannotAdvanceOms`
- `DuplicateEvidenceAppliedAtMostOnce`
- `NoBrokerEvidenceNoLifecycle`
- `OutOfOrderEvidenceCannotRegressState`
- `PartialFillCannotRegressToAck`
- `FilledIsAbsorbingUnlessTerminalConflict`
- `CancelSignalCannotCreateCancelled`
- `ConflictingTerminalEvidenceFailsClosed`
- `SemanticConflictFailsClosed`
- `RejectedHasNoFill`
- `CancelledNeverClaimsFullFill`

The formal model uses a finite order quantity abstraction of `2`, where cumulative fill is `0/1/2`. Concrete quantities remain implementation-test territory.

## 6. Broker Evidence Contract semantics

The contract freezes these safety rules:

```text
command_result / submit-return / cancel-return
    != BrokerEvidence
```

Only calibrated:

```text
ORDER callback
DEAL callback
active ORDER query
active DEAL query
```

may produce `BrokerEvidence v1`.

Unknown raw statuses, identity mismatches, quantity inconsistencies, unsupported source/status pairs, and same source-event identity with a different semantic digest fail closed and do not silently mutate OMS.

Broker terminal states are not ordered by timestamp/source priority. Conflicting distinct terminal facts lead to `MANUAL_REVIEW`.

## 7. Implementation / contract conformance

### Order FSM

`tools/verify_fsm_exhaustive.py` independently checks the frozen OMS state-machine relation.

### Bridge protocol

`tools/verify_bridge_protocol_exhaustive.py` checks Host ingress semantics and command-spool idempotency/conflict/expiry.

### Bridge schema drift

`tools/verify_bridge_schema_contract.py` checks wire-version and enum drift between Bridge JSON Schema and implementation constants.

### Broker Evidence contract

`tools/verify_broker_evidence_contract.py` is an implementation-independent finite reference model. It exhaustively checks the contract matrix across current OMS state, broker/control source, target lifecycle fact, cumulative quantity, identity admission, raw-status calibration, and duplicate semantics.

It also asserts that the JSON Schema source/status/evidence enums remain aligned with the frozen contract and that control-plane source names are not admitted by the BrokerEvidence schema.

`tests/qmt/test_broker_evidence_contract.py` validates legal/illegal `BrokerEvidence v1` samples using JSON Schema Draft 2020-12.

No broker-specific mapper is treated as PASS by this Gate yet; that remains the next implementation checkpoint.

## 8. Static broker-side-effect audit

`tools/audit_side_effect_calls.py` remains a structural drift detector.

Generic and `galaxy` production artifacts must continue to expose **zero broker mutation call surface**.

The separately reviewed, fingerprint-pinned `guojin_sim` artifact may contain
bounded simulation mutation logic. Since `p6-guojin-live-canary-7`, `guojin` may
contain only the single explicitly modelled P6 LIVE_CANARY case
(`00700.HGT BUY 100 @ 1.00 HKD`, submit/cancel fuse 1/1); the static audit and
`tests/qmt/test_live_canary_authority_contract.py` reject every broader production
mutation surface, including the retired GC001 and not-yet-authorized 511880 cases.

## 9. Toolchain

CI pins:

- `tla2tools.jar`: **v1.7.4**
- SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Java: Temurin 17

## 10. Gate criteria

A safety-critical candidate cannot PASS unless the exact candidate has:

- full Python test suite green;
- OMS FSM conformance green;
- Bridge protocol conformance green;
- Bridge Schema drift check green;
- Broker Evidence finite contract/schema conformance green;
- broker-side-effect audit green;
- standalone deployment build check green;
- every configured TLC model green;
- no unresolved TLC counterexample;
- no safety-invariant waiver.

A TLC counterexample is a design/model/implementation defect until resolved. The default response is to correct the defect, not weaken the invariant.

## 11. Current gate status

- **P0/G0: PASS**
- **P1 Offline OMS: PASS**
- **P2 Risk Engine: PASS**
- **P3 Big QMT read-only: PASS**
- **P4 SHADOW deployment: PASS**
- **P5 bounded Guojin simulation submit/cancel/fill calibration: PASS**
- **BigQMT Bridge API v1: FORMAL CONTRACT PASS**
- **Broker Evidence Contract v1: PROTOCOL/FORMAL CONTRACT PASS**
- **Guojin simulation raw status mapper: PASS (`guojin_sim` only)**
- **Production Guojin / Galaxy mapper: NOT IMPLEMENTED / NOT AUTHORIZED**
- **Production live trading: NO**
- **Guojin simulation deployment: `p5-simulation-calibration-7`, 20/20 read-only route evidence**
- **Guojin LIVE_CANARY: `p6-guojin-live-canary-7`; ONE NAMED CASE ONLY (`00700.HGT BUY 100 @ 1.00 HKD`), SUBMIT/CANCEL FUSE 1/1; GC001 NO LONGER AUTHORIZED; 511880 READ-ONLY PENDING A SEPARATE GATE**

The Guojin simulation mapper is now implemented under the versioned
`qmt-guojin-sim-20260917-v1` profile. The next execution-safety checkpoints are
durable mapper-registry recovery and separately calibrated production/other-
broker profiles. Those future Gates must not alter the frozen evidence
semantics without a contract/version change.
