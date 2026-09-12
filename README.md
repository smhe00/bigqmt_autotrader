# bigqmt_autotrader

Personal production-grade automated trading execution platform using **Big QMT as the broker terminal**.

## Safety status

The project has passed **P0 / G0: Order Safety Contract** and is now in **P1: Offline OMS — IN PROGRESS**.

- Live trading is **not enabled**.
- Real QMT order submission is **not implemented**.
- Real QMT cancellation is **not implemented**.
- Current execution tests use a deterministic simulated driver only.
- The QMT-side bridge remains fail-closed and exposes only `ping` / `capabilities`.
- Strategy code must never call QMT directly.

The first production target is deliberately narrow: one A-share cash account, ordinary spot equities, limit orders, low-frequency/minute-level strategies, a single OMS writer, persistent reconciliation, and explicit human control.

## Architecture

```text
Market/account state
        |
        v
 Strategy Service  -- emits OrderIntent only
        |
        v
    Risk Engine
        |
        v
 Execution / OMS  -- SQLite WAL, persistent single-writer design
        |
        v
   Broker Driver  <---- callbacks/query reconciliation
        |
        +---- P1: deterministic simulated driver
        |
        +---- P3+: BigQMT read-only driver (future)
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
2. **P1 — IN PROGRESS**: crash-recoverable offline OMS with SQLite WAL.
3. **P2**: four-level pre-trade risk engine.
4. **P3**: Big QMT read-only query/event bridge and field calibration.
5. **P4**: minimal limit-order/cancel bridge behind leases and dual unlock.
6. **P5**: shadow, simulation, then tightly limited live canary.

No phase may skip directly to live trading.

## Current P1 properties

- account-scoped durable `client_order_id` uniqueness;
- durable order/risk/event state;
- `SUBMITTING` reservation committed before simulated side effect;
- submit ambiguity enters `UNKNOWN`;
- startup reconciliation is mandatory before new intents;
- restart recovery never automatically resubmits an ambiguous order;
- simulated broker evidence can converge `UNKNOWN -> RECONCILING -> ACKNOWLEDGED`;
- no evidence converges to automation-terminal `MANUAL_REVIEW`.

## Local development

```bash
python -m pip install -e ".[test]"
pytest -q
```

See `docs/P0_IMPLEMENTATION_REPORT.md` and `docs/P1_IMPLEMENTATION_REPORT.md` for gate status.
