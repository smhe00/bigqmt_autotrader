# P1 Gate Result — Crash-Recoverable Offline OMS

Date: 2026-09-12

Decision: **PASS**

Scope: **P1 only — simulated broker, no Big QMT execution**

## Candidate and evidence

Implementation candidate:

`195c2f675a7b9f01667c3146e09c4bd941e95d98`

GitHub Actions run:

`34700851624`

The candidate is the code baseline used for the final P1 implementation/fault/formal audit. Subsequent P1-closing commits only update phase documentation and must themselves keep the same CI gates green.

## Exit criteria

P1's normative exit criterion is:

> Every forced-crash boundary must restart into an explainable state, and no failure path may produce a second simulated broker submit for the same durable client order identity.

Decision: **SATISFIED**.

Evidence includes:

- durable submit/cancel reservation before side effect;
- no blind retry from UNKNOWN;
- pre-side-effect restart -> ABORTED or fail-close invariant violation;
- hard crash before/after broker acceptance;
- hard crash after reservation but before driver call;
- ACK persistence failure after broker side effect;
- SQLite rollback before broker side effect;
- callback/reconciliation dedup and monotonic broker facts;
- atomic evidence journal + aggregate rollback;
- transactional leader fencing and stale-writer takeover tests;
- static CI audit limiting broker side-effect call sites.

## Automated verification

Python test suite on the implementation candidate:

- CPython 3.11: **75 passed**;
- CPython 3.12: **75 passed**.

Finite implementation/spec conformance:

- **14** order states;
- **25** applied edges;
- **196 / 196** state/request pairs checked;
- **14 / 14** states reachable.

TLC model checking:

| Model | Generated | Distinct | Depth | Result |
| --- | ---: | ---: | ---: | --- |
| OrderFSM | 146 | 14 | 6 | PASS |
| SubmitProtocol | 302 | 105 | 12 | PASS |
| LeaderLease | 234 | 73 | 9 | PASS |
| EvidenceReplay | 33 | 8 | 4 | PASS |
| PreSubmitRecovery | 47 | 19 | 7 | PASS |

All queues were exhausted and no configured safety or temporal-property counterexample was found.

## Architectural guarantees established for later phases

Later phases must preserve these P1 contracts:

1. Durable identity exists before external side effect.
2. Submit/cancel side effects are reserved durably before invocation.
3. Ambiguous results do not trigger blind retries.
4. Restart reconciles durable ambiguity before new exposure is accepted.
5. One active OMS writer is enforced by fencing.
6. Every OMS durable write is leader-checked inside the SQLite write transaction.
7. Callback/query broker facts share one monotonic normalization contract.
8. Evidence replay is auditable and idempotent.
9. Contradictory broker facts fail closed.
10. Pre-side-effect orphan intents never silently resume after restart.

## Boundary of this PASS

This PASS does not claim correctness of Windows, QMT, broker infrastructure, networking, or future adapters. It proves/tests the current offline architecture within the documented formal and fault-test boundaries.

It explicitly does **not** authorize:

- real QMT submit;
- real QMT cancel;
- account credentials;
- live trading mode;
- real terminal control.

## Authorized next phase

Development may proceed to **P2 Risk Engine** while remaining fully offline/simulated. P3/P4 require separate gates.
