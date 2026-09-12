# bigqmt_autotrader

Personal production-grade automated trading execution platform using **Big QMT as the broker terminal**.

## Safety status

The project has passed **P0 / G0**, **P1 Offline OMS**, and **P2 Deterministic Risk Engine**. Development is intentionally stopped **before P3 Big QMT read-only integration**.

- Live trading is **not enabled**.
- Real QMT order submission is **not implemented**.
- Real QMT cancellation is **not implemented**.
- Big QMT read-only integration is **not started**.
- Current execution tests use a deterministic simulated driver only.
- The QMT-side bridge remains fail-closed and exposes only `ping` / `capabilities` plus disabled submit/cancel stubs.
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
        +---- Current: deterministic simulated driver
        |
        +---- P3: Big QMT read-only adapter (NOT STARTED)
        |
  localhost RPC
        |
        v
 QMT-side Execution Bridge
        |
        v
      Big QMT
```

## Development gates

1. **P0 / G0 — PASS**: order-domain contract and deterministic state machine.
2. **P1 — PASS**: crash-recoverable offline OMS with SQLite WAL, fencing, replay and reconciliation.
3. **P2 — PASS**: deterministic four-level pre-trade risk engine and OMS-owned risk-to-submit boundary.
4. **P3 — NOT STARTED**: Big QMT read-only query/event bridge and field calibration.
5. **P4 — NOT STARTED**: minimal limit-order/cancel bridge behind leases and dual unlock.
6. **P5 — NOT STARTED**: shadow, simulation, then tightly limited live canary.

No phase may skip directly to live trading.

## Verified properties through P2

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

## Local development

```bash
python -m pip install -e ".[test]"
pytest -q
```

See `docs/PROJECT_STATUS.md`, `docs/P1_GATE_RESULT_20260912.md`, and `docs/P2_GATE_RESULT_20260913.md` for current gate status and evidence.
