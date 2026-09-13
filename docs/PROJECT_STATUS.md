# Project Status

Updated: 2026-09-13

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| Host Python baseline | **CPython 3.12** |
| QMT-side syntax target | **Built-in Python 3.6 compatible** |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | **PASS** |
| P3 Big QMT read-only | **IN PROGRESS — QMT adapter implemented; Guojin 2.1.19.0 field/runtime calibration pending** |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Big QMT read-only adapter implemented | **YES — active query + callback normalization, in-memory queue only** |
| QMT-side transport to host | NOT IMPLEMENTED — pending P3 calibration |
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

Current checkpoint: **P0/P1/P2 PASS. P3 has started.** The QMT-side read-only adapter now consumes the model-trading `account` / `accountType` globals, calls `ContextInfo.set_account(account)` for account event subscriptions, queries `ACCOUNT` / `POSITION` / `ORDER` / `DEAL` through `get_trade_detail_data`, normalizes callbacks and query results, and stores full normalized events in a bounded in-memory queue. QMT logs contain only safe summaries without raw account IDs, balances, quantities, order IDs or trade IDs.

P3 is **not yet PASS**. Remaining work requires Guojin QMT 2.1.19.0 runtime calibration and then localhost host transport / host ingestion. This phase still does not authorize or implement real submit/cancel.
