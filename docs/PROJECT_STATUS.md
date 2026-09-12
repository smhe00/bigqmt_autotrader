# Project Status

Updated: 2026-09-13

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | **PASS** |
| P3 Big QMT read-only | **NOT STARTED — STOP BOUNDARY** |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Big QMT read-only adapter implemented | **NO** |
| P2 execution-authority policy | **SIMULATION only** |
| SQLite schema | v4 forward-only migrations |
| Latest verified Python tests | **112 passed** on Python 3.11 and 3.12 |
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

Current checkpoint: **P2 COMPLETE / PASS. P3 has not been started.** The next phase, when explicitly resumed, is Big QMT read-only query/callback integration and field calibration; it must not imply live submit/cancel authorization.
