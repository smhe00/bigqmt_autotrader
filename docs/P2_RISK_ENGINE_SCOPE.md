# P2 Scope — Deterministic Fail-Closed Risk Engine

Date: 2026-09-12

Status: **NORMATIVE P2 SCOPE**

Prerequisite: **P1 PASS**

Safety boundary: P2 is offline/simulated. It does not add or enable a real Big QMT submit/cancel path.

## 1. Goal

Implement the four-level pre-trade risk contract as a deterministic pure evaluation layer:

1. **Global**
2. **Account**
3. **Strategy**
4. **Security / Order**

For the same immutable `OrderIntent`, `RiskPolicy` and `RiskSnapshot`, evaluation must produce the same ordered findings, primary reason code and canonical snapshot hash.

The engine is fail-closed: unavailable, stale, contradictory or unauthorized inputs reject new execution eligibility rather than infer a permissive state.

## 2. P2 execution-mode boundary

The runtime-mode vocabulary is:

- `DISABLED`
- `OBSERVE`
- `SHADOW`
- `SIMULATION`
- `LIVE_CANARY`
- `LIVE_ARMED`

In P2, `RiskPolicy.permitted_execution_modes` is structurally constrained to **exactly `{SIMULATION}`**. Construction of a P2 policy fails if it attempts to authorize `SHADOW`, `LIVE_CANARY`, `LIVE_ARMED`, or any mixed execution-mode set.

The live mode names remain in the vocabulary so later phase contracts do not require incompatible enums; they are **not enabled by P2** and are not authorization for live trading. Any later capability that permits `LIVE_CANARY` or `LIVE_ARMED` requires an explicit contract/code/formal-gate change in a later phase; it cannot be opened by configuration alone.

## 3. Immutable inputs

### `OrderIntent`

The existing durable P0/P1 intent remains the requested action.

### `RiskPolicy`

Policy includes deterministic limits and freshness requirements, including:

- rule version;
- expected account fingerprint;
- permitted execution modes;
- whether QMT health is required;
- maximum data ages;
- minimum cash buffer and fee buffer;
- account/strategy/security/order notional limits;
- daily loss/turnover/order/cancel limits;
- strategy allow-list/version/universe/budget;
- maximum price deviation from the supplied reference price.

All monetary/rate values use `Decimal`; binary float is forbidden.

### `RiskSnapshot`

The snapshot supplies facts; it never grants authority. It includes:

- current runtime mode and health flags;
- reconciliation/leader/database state;
- account fingerprint, cash, gross exposure and account-data timestamp;
- daily PnL, turnover, order count and cancel count;
- strategy heartbeat, current strategy exposure, current strategy exposure for the requested security, turnover and position count;
- security market facts: tick, price limits, reference price, market-data timestamp, lot size, sellable quantity and current security exposure;
- currently blocked/ambiguous symbols and account-wide ambiguity flag.

P2 does not fetch these values from QMT. Tests construct snapshots directly. P3/P4 adapters must later populate the same contract without weakening it.

## 4. Deterministic rejection order

Findings are emitted in this fixed level/rule order. The first finding becomes `RiskDecision.reason_code`; all findings remain available in the in-memory `RiskEvaluation` audit object.

### Global

1. database health;
2. OMS health;
3. leader ownership;
4. startup reconciliation complete;
5. execution mode permitted;
6. required QMT health;
7. account-wide ambiguity;
8. market open;
9. daily loss limit;
10. daily turnover limit;
11. daily order-count limit;
12. daily cancel-count limit.

### Account

1. account fingerprint match;
2. account snapshot freshness;
3. minimum cash buffer;
4. projected account exposure.

### Strategy

1. strategy ID/version allow-list;
2. strategy heartbeat freshness;
3. symbol universe;
4. projected strategy exposure/budget;
5. strategy turnover limit;
6. strategy position-count limit.

### Security / Order

1. intent expiry;
2. supported market suffix (`.SH`, `.SZ`, `.BJ`);
3. market-data freshness;
4. symbol-level ambiguity block;
5. tick-size validity;
6. price-band validity;
7. reference-price deviation limit;
8. lot-size validity;
9. projected single-order notional;
10. projected per-security exposure;
11. BUY available-cash + fee-buffer rule;
12. SELL explicit sellable-quantity rule.

Input dataclasses reject impossible types/ranges before rule evaluation. Runtime absence/staleness is a risk rejection, not a Python default value.

## 5. Reason codes and rule IDs

The existing append-only `RiskReasonCode` namespace remains authoritative. P2 does not silently repurpose codes.

Fine-grained rule identity is carried separately by stable `rule_id` strings while the persisted primary `RiskReasonCode` uses the existing semantic buckets, for example:

- health/freshness -> `RISK_DATABASE_UNHEALTHY`, `RISK_LEADER_NOT_HELD`, `RISK_DATA_STALE`;
- runtime mode -> `RISK_MODE_NOT_ARMED`;
- ambiguity -> `RISK_UNKNOWN_ORDER`;
- account mismatch -> `RISK_ACCOUNT_MISMATCH`;
- strategy authorization -> `RISK_STRATEGY_NOT_ALLOWED`;
- market session -> `RISK_MARKET_CLOSED`;
- expiry -> `RISK_INTENT_EXPIRED`;
- malformed tick/price/lot/security -> `RISK_INVALID_ORDER`;
- numeric budgets/cash/position/activity limits -> `RISK_LIMIT_EXCEEDED`.

This preserves stable audit semantics while allowing specific deterministic diagnostics.

## 6. Snapshot hashing

`RiskDecision.snapshot_hash` is SHA-256 over a canonical JSON representation of the immutable `RiskSnapshot`.

Rules:

- dataclass field names are explicit;
- enums serialize by value;
- `Decimal` serializes as exact decimal text;
- datetimes serialize as timezone-aware ISO-8601 strings normalized to UTC;
- sets/frozensets serialize in sorted order;
- maps are key-sorted;
- binary floats are forbidden from risk models.

`rule_version` identifies the policy contract; policy version mutation without changing `rule_version` is a release-process violation.

## 7. OMS authority boundary

The public OMS submit API accepts `(OrderIntent, RiskSnapshot, RiskPolicy)`. It evaluates risk internally, persists the resulting `RiskDecision`, and only an accepted decision may proceed to durable submit reservation.

Production callers cannot pass a preconstructed accepted `RiskDecision` through the public submit API. The old decision-injection path is retained only as a private P1 mechanics hook used by tests. Static CI audits the production source so this private path is reachable only from the public OMS risk-evaluation path.

## 8. P2 non-goals

P2 does not implement:

- QMT query/callback access;
- real positions/cash retrieval;
- exchange-calendar download;
- dynamic tick/price-limit calculation;
- live mode unlock;
- live submit/cancel;
- margin, options, futures, Stock Connect or algorithmic orders.

Market-specific values are supplied as risk snapshot facts and validated, not guessed.

## 9. Required verification

P2 cannot PASS without:

- rule-by-rule unit tests;
- deterministic primary-reason precedence tests;
- stale/missing/unhealthy fail-close tests;
- Decimal/no-float tests;
- BUY cash and SELL sellable-quantity tests;
- ambiguity-block tests;
- canonical snapshot-hash stability tests;
- integration test proving a rejected public OMS submission causes zero simulated broker calls;
- integration test proving the public OMS path owns risk evaluation and persists its decision before execution eligibility;
- P2 policy construction rejecting non-simulation execution authority;
- finite formal model of level precedence/fail-close behavior added to mandatory CI;
- P1 formal/fault gates remaining green.

## 10. Exit criterion

P2 may PASS when the engine is deterministic and fail-closed for every implemented rule, the formal precedence model has no counterexample, rejected decisions cannot reach the simulated broker side-effect surface, the public OMS submit path owns risk evaluation, and no real QMT capability has been added.
