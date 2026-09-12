# bigqmt_autotrader

Personal production-grade automated trading execution platform using **Big QMT as the broker terminal**.

## Safety status

The project is currently in **P0 / G0: Order Safety Contract**.

- Live trading is **not enabled**.
- Real order submission is **not implemented**.
- Real cancellation is **not implemented**.
- The QMT-side bridge is fail-closed and exposes only a safety skeleton.
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
 Execution / OMS  -- persistent single writer
        |
        v
 BigQMT Driver  <---- callbacks + active reconciliation
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

1. **P0 / G0** - order-domain contract and deterministic state machine.
2. **P1** - crash-recoverable offline OMS with SQLite WAL.
3. **P2** - four-level pre-trade risk engine.
4. **P3** - Big QMT read-only query/event bridge and field calibration.
5. **P4** - minimal limit-order/cancel bridge behind leases and dual unlock.
6. **P5** - shadow, simulation, then tightly limited live canary.

No phase may skip directly to live trading.

## Local development

```bash
python -m pip install -e ".[test]"
pytest -q
```

See `docs/` for the normative P0 contracts.
