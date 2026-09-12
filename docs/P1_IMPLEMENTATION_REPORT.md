# P1 Implementation Report

Date: 2026-09-12

Phase: **P1 — Crash-Recoverable Offline OMS**

Status: **PASS**

Safety boundary: simulated driver only. No Big QMT import, credential, live submit, or live cancel path is enabled.

## 1. Delivered P1 scope

### Durable OMS core

- SQLite WAL, foreign keys and `synchronous=FULL`.
- Forward-only packaged migrations through schema **v4**.
- Fail-close on a database schema newer than the running binary.
- Durable intents, broker orders, risk decisions, order events, runtime sessions, leader state and broker-evidence journal.
- Database-enforced `(account_fingerprint, client_order_id)` identity uniqueness.
- Startup is non-trading until reconciliation completes.

### Submit safety

- `SUBMITTING + submit_call_started=1` commits before a broker side effect.
- One durable client-order identity can invoke simulated submit at most once.
- Timeout/response loss enters `UNKNOWN`; no blind resubmit exists.
- Hard crash before/after broker acceptance is explicitly injected and recovered.
- Restart converts ambiguous submit state through `UNKNOWN -> RECONCILING`.
- If no broker fact can prove execution, automation terminates in `MANUAL_REVIEW` rather than reissue.

### Cancel safety

- `CANCEL_PENDING + cancel_call_started=1 + cancel_outcome_resolved=0` commits before the cancel side effect.
- One durable cancel reservation invokes simulated cancel at most once.
- Cancel response loss or process crash never causes automatic recancel.
- Cancel resolution is tracked independently from aggregate order lifecycle, preserving cancel ambiguity across fill races.

### Pre-side-effect restart policy

- Durable `CREATED` or `RISK_ACCEPTED` found on startup with no side-effect marker becomes terminal `ABORTED`.
- It is not automatically submitted after restart.
- A contradictory pre-submit row carrying side-effect evidence is a `RecoveryInvariantViolation` and fails closed.
- A new execution attempt requires a new durable intent and a new risk decision.

### Single-writer / fencing

- SQLite-backed leader lease with session ID, lease token and monotonically increasing fencing epoch.
- Live-leader contention fails closed.
- Expired takeover increments the epoch; the old writer cannot heartbeat or execute.
- Every OMS repository write checks the active fencing token **inside `BEGIN IMMEDIATE`**, after SQLite's writer slot is acquired and before state mutation.
- Submit/cancel paths also re-check ownership before broker side effect and after broker return.
- Callback/evidence ingestion is owned by `OfflineOms` and fenced inside its write transaction.

### Broker evidence / replay

- Durable logical evidence keys and raw observation journal.
- Exact replay remains auditable but affects aggregate state at most once.
- Reused source-event identity with changed facts fails closed.
- Callback and active reconciliation use the same broker-fact normalization path.
- Broker-order identity is immutable.
- Filled quantity is monotonic and bounded by original quantity.
- Stale ACK cannot erase a partial fill; late partial evidence cannot downgrade FILLED.
- Contradictory lifecycle/fill facts fail closed.

### Database/fault atomicity

Verified failure boundaries include:

- database read-only before persistence -> zero broker calls;
- risk persistence failure -> CREATED orphan -> restart ABORTED, zero broker calls;
- submit reservation persistence failure -> rollback, zero broker calls;
- broker accepts submit but ACK persistence fails -> durable ambiguous reservation -> reconcile, no second submit;
- cancel reservation persistence failure -> rollback, zero cancel calls;
- broker accepts cancel but ACK persistence fails -> durable unresolved cancel -> reconcile, no second cancel;
- evidence key/observation persistence failure -> aggregate state, event, dedup key and journal observation roll back atomically;
- hard crash with broker accepted/not accepted -> restart reconciliation without duplicate side effect.

## 2. P1 Gate evidence

Implementation candidate:

`195c2f675a7b9f01667c3146e09c4bd941e95d98`

GitHub Actions run:

`34700851624`

Results:

- CPython 3.11: **75 passed**;
- CPython 3.12: **75 passed**;
- FSM Python/formal conformance: **196 / 196 PASS**;
- static broker/evidence write-surface audit: **PASS**;
- TLC `OrderFSM`: **PASS**, 146 generated / 14 distinct, queue exhausted;
- TLC `SubmitProtocol`: **PASS**, 302 generated / 105 distinct, queue exhausted, 2 temporal branches checked;
- TLC `LeaderLease`: **PASS**, 234 generated / 73 distinct, queue exhausted;
- TLC `EvidenceReplay`: **PASS**, 33 generated / 8 distinct, queue exhausted;
- TLC `PreSubmitRecovery`: **PASS**, 47 generated / 19 distinct, queue exhausted, temporal property checked.

See `docs/FORMAL_VERIFICATION_RESULT_20260912.md` for exact formal evidence and `docs/P1_GATE_RESULT_20260912.md` for the phase decision.

## 3. Exit-criterion audit

The P1 scope requires that every forced-crash boundary restart into an explainable state and that no failure path produce a second simulated broker submit for the same durable client-order identity.

The implemented recovery policy now covers:

- pre-risk / post-intent crash;
- post-risk / pre-reservation crash;
- post-reservation / pre-driver crash;
- broker-call before acceptance / crash;
- broker accepted / result not persisted / crash;
- response-loss ambiguity;
- cancel equivalents;
- evidence write rollback;
- leader expiry/takeover races.

No covered recovery path contains an automatic second submit or second cancel. Static CI also constrains broker side-effect calls to the two fenced OMS methods.

**P1 exit criterion: SATISFIED.**

## 4. Explicit non-goals retained

P1 still contains no:

- enabled Big QMT adapter;
- `xtquant` execution path;
- `passorder` execution path;
- credentials;
- real account side effect;
- live trading mode;
- production scheduler or web console.

## 5. Gate decision

**P1 — PASS**

This authorizes development to proceed to **P2 Risk Engine** only. It does not authorize P3/P4 live integration and does not authorize any real submit/cancel operation.
