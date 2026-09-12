# P2 Deterministic Risk Engine — Implementation Report

Date: 2026-09-13

Phase: **P2 — Deterministic Fail-Closed Risk Engine**

Status: **PASS**

Safety boundary: offline/simulated only. No Big QMT read-only adapter, real submit, real cancel, credentials or live-mode unlock was added.

## Implemented

### Immutable risk contract

P2 adds immutable models for:

- `RuntimeMode` and `RiskLevel`;
- `StrategyPolicy` and `RiskPolicy`;
- account, strategy and security risk snapshots;
- aggregate `RiskSnapshot`;
- ordered `RiskFinding` and `RiskEvaluation`.

Monetary values and rates use `Decimal`; binary float input is rejected. Timestamps must be timezone-aware. Snapshot models reject structurally contradictory values such as a strategy's security exposure exceeding total strategy exposure.

### Four-level deterministic engine

`evaluate_risk()` evaluates a fixed sequence:

1. Global
2. Account
3. Strategy
4. Security / Order

All failed rules are returned in deterministic order. The first finding supplies the durable primary `RiskReasonCode`. The stable append-only reason-code namespace is preserved while more specific diagnostics use stable `rule_id` values.

Implemented checks include health/reconciliation/leader state, execution mode, optional QMT-health requirement, ambiguity blocks, market-open state, daily loss/activity limits, account identity/freshness/cash/exposure, strategy identity/version/universe/heartbeat/budgets, intent expiry, market-data freshness, A-share market suffixes, tick/band/reference deviation, lot sizes, order/security exposure, BUY cash+fee buffer and SELL sellable quantity.

### Risk-reducing SELL semantics

Strategy snapshots carry explicit current exposure for the requested security. Projected account/strategy/security exposure calculations use that fact so a valid SELL can reduce risk without being misclassified by naive total-exposure arithmetic.

### Canonical risk evidence

`RiskDecision.snapshot_hash` is SHA-256 over canonical JSON:

- exact decimal text;
- enums by value;
- aware datetimes normalized to UTC;
- sorted set/frozenset contents;
- deterministic map ordering.

Equivalent snapshots therefore produce stable hashes independent of set iteration order.

### OMS-owned risk authority

The public `OfflineOms.submit_intent()` accepts `OrderIntent`, `RiskSnapshot` and `RiskPolicy`; it does not accept a caller-supplied accepted `RiskDecision`.

The OMS:

1. confirms leader/reconciliation authority;
2. evaluates risk internally;
3. persists the resulting `RiskDecision`;
4. returns `RISK_REJECTED` with zero broker calls if rejected;
5. only after acceptance enters the P1 durable submit-reservation path.

The prior P1 decision-injection path survives only as a private test/mechanics hook. Production-source static audit prevents another production call site from reaching it.

### P2 execution-mode lock

Although the shared runtime-mode enum contains future names such as `LIVE_CANARY` and `LIVE_ARMED`, a P2 `RiskPolicy` must have:

```text
permitted_execution_modes == {SIMULATION}
```

Any other execution-authority set fails policy construction. Later live capability therefore requires a deliberate later-phase contract/code/Gate change; it cannot be enabled by configuration alone.

## Verification

Verified implementation candidate: `5e980bb67280dbb0db66c7cde2e1bfe9b53de4c4`

GitHub Actions run: `34711007532`

Results:

- CPython 3.11: **112 passed**;
- CPython 3.12: **112 passed**;
- FSM implementation/formal conformance: **196 / 196 PASS**;
- static side-effect/risk-bypass/evidence-surface audit: **PASS**;
- TLC `OrderFSM`: **PASS**;
- TLC `SubmitProtocol`: **PASS**;
- TLC `LeaderLease`: **PASS**;
- TLC `EvidenceReplay`: **PASS**;
- TLC `PreSubmitRecovery`: **PASS**;
- TLC `RiskPrecedence`: **PASS**.

`RiskPrecedence` exhaustively checks all `2^12 = 4096` pass/fail combinations of 12 representative ordered rule slots spanning all four risk levels. TLC generated 8192 states, found 4096 distinct states, and left zero states on the queue with no counterexample.

## P2 boundary

P2 deliberately does **not** implement:

- Big QMT query or callback access;
- QMT account/position/order/trade retrieval;
- a real broker adapter;
- QMT submit/cancel;
- credentials or account configuration;
- live-mode lease/unlock;
- P3 field calibration.

`qmt_side/BIGQMT_EXECUTION_BRIDGE.py` therefore remains fail-closed.

## Gate decision

**P2: PASS.**

The next architectural phase is P3 read-only Big QMT integration, but P3 remains **NOT STARTED** at this checkpoint.
