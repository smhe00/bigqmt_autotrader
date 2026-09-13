# Project Status

Updated: 2026-09-14

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| Host Python baseline | **CPython 3.12** |
| QMT-side syntax target | **Built-in Python 3.6 compatible** |
| Observed Guojin QMT runtime | **CPython 3.6.8** |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | **PASS** |
| P3 Big QMT read-only | **IN PROGRESS — active-query PASS; localhost transport + Host ingestion implemented; real end-to-end transport/callback calibration pending** |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Big QMT read-only adapter implemented | **YES — active query + callback normalization + bounded queue** |
| Guojin ACCOUNT/POSITION active query | **PASS — real terminal calibration, no query errors** |
| Guojin ORDER/DEAL active query | **CALL SUCCEEDED, 0 rows observed; field rows/status semantics still uncalibrated** |
| Guojin callback delivery | **PENDING CALIBRATION** |
| QMT-side localhost sender | **IMPLEMENTED — V03 candidate, Python 3.6-compatible, loopback TCP + ACK, no threads** |
| Python 3.12 localhost receiver | **IMPLEMENTED — loopback-only, account pinning, protocol/session/sequence validation** |
| Host read model | **IMPLEMENTED — gap/restart fail-closed until clean full snapshot resync** |
| Host ORDER/DEAL ingestion | **FAIL-CLOSED — quarantined unless explicit calibrated EvidenceMapper exists** |
| Runnable host receiver | **IMPLEMENTED — `python -m bigqmt_autotrader.qmt.host`** |
| P2 execution-authority policy | **SIMULATION only** |
| SQLite schema | v4 forward-only migrations |
| Latest verified Python tests | **132 passed on Python 3.12** |
| QMT-side Python 3.6 syntax contract | **PASS** |
| P3 QMT mutation-call static contract | **PASS — no passorder/order_lots/cancel mutation calls** |
| FSM implementation/formal conformance | **196 / 196** state-request pairs PASS |
| Static side-effect/risk-bypass/evidence audit | **PASS** |
| TLC OrderFSM | **PASS** — 14 distinct states |
| TLC SubmitProtocol | **PASS** — 105 distinct states + temporal properties |
| TLC LeaderLease | **PASS** — 73 distinct states |
| TLC EvidenceReplay | **PASS** — 8 distinct states |
| TLC PreSubmitRecovery | **PASS** — 19 distinct states + temporal property |
| TLC RiskPrecedence | **PASS** — 4096 distinct failure-set states |
| Simulated submit at-most-once | Implemented + fault-tested + formally modeled |
| Simulated cancel at-most-once | Implemented + fault-tested + formally modeled |
| Transactional OMS leader/fencing | Implemented + tested + formally modeled |
| Broker evidence dedup/replay | Implemented + tested + formally modeled |
| Hard-crash recovery matrix | Implemented + tested |
| SQLite failure/rollback injection | Implemented for P1 persistence/side-effect/evidence boundaries |
| Deterministic four-level Risk Engine | Implemented + rule-tested + formally precedence-checked |
| Public OMS-owned risk decision | Implemented + integrated + statically audited |
| Canonical risk snapshot SHA-256 | Implemented + tested |

P1 Gate evidence: `docs/P1_GATE_RESULT_20260912.md`.

P2 Gate evidence: `docs/P2_GATE_RESULT_20260913.md`.

P3 Guojin query calibration: `docs/P3_GUOJIN_QMT_CALIBRATION_20260914.md`.

P3 localhost transport contract: `docs/P3_LOCALHOST_TRANSPORT.md`.

Current checkpoint: **P0/P1/P2 PASS. P3 IN PROGRESS.** Real Guojin QMT 2.1.19.0 calibration has confirmed built-in CPython 3.6.8, normal `init` / `handlebar` lifecycle behavior, account binding, and successful read-only ACCOUNT/POSITION queries through `get_trade_detail_data()` with zero query errors. The successful snapshot returned one ACCOUNT row and two POSITION rows; ORDER and DEAL queries returned zero rows in that run.

The next P3 slice is now implemented in source and CI-tested: a QMT-side Python 3.6-compatible ACK-gated loopback TCP sender, a Python 3.12 loopback receiver, account/session/sequence validation, gap/restart resynchronization semantics, a fail-closed host read model, and an ingestion boundary that quarantines ORDER/DEAL facts until an explicit calibrated mapper can translate them into canonical OMS evidence. ACK loss is replay-safe because duplicate `session_id + sequence` events are discarded before read-model/OMS reapplication.

The transport-enabled QMT candidate is `qmt_side/BIGQMT_EXECUTION_BRIDGE_V03.py`. The already calibrated bridge remains unchanged until V03 passes a real Guojin end-to-end localhost run.

The QMT-side adapter still has no trading mutation path. `passorder`, `order_lots`, cancel/task mutation, real submit, and real cancel remain absent/disabled. P3 is **not yet PASS**: remaining work is real QMT→Host transport calibration, callback-delivery calibration, reconnect/startup testing, and ORDER/DEAL schema/status mapping before broker order evidence can enter the OMS.
