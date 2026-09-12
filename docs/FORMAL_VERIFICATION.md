# Formal Verification Gate

Date: 2026-09-12

Status: **MANDATORY PERMANENT GATE**

## 1. Objective

Order execution and recovery are safety-critical. Unit and fault tests remain necessary, but finite safety protocols are also exhaustively model-checked in CI. A safety-relevant implementation change must update the corresponding model or conformance contract and keep the gate green.

The gate combines:

1. **TLA+ / TLC exhaustive model checking** of finite abstractions.
2. **Independent exhaustive Python/FSM conformance** over every state/request pair.
3. **Static write-surface auditing** of broker side effects and internal evidence aggregation entry points.
4. Runtime transaction/fault/replay tests for boundaries outside the formal abstractions.

## 2. Meaning and boundary of “complete”

For each finite TLA+ abstraction, TLC explores the complete reachable abstract state graph configured by the model rather than sampling scenarios. The Python FSM checker independently enumerates all `14 x 14 = 196` state/request combinations.

This establishes exhaustive properties of the encoded abstractions and a complete finite conformance check of `transition()`. It does **not** prove CPython, SQLite, Windows, QMT, the filesystem, networking, or broker infrastructure. Those layers remain subject to fault injection, replay, integration and operational gates.

Safety invariants are unconditional within their models. Liveness properties are stated only under the explicit fairness assumptions encoded in the corresponding specification.

## 3. Formal models

### `formal/OrderFSM.tla`

Models the 14-state lifecycle, including `ABORTED`, and checks:

- state type correctness;
- total/exclusive classification of every state/request pair;
- terminal absorption and no applied terminal exits;
- `UNKNOWN` exits only to `RECONCILING`;
- ambiguity cannot return to pre-submit execution opportunity;
- only `CREATED` or `RISK_ACCEPTED` may enter `ABORTED`.

The Python conformance checker verifies the same finite relation independently for all **196** pairs.

### `formal/SubmitProtocol.tla`

Models durable reservation, submit/cancel side effects, response loss, hard crash before result persistence, restart, reconciliation, partial fill and fill. It checks, among other properties:

- at most one submit call per durable identity;
- at most one cancel call per cancel reservation;
- submit/cancel side effects require their durable reservations;
- broker existence/cancellation is causally consistent with side effects;
- crashed sessions are not considered reconciled;
- ambiguity passes through `RECONCILING`;
- abandoned reservations do not authorize automatic re-submit/re-cancel;
- post-submit lifecycle cannot return to pre-submit risk states;
- under explicit strong fairness, UNKNOWN begins reconciliation and reconciliation settles.

The hard-crash model includes both accepted and not-accepted broker-call outcomes while the durable phase remains `SUBMITTING`/`CANCEL_PENDING` because result persistence has not yet happened.

### `formal/LeaderLease.tla`

Models two OMS contenders, lease expiry and fencing epochs. It checks:

- at most one valid executor;
- no execution authority without a live owner;
- the live owner has the current fencing epoch;
- the other session is fenced;
- an expired lease cannot authorize execution.

Implementation tests additionally place the fence check **inside `BEGIN IMMEDIATE` write transactions**, closing the race between a service-level assertion and a durable write.

### `formal/EvidenceReplay.tla`

Models duplicate and out-of-order broker evidence. It checks that:

- a logical evidence identity affects aggregate state at most once;
- aggregate lifecycle facts do not regress;
- filled quantity is monotonic;
- terminal fill cannot be downgraded by replay.

### `formal/PreSubmitRecovery.tla`

Models restart while a durable order is still pre-side-effect. It checks that:

- `CREATED`/`RISK_ACCEPTED` without a submit reservation terminate as `ABORTED` after restart;
- an aborted order cannot later generate a submit side effect;
- recovery does not silently convert a stale pre-submit intent into executable authority.

## 4. Implementation conformance and static audit

`tools/verify_fsm_exhaustive.py` defines an independent copy of the frozen formal relation rather than importing the implementation's private transition tables. It exhaustively checks all **196** state/request pairs and graph invariants.

`tools/audit_side_effect_calls.py` fails CI if production write surfaces escape the intended OMS boundary. At the P1 gate it requires:

- `submit_limit_order()` only in `OfflineOms.submit_intent()`;
- `cancel_order()` only in `OfflineOms.cancel_order()`;
- `merge_broker_fact_in_tx()` only in evidence ingestion;
- `EvidenceJournal(...)` construction only inside `OfflineOms`.

This is a structural drift detector, not a substitute for runtime fencing.

## 5. Toolchain and reproducibility

CI pins:

- `tla2tools.jar`: **v1.7.4**
- SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Java: Temurin 17

The JAR hash is checked before TLC executes.

## 6. Gate criteria

A safety-critical phase candidate cannot PASS unless the exact candidate commit has:

- Python tests green on supported CI Python versions;
- exhaustive FSM implementation/formal conformance green;
- static side-effect/write-surface audit green;
- every configured TLC model green with no unresolved counterexample;
- no safety-invariant waiver;
- transaction/fault/replay tests green for implementation boundaries not represented directly by TLC.

A TLC counterexample is treated as a design/model/implementation defect until resolved. The default response is to correct the defect, not weaken the invariant.

## 7. P1 result and future extension

P1 satisfies this gate. Exact evidence is recorded in `docs/P1_GATE_RESULT_20260912.md` and `docs/FORMAL_VERIFICATION_RESULT_20260912.md`.

Later phases must extend the models before capability expansion where appropriate. In particular, real Big QMT integration must preserve the P1 durable-identity, fencing, ambiguity, replay, and fail-close contracts; adding a real broker adapter does not waive them and does not itself authorize live trading.
