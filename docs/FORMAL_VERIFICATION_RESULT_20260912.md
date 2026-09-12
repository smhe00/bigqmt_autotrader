# Formal Verification Result — Order State Machine

Date: 2026-09-12

Candidate commit: `3c9270cb4244441d8f4e8e2093ba55a4be3df2fc`

GitHub Actions run: `34695744312`

Result: **PASS — no invariant or temporal-property counterexample**

## 1. Implementation/spec conformance

`tools/verify_fsm_exhaustive.py` exhaustively checked every current/requested status combination against the independent frozen formal transition relation.

Result:

- state/request combinations checked: **169 / 169**;
- applied edges: **23**;
- declared states reachable from `CREATED`: **13 / 13**;
- classification counts:
  - `APPLIED`: 23;
  - `DUPLICATE`: 13;
  - `STALE`: 74;
  - `ILLEGAL`: 59.

The checker also verified:

- no terminal state has an applied exit;
- UNKNOWN's only applied exit is RECONCILING;
- UNKNOWN and RECONCILING have no transitive path back to CREATED/RISK_ACCEPTED/SUBMITTING;
- Python `transition()` agrees with the formal classification for every pair.

## 2. TLC — OrderFSM

Model: `formal/OrderFSM.tla`

Configured checks:

- `TypeOK`;
- `TerminalAbsorption`;
- `ClassificationIsTotalAndExclusive`;
- `TerminalHasNoAppliedExit`;
- `UnknownOnlyExitsToReconciling`;
- `NoReturnToPreSubmitFromAmbiguity`.

TLC result:

- **Model checking completed. No error has been found.**
- states generated: **124**;
- distinct reachable states: **13**;
- states left on queue: **0**;
- complete-state-graph depth: **6**.

## 3. TLC — SubmitProtocol

Model: `formal/SubmitProtocol.tla`

Safety invariants checked:

- `TypeOK`;
- `AtMostOneSubmit`;
- `SubmitSideEffectRequiresReservation`;
- `BrokerOrderRequiresSubmit`;
- `KnownBrokerLifecycleHasBroker`;
- `CrashedSessionIsNotReconciled`;
- `UnknownMustPassReconcile`;
- `AbandonedReservationNeverResubmitted`;
- `PostSubmitNeverReturnsToRisk`.

Temporal properties checked under the explicit strong-fairness assumptions in the spec:

- `UnknownEventuallyBeginsReconcile`;
- `ReconcilingEventuallySettles`.

TLC result:

- **Model checking completed. No error has been found.**
- states generated: **149**;
- distinct reachable states: **51**;
- states left on queue: **0**;
- complete-state-graph depth: **9**;
- temporal-property branches checked: **2**.

## 4. Counterexample-driven correction during verification

The first formal CI run did not pass. TLC detected that `Restart` did not syntactically assign `abandonedReservation'` on every parsed branch because the intended Boolean RHS was not explicitly parenthesized. The model was corrected so the next-state relation is total. The corrected model was then rerun from a clean CI checkout and passed the complete state-space and temporal checks above.

This failed-first run is retained in Git history as evidence that the formal gate is active rather than decorative.

## 5. Verification boundary

This PASS means the following claim is justified:

> For the finite abstractions encoded in `OrderFSM.tla` and `SubmitProtocol.tla`, TLC exhaustively explored all reachable abstract states and found no violation of the configured safety invariants or temporal properties; the current Python `transition()` implementation also matches the frozen state-transition contract for all 169 possible status-request pairs.

It does **not** prove the correctness of CPython, SQLite, the filesystem, Windows, QMT, broker infrastructure, networking, or code outside the modeled abstraction.

Those layers remain subject to crash injection, replay testing, integration testing, and later formal-model extensions.

## 6. Gate decision

**STATE-MACHINE FORMAL VERIFICATION: PASS**

This becomes a permanent required CI gate. P1 itself remains **IN PROGRESS** because cancellation execution/recovery, leader ownership, migrations, callback dedup/replay, and broader fault injection are still incomplete.
