# P3 Localhost Transport and Host Ingestion

Date: 2026-09-14

Status: **IMPLEMENTED — awaiting Guojin QMT end-to-end calibration**

## Scope

This P3 transport connects the QMT built-in Python 3.6.8 read-only bridge to the
Python 3.12 host process. It does not add trading authority.

```text
Guojin QMT 2.1.19.0 / CPython 3.6.8
    read-only snapshot + callbacks
                |
                | 127.0.0.1 TCP, one JSON event / connection, ACK gated
                v
Python 3.12 LocalQmtReceiver
    protocol/account/session/sequence validation
                |
                v
QmtHostIngestion
    snapshot/account/position -> read model
    order/deal -> quarantine unless explicitly calibrated mapper exists
                |
                v
Existing OMS EvidenceJournal (only after explicit mapping)
```

## Transport contract

- transport version: `1`;
- bridge event protocol version: `0.2`;
- default endpoint: `127.0.0.1:18765`;
- maximum frame: 1 MiB;
- QMT sender timeout: 50 ms;
- QMT uses no threads or subprocesses;
- a queued event is removed only after a positive host ACK;
- failed transport keeps the failed event and all later FIFO events queued;
- the QMT queue remains bounded by the bridge's existing 512-event limit.

The host binds only to loopback. Binding to a non-loopback address is rejected.

## Identity and ordering

Every bridge event contains:

```text
protocol_version
session_id
sequence
timestamp_ms
event_type
source
account_fingerprint
account_type
payload
```

The host validates the SHA-256 account fingerprint. If an expected fingerprint
is not configured, the first valid event pins the receiver to that fingerprint;
subsequent events for another account are rejected.

Within a QMT `session_id`, `sequence` is monotonic:

- lower/equal sequence -> `DUPLICATE`;
- non-consecutive higher sequence -> `GAP` and fail-closed `needs_resync=true`;
- a new QMT session also begins in `needs_resync=true`;
- only a complete clean active `snapshot` clears `needs_resync`.

Therefore callback continuity is never assumed after a gap or restart.

## ACK-loss semantics

The host validates and ingests an event before returning ACK. If the ACK is lost,
the QMT bridge retains the event and retries it. The retry has the same
`session_id + sequence`, is classified `DUPLICATE`, and is not reapplied by the
host ingestion boundary. This gives replay safety without pretending the TCP
transport itself is exactly-once.

## Host ingestion boundary

`QmtHostIngestion` deliberately does not guess Guojin order status codes.

- `snapshot`, `account`, and `position` update the read-only broker view;
- `order` and `deal` callbacks are quarantined by default;
- an explicit calibrated `EvidenceMapper` must resolve QMT facts into:
  - `client_order_id`;
  - canonical `OrderStatus`;
  - cumulative filled quantity;
  - broker order ID;
- only then can the fact be passed to the existing OMS `EvidenceJournal`.

This preserves the P1 rule that callbacks and active queries converge through one
durable evidence path while avoiding uncalibrated state transitions.

## Runnable host

Start the Python 3.12 receiver with:

```text
python -m bigqmt_autotrader.qmt.host
```

It emits only safe summaries under:

```text
BIGQMT_HOST_STATUS=
```

No cash values, quantities, broker order IDs, trade IDs, or raw account IDs are
printed by this host status stream.

An explicit expected fingerprint can optionally be supplied:

```text
python -m bigqmt_autotrader.qmt.host --expected-account-fingerprint sha256:<hex>
```

If omitted, first-valid-event pinning is used.

## QMT candidate bridge

The transport-enabled standalone candidate is:

```text
qmt_side/BIGQMT_EXECUTION_BRIDGE_V03.py
```

It retains all P3 read-only safety constraints and keeps submit/cancel entry
points hard-disabled. The previously calibrated bridge remains unchanged until
V03 passes a real Guojin localhost transport run.

## Remaining P3 calibration

1. Run the Python 3.12 host receiver locally.
2. Run `BIGQMT_EXECUTION_BRIDGE_V03.py` in Guojin model-trading simulation-signal mode.
3. Confirm `snapshot` reaches the host and ACK drains the QMT queue.
4. Restart the host and QMT independently to verify session/gap/resync behavior.
5. Calibrate callback delivery separately.
6. Obtain real ORDER/DEAL schemas/status codes without enabling live mutation.
7. Add the explicit ORDER/DEAL evidence mapper only after those semantics are verified.

P4 real submit/cancel capability remains out of scope and unauthorized.
