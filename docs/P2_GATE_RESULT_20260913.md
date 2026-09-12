# P2 Gate Result — Deterministic Fail-Closed Risk Engine

Date: 2026-09-13

Verified implementation candidate: `5e980bb67280dbb0db66c7cde2e1bfe9b53de4c4`

GitHub Actions run: `34711007532`

Decision: **PASS**

## 1. Scope decision

P2 is judged only against `docs/P2_RISK_ENGINE_SCOPE.md`. It remains an offline/simulated phase and does not authorize or implement real QMT capability.

## 2. Exit-criterion matrix

| Requirement | Evidence | Result |
| --- | --- | --- |
| Deterministic four-level risk evaluation | fixed Global -> Account -> Strategy -> Security/Order engine; repeat-input equality tests | PASS |
| Rule-by-rule behavior | risk unit matrix covers health, freshness, ambiguity, limits, security/order validity, BUY/SELL rules | PASS |
| Deterministic primary reason | ordered findings tests + formal precedence model | PASS |
| Fail-close stale/unhealthy/contradictory inputs | explicit stale/future/health/cross-snapshot tests | PASS |
| Decimal/no binary float | model validation and tests | PASS |
| Canonical snapshot hash | deterministic canonical JSON + set-order stability tests | PASS |
| BUY cash + fee buffer | explicit rule/test | PASS |
| SELL sellable quantity and risk-reducing exposure | explicit rules/tests with per-security strategy exposure | PASS |
| Ambiguity blocks | account-wide and symbol-level tests | PASS |
| OMS owns risk authority | public submit accepts snapshot/policy, internally calls `evaluate_risk`, persists decision before execution path | PASS |
| Rejection has zero broker submit | public OMS integration test | PASS |
| Caller cannot configure live execution in P2 | `RiskPolicy` requires exactly `{SIMULATION}` | PASS |
| Static production authority audit | submit/evaluate/private-hook/evidence call surfaces checked in CI | PASS |
| P1 safety/fault/formal gates remain green | same CI run executes all P1 tests/models | PASS |
| Risk precedence formal model | TLC `RiskPrecedence` | PASS |
| No real QMT capability added | QMT bridge remains fail-closed; no P3 adapter | PASS |

## 3. Python and static verification

On both supported CI interpreters:

- CPython 3.11: **112 passed**;
- CPython 3.12: **112 passed**.

Independent FSM conformance remains:

- **196 / 196** state/request pairs;
- 14 / 14 states reachable;
- 25 applied edges;
- classification: 25 applied, 14 duplicate, 92 stale, 65 illegal.

Static production-surface audit: **PASS**. The audited chain is:

```text
OfflineOms.submit_intent
  -> evaluate_risk
  -> OfflineOms._submit_decided_intent
  -> SimulatedDriver.submit_limit_order
```

with broker cancel and evidence aggregation likewise restricted to their intended OMS locations.

## 4. TLC results

All mandatory models completed with zero unresolved counterexamples:

| Model | Generated states | Distinct states | Depth / property | Result |
| --- | ---: | ---: | --- | --- |
| `OrderFSM` | 146 | 14 | depth 6 | PASS |
| `SubmitProtocol` | 302 | 105 | depth 12; 2 temporal branches | PASS |
| `LeaderLease` | 234 | 73 | depth 9 | PASS |
| `EvidenceReplay` | 33 | 8 | depth 4 | PASS |
| `PreSubmitRecovery` | 47 | 19 | depth 7; temporal property | PASS |
| `RiskPrecedence` | 8192 | 4096 | all `2^12` representative failure sets | PASS |

`RiskPrecedence` proves fail-close and primary-rule/level precedence over its finite Boolean abstraction. Numeric risk-boundary correctness is covered by Python rule tests rather than claimed as part of that finite proof.

## 5. Safety boundary retained

At this gate:

- live trading allowed: **NO**;
- real QMT submit implemented: **NO**;
- real QMT cancel implemented: **NO**;
- Big QMT read-only adapter implemented: **NO**;
- P3 started: **NO**.

The future runtime-mode names do not weaken this boundary because P2 policy construction accepts execution authority for `SIMULATION` only.

## 6. Gate decision

**P2 — PASS**

P0/G0 and P1 remain PASS. Development is intentionally stopped at the boundary immediately before P3.
