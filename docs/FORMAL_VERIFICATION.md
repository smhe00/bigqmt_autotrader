# Formal Verification Gate

Date: 2026-09-13

Status: **MANDATORY PERMANENT GATE**

## 1. Objective

Order execution, recovery and execution-eligibility selection are safety-critical. Unit and fault tests remain necessary, but finite safety protocols are also exhaustively model-checked in CI. A safety-relevant implementation change must update the corresponding model or conformance contract and keep the gate green.

The gate combines:

1. **TLA+ / TLC exhaustive model checking** of finite abstractions.
2. **Independent exhaustive Python/FSM conformance** over every state/request pair.
3. **Static production-surface auditing** of broker side effects, risk evaluation, internal decided-submit entry and evidence aggregation.
4. Runtime transaction/fault/replay/risk tests for boundaries outside the formal abstractions.

## 2. Meaning and boundary of “complete”

For each finite TLA+ abstraction, TLC explores the complete configured abstract state graph rather than sampling scenarios. The Python FSM checker independently enumerates all `14 x 14 = 196` state/request combinations.

This establishes exhaustive properties of the encoded abstractions and a complete finite conformance check of `transition()`. It does **not** prove CPython, SQLite, Windows, QMT, the filesystem, networking, broker infrastructure, or the full numeric input space of the risk engine. Those layers remain subject to fault injection, replay, integration and rule-by-rule tests.

Safety invariants are unconditional within their models. Liveness properties are stated only under the explicit fairness assumptions encoded in the corresponding specification.

## 3. Formal models

### `formal/OrderFSM.tla`

Models the 14-state lifecycle, including `ABORTED`, and checks state typing, total/exclusive event classification, terminal absorption, UNKNOWN/RECONCILING rules, ambiguity non-regression and ABORTED entry constraints. The independent Python conformance checker verifies all **196** current/request pairs.

### `formal/SubmitProtocol.tla`

Models durable submit/cancel reservation, broker side effects, response loss, hard crash before result persistence, restart, reconciliation, partial fill and fill. It checks at-most-once side effects, durable-reservation causality, ambiguity/reconciliation rules, no automatic retry of abandoned reservations and temporal convergence under the model's fairness assumptions.

### `formal/LeaderLease.tla`

Models two OMS contenders, lease expiry and fencing epochs. It checks at most one valid executor, current-owner fencing and loss of authority after expiry. Implementation tests additionally place fence checks inside `BEGIN IMMEDIATE` write transactions.

### `formal/EvidenceReplay.tla`

Models duplicate and out-of-order broker evidence. It checks one aggregate effect per logical evidence identity, monotonic lifecycle/fill facts and terminal-fill non-regression.

### `formal/PreSubmitRecovery.tla`

Models restart while an order is in a durable pre-side-effect state. It checks `CREATED`/`RISK_ACCEPTED` orphan convergence to `ABORTED` and proves the abstraction does not later authorize submit from that aborted identity.

### `formal/RiskPrecedence.tla`

P2 adds a finite abstraction of deterministic fail-close risk selection. It uses **12 representative ordered rule slots** spanning Global, Account, Strategy and Security/Order. TLC exhaustively enumerates every pass/fail assignment to those slots (`2^12 = 4096` distinct failure sets) and checks:

- acceptance occurs only when no modeled rule fails;
- any modeled rule failure forces rejection;
- the selected primary rule is the earliest failed rule in the fixed order;
- primary risk level follows Global -> Account -> Strategy -> Security/Order precedence;
- primary selection is always one of the actual failures.

This model proves precedence/fail-close semantics over the encoded Boolean abstraction. It intentionally does **not** model every `Decimal` boundary value or timestamp; concrete numeric/freshness semantics are covered by Python rule-matrix tests.

## 4. Implementation conformance and static audit

`tools/verify_fsm_exhaustive.py` defines an independent copy of the frozen FSM relation rather than importing implementation-private transition tables. It checks all **196** state/request pairs and graph invariants.

`tools/audit_side_effect_calls.py` fails CI if production source escapes the intended authority boundaries. Through P2 it requires:

- `submit_limit_order()` only in `OfflineOms._submit_decided_intent()`;
- `_submit_decided_intent()` called in production source only from `OfflineOms.submit_intent()`;
- `evaluate_risk()` called in production source only from `OfflineOms.submit_intent()`;
- `cancel_order()` broker side effect only in `OfflineOms.cancel_order()`;
- `merge_broker_fact_in_tx()` only in evidence ingestion;
- `EvidenceJournal(...)` construction only inside `OfflineOms`.

Thus the production submit chain is structurally constrained to:

```text
public submit_intent
  -> evaluate_risk
  -> persist RiskDecision
  -> private decided-submit path
  -> durable SUBMITTING reservation
  -> simulated broker side effect
```

The static audit is a structural drift detector, not a substitute for runtime fencing or tests.

## 5. Toolchain and reproducibility

CI pins:

- `tla2tools.jar`: **v1.7.4**
- SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Java: Temurin 17

The JAR hash is checked before TLC executes.

## 6. Gate criteria

A safety-critical phase candidate cannot PASS unless the exact implementation candidate has:

- Python tests green on supported CI Python versions;
- exhaustive FSM implementation/formal conformance green;
- static authority/surface audit green;
- every configured TLC model green with no unresolved counterexample;
- no safety-invariant waiver;
- transaction/fault/replay/risk tests green for implementation boundaries not represented directly by TLC.

A TLC counterexample is treated as a design/model/implementation defect until resolved. The default response is to correct the defect, not weaken the invariant.

## 7. Gate results

- **P1: PASS.** Evidence: `docs/P1_GATE_RESULT_20260912.md`.
- **P2: PASS.** Evidence: `docs/P2_GATE_RESULT_20260913.md`.

P3 is **NOT STARTED**. Any real Big QMT integration must preserve P1/P2 durable-identity, fencing, ambiguity, replay, risk and fail-close contracts. Adding a read-only or real broker adapter does not waive those contracts and does not itself authorize live trading.
