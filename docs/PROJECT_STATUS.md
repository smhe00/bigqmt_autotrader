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
| P3 Big QMT read-only | **IN PROGRESS — active-query path calibrated PASS; callbacks/host transport pending** |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Big QMT read-only adapter implemented | **YES — active query + callback normalization, in-memory queue only** |
| Guojin ACCOUNT/POSITION active query | **PASS — real terminal calibration, no query errors** |
| Guojin ORDER/DEAL active query | **CALL SUCCEEDED, 0 rows observed; field rows still uncalibrated** |
| Guojin callback delivery | **PENDING CALIBRATION** |
| QMT-side transport to host | **NOT IMPLEMENTED** |
| P2 execution-authority policy | **SIMULATION only** |
| SQLite schema | v4 forward-only migrations |
| Latest verified Python tests | **117 passed on Python 3.12** |
| QMT-side Python 3.6 syntax contract | **PASS** |
| P3 QMT mutation-call static contract | **PASS — no passorder/cancel/order mutation calls** |
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

P3 calibration evidence: `docs/P3_GUOJIN_QMT_CALIBRATION_20260914.md`.

Current checkpoint: **P0/P1/P2 PASS. P3 IN PROGRESS.** Real Guojin QMT 2.1.19.0 calibration has now confirmed built-in CPython 3.6.8, normal `init` / `handlebar` lifecycle behavior, account binding, and successful read-only ACCOUNT/POSITION queries through `get_trade_detail_data()` with zero query errors. The successful snapshot returned one ACCOUNT row and two POSITION rows; ORDER and DEAL queries returned zero rows in that run.

The QMT-side adapter still has no trading mutation path. `passorder`, order-lot helpers, cancel/task mutation, real submit, and real cancel remain absent/disabled. P3 is **not yet PASS**: remaining work is callback-delivery calibration, localhost host transport, host ingestion into OMS evidence/reconciliation, and reconnect/startup testing.
