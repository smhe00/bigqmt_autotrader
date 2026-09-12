# Formal Verification Gate for the Order State Machine

Date: 2026-09-12

Status: **MANDATORY GATE — required before P1 can PASS**

## 1. Verification objective

The order lifecycle is safety-critical. Unit tests are necessary but insufficient. The project therefore treats the designed order state machine and its submit/recovery protocol as formally specified finite-state systems and requires exhaustive model checking in CI.

The gate has two independent layers:

1. **TLA+ / TLC model checking** of the abstract design.
2. **Exhaustive implementation-conformance checking** of every `(current_status, requested_status)` pair against the frozen formal contract.

A change to order states, allowed transitions, stale-event handling, UNKNOWN recovery, cancel semantics, submit idempotency, or terminal behavior MUST update and pass both layers.

## 2. Scope and meaning of “complete”

Within the finite abstraction defined by the TLA+ models, TLC explores the entire reachable state space rather than a sample of scenarios. The Python conformance checker separately enumerates all `13 x 13 = 169` state/request combinations.

This is a complete verification of the **abstract state-machine model and its refinement relation to the Python transition function**. It is not a mathematical proof of CPython, SQLite, Windows, QMT, the broker gateway, the operating system, or the network stack. Those components require separate fault testing and integration gates.

Safety properties are required unconditionally in the model. Liveness properties are proved under explicit fairness assumptions: a crashed process is eventually restarted and an enabled reconciliation action that remains/repeatedly becomes possible is eventually executed.

## 3. Formal models

### `formal/OrderFSM.tla`

Models the 13-state order lifecycle and verifies:

- state type correctness;
- total and mutually exclusive classification of every state/request pair as `APPLIED`, `DUPLICATE`, `STALE`, or `ILLEGAL`;
- terminal-state absorption;
- no applied exit from a terminal state;
- `UNKNOWN` has exactly one applied exit: `RECONCILING`;
- ambiguity states cannot return to `CREATED`, `RISK_ACCEPTED`, or `SUBMITTING`;
- duplicate/stale evidence cannot downgrade aggregate state.

### `formal/SubmitProtocol.tla`

Models the submit/restart/reconciliation protocol around the state machine and verifies:

- at most one submit side-effect call per durable order identity;
- a submit side effect cannot occur before the durable reservation;
- a broker order cannot exist unless the submit reservation and one submit call exist;
- known broker lifecycle states imply broker existence;
- a crashed session is never considered reconciled;
- an UNKNOWN epoch cannot bypass `RECONCILING`;
- a reservation abandoned by crash before submit is never automatically resubmitted;
- a reserved/post-submit lifecycle never returns to pre-submit risk states;
- under strong fairness, UNKNOWN eventually starts reconciliation;
- under strong fairness, RECONCILING eventually converges to broker evidence or `MANUAL_REVIEW` in the abstract recovery model.

The second model includes crash/restart interleavings, response loss before broker acceptance, response loss after broker acceptance, broker rejection, cancellation ambiguity, partial fill, fill, and reconciliation.

## 4. Implementation conformance

`tools/verify_fsm_exhaustive.py` intentionally defines an independent copy of the frozen formal transition relation. It does **not** import the implementation's private `_ALLOWED` or `_STALE` tables.

For all 169 state/request pairs it asserts that `transition()` exactly matches the formal classification and result:

- `APPLIED` must change to the requested state;
- `DUPLICATE` must stutter with `DUPLICATE_IGNORED`;
- `STALE` must stutter with `STALE_IGNORED`;
- `ILLEGAL` must raise `InvalidTransition`.

It additionally proves by exhaustive graph traversal that:

- every declared state is reachable from `CREATED` through applied transitions;
- no terminal state has an applied exit;
- UNKNOWN's only applied target is RECONCILING;
- neither UNKNOWN nor RECONCILING has any transitive path back to pre-submit states.

This checker is deliberately redundant with the TLA+ relation. Redundancy is the drift detector: changing implementation or specification alone must break CI.

## 5. Toolchain and reproducibility

CI pins the stable TLA+ tools artifact:

- `tla2tools.jar`: v1.7.4
- SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Java: Temurin 17 in CI

The JAR hash is verified before TLC runs. The binary is downloaded during CI and is not committed to the repository.

## 6. Gate criteria

P1 may not be declared PASS unless all of the following are green on the exact candidate commit:

- normal Python unit/state-machine/fault tests;
- exhaustive 169-pair implementation-conformance checker;
- TLC `OrderFSM` model check with all configured invariants;
- TLC `SubmitProtocol` model check with all configured invariants and temporal properties;
- no unresolved TLC counterexample;
- no waiver for a safety invariant;
- formal models and implementation reviewed for semantic equivalence after any state-machine change.

A TLC counterexample is a design defect until demonstrated otherwise. The default response is to fix the model/design/implementation, not to weaken the invariant.

## 7. Future extension

Before opening real Big QMT trading capability, the formal model must be extended to cover at minimum:

- cancel-call at-most-once semantics and cancel-response loss;
- leader/lease ownership and two-OMS contention;
- callback/event deduplication identity;
- external/manual broker orders and reconciliation;
- symbol/account-level UNKNOWN blocking;
- trading-session unlock/lease expiry.

Those extensions belong to later P1/P4 gates and do not authorize live trading.
