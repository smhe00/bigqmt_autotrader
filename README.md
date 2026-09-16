# bigqmt_autotrader

Personal production-grade automated trading execution platform using **Big QMT as the broker terminal**.

## Safety status

The project has passed **P0 / G0**, **P1 Offline OMS**, **P2 Deterministic Risk
Engine**, **P3 Big QMT read-only**, and the **P4 SHADOW deployment gate**. P5
now has a code-complete, account-pinned Guojin simulation calibration path.

- Host-side development baseline: **Python 3.12**.
- QMT-side bridge remains **Python 3.6 syntax compatible** for the built-in QMT runtime.
- Production-account live trading is **not enabled**.
- QMT broker mutation exists only in the fingerprint-pinned `guojin_sim`
  calibration artifact; Galaxy and Guojin production artifacts contain zero
  submit/cancel API calls.
- The P3 QMT-side adapter can read and normalize `ACCOUNT`, `POSITION`, `ORDER`, and `DEAL` snapshots and callback facts.
- The adapter stores full normalized facts only in a bounded in-memory queue; QMT logs contain safe summaries only.
- No QMT mutation function is called by the P3 adapter.
- Strategy code must never call QMT directly.
- P2 `RiskPolicy` may authorize execution eligibility in **SIMULATION only**; live-named runtime modes cannot be enabled by configuration alone.

The first production target remains deliberately narrow: one A-share cash account, ordinary spot equities, limit orders, low-frequency/minute-level strategies, a single OMS writer, persistent reconciliation, and explicit human control.

## Architecture

```text
Market/account state
        |
        v
 Strategy Service  -- emits OrderIntent only
        |
        v
    Risk Engine     -- P2 deterministic/fail-closed
        |
        v
 Execution / OMS    -- SQLite WAL, fenced single writer
        |
        v
   Broker Driver  <---- callbacks/query reconciliation
        |
        +---- Current execution: deterministic simulated driver
        |
        +---- P3 read-only facts: Big QMT adapter (PASS)
        |
  future localhost transport
        |
        v
 QMT-side bridge -- Python 3.6; production SHADOW / pinned simulation calibration
        |
        v
  Guojin QMT 2.1.19.0
```

## Development gates

1. **P0 / G0 — PASS**: order-domain contract and deterministic state machine.
2. **P1 — PASS**: crash-recoverable offline OMS with SQLite WAL, fencing, replay and reconciliation.
3. **P2 — PASS**: deterministic four-level pre-trade risk engine and OMS-owned risk-to-submit boundary.
4. **P3 — PASS**: Big QMT read-only query/callback transport, recovery/archive, and Guojin V05 timer calibration are complete.
5. **P4 — SHADOW DEPLOYMENT GATE PASS**: durable command round-trip and OMS reconciliation are implemented without production mutation.
6. **P5 — SIMULATION MUTATION CODE GATE PASS**: `guojin_sim` is fingerprint-pinned and tightly bounded; QMT redeployment and ORDER/DEAL calibration are pending.

No phase may skip directly to live trading.

## Verified properties

Through P2:

- durable account-scoped `client_order_id` uniqueness;
- durable order/risk/event state and startup reconciliation;
- submit/cancel reservations committed before simulated side effects;
- ambiguous broker outcomes never trigger blind submit/cancel retry;
- hard-crash recovery and leader/fencing behavior are fault-tested;
- broker evidence is deduplicated, replay-audited and monotonic;
- pre-submit restart orphans terminate as `ABORTED` rather than becoming executable;
- public OMS submission evaluates risk internally; callers cannot supply an accepted `RiskDecision` as execution authority;
- deterministic risk order: Global -> Account -> Strategy -> Security/Order;
- canonical risk snapshot SHA-256 and exact `Decimal` arithmetic;
- stale, contradictory, unhealthy or unauthorized risk facts fail closed;
- rejected risk decisions produce zero simulated broker submit calls;
- P2 policy construction permits execution eligibility in `SIMULATION` only;
- static CI audits the broker-side-effect, evidence-write, risk-evaluation and internal submit call surfaces;
- mandatory TLA+/TLC models cover the order FSM, submit/recovery protocol, leader lease, evidence replay, pre-submit recovery and risk precedence abstractions.

P3 implementation candidate additionally verifies:

- QMT bridge parses as Python 3.6 syntax;
- `account` / `accountType` runtime binding is isolated to the QMT adapter;
- `ContextInfo.set_account(account)` is used only for read-only callback subscription;
- `get_trade_detail_data()` query results are normalized for account, position, order and deal facts;
- raw account IDs are excluded from normalized output in favor of a SHA-256 account fingerprint;
- QMT log output excludes cash balances, quantities, order IDs, trade IDs and raw account IDs;
- source-level tests reject broker mutation calls in the template and both
  production-account artifacts;
- static audit permits exactly one submit and one cancel call only inside the
  reviewed `guojin_sim` executor.

## Local development

```bash
python -m pip install -e ".[test]"
pytest -q
```

See `docs/PROJECT_STATUS.md`, `docs/P1_GATE_RESULT_20260912.md`, and `docs/P2_GATE_RESULT_20260913.md` for gate status and evidence.
