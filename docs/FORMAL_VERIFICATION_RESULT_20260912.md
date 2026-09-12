# Formal Verification Result — P1 Safety Protocols

Date: 2026-09-12

Implementation candidate: `195c2f675a7b9f01667c3146e09c4bd941e95d98`

GitHub Actions run: `34700851624`

Result: **PASS — no configured invariant or temporal-property counterexample**

## 1. Python/FSM conformance

`tools/verify_fsm_exhaustive.py` independently checked every current/requested status combination against the frozen formal relation.

Result:

- state/request combinations: **196 / 196 PASS**;
- declared states: **14 / 14 reachable**;
- applied edges: **25**;
- classification counts:
  - `APPLIED`: 25;
  - `DUPLICATE`: 14;
  - `STALE`: 92;
  - `ILLEGAL`: 65.

The checker also confirmed terminal absorption, UNKNOWN-only-via-RECONCILING recovery, no ambiguity path back to pre-submit execution opportunity, and the restricted `ABORTED` entry policy.

## 2. Static execution/write-surface audit

`tools/audit_side_effect_calls.py`: **PASS**.

Observed production surfaces on the candidate:

- `submit_limit_order`: `oms/service.py:submit_intent()` only;
- `cancel_order`: `oms/service.py:cancel_order()` only;
- `merge_broker_fact_in_tx`: `oms/evidence.py:ingest()` only;
- `EvidenceJournal`: constructed only by `oms/service.py:__init__()`.

## 3. TLC — `OrderFSM`

Result:

- **No error found**;
- states generated: **146**;
- distinct reachable states: **14**;
- queue remaining: **0**;
- complete graph depth: **6**.

## 4. TLC — `SubmitProtocol`

The final P1 model includes durable submit/cancel reservation, response loss, accepted/not-accepted broker side effects before result persistence, hard crash, restart, reconciliation, fill and cancel races.

Result:

- **No error found**;
- states generated: **302**;
- distinct reachable states: **105**;
- queue remaining: **0**;
- complete graph depth: **12**;
- temporal-property satisfiability branches: **2**, both checked successfully.

Key configured safety claims include at-most-one submit, at-most-one cancel, reservation-before-side-effect, broker causality, no automatic retry after ambiguity/crash, and no return from post-submit lifecycle to risk/pre-submit states.

## 5. TLC — `LeaderLease`

Result:

- **No error found**;
- states generated: **234**;
- distinct reachable states: **73**;
- queue remaining: **0**;
- complete graph depth: **9**.

The model verifies single valid executor and fencing semantics. Implementation tests additionally verify the SQLite transactional linearization point: the current leader token is checked after `BEGIN IMMEDIATE`, before every OMS durable write.

## 6. TLC — `EvidenceReplay`

Result:

- **No error found**;
- states generated: **33**;
- distinct reachable states: **8**;
- queue remaining: **0**;
- complete graph depth: **4**.

The model checks deduplication and monotonic aggregate facts under duplicate/out-of-order evidence.

## 7. TLC — `PreSubmitRecovery`

Result:

- **No error found**;
- states generated: **47**;
- distinct reachable states: **19**;
- queue remaining: **0**;
- complete graph depth: **7**;
- temporal-property branches: **1**, checked successfully.

This model proves the fail-safe pre-side-effect restart policy: a stale `CREATED`/`RISK_ACCEPTED` intent without a submit reservation becomes terminal `ABORTED` and cannot later produce a submit side effect.

## 8. Runtime/fault boundary verification

Formal checking is complemented by Python tests on the same candidate. The P1 suite reports **75 passed** on both CPython 3.11 and CPython 3.12. It includes:

- timeout before/after broker acceptance;
- hard crash before/after submit acceptance;
- hard crash before/after cancel acceptance;
- crash after durable submit/cancel reservation but before the driver call;
- SQLite write failure before side effects;
- ACK persistence failure after side effects;
- atomic rollback of aggregate/event/dedup evidence if evidence persistence fails;
- leader takeover and stale-writer fencing;
- duplicate/out-of-order callback replay;
- broker-ID and fill-quantity conflict handling;
- migration/version fail-close behavior.

## 9. Historical counterexample-driven corrections

Formal and CI gates have caught real defects during P1 development, including an incomplete TLA+ next-state assignment and implementation/test mismatches around restart semantics. Those failures were corrected and rerun rather than waived. The history is intentionally retained.

## 10. Verification boundary

This result justifies the following bounded claim:

> For the finite abstractions encoded in the five P1 TLA+ models, TLC exhaustively explored the complete configured reachable state spaces and found no configured safety or temporal-property violation; the Python order transition function also matches the independent 14-state formal contract for all 196 state/request pairs, and the implementation fault/replay suite passes on the supported CI runtimes.

It does **not** prove CPython, SQLite, Windows, QMT, networking, the broker, or future code outside these abstractions. Real-QMT phases require their own integration and operational gates.

## 11. Decision

**P1 FORMAL/SAFETY VERIFICATION: PASS**

This is not authorization for live trading. The repository still contains no enabled real-QMT submit/cancel path.
