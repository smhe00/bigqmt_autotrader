# Project Status

Updated: 2026-09-12

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| P0 / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 Risk engine | READY / NEXT |
| P3 Big QMT read-only | NOT STARTED |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| SQLite schema | v4 forward-only migrations |
| Latest P1 verified Python tests | **75 passed** on Python 3.11 and 3.12 |
| FSM implementation/formal conformance | **196 / 196** state-request pairs PASS |
| TLC OrderFSM | **PASS** — 14 distinct states |
| TLC SubmitProtocol | **PASS** — 105 distinct states + temporal properties |
| TLC LeaderLease | **PASS** — 73 distinct states |
| TLC EvidenceReplay | **PASS** — 8 distinct states |
| TLC PreSubmitRecovery | **PASS** — 19 distinct states + temporal property |
| Broker side-effect/write-surface audit | **PASS** |
| Simulated submit at-most-once | Implemented + fault-tested + formally modeled |
| Simulated cancel at-most-once | Implemented + fault-tested + formally modeled |
| Transactional OMS leader/fencing | Implemented + tested + formally modeled |
| Broker evidence dedup/replay | Implemented + tested + formally modeled |
| Hard-crash recovery matrix | Implemented + tested |
| SQLite failure/rollback injection | Implemented for P1 persistence/side-effect/evidence boundaries |

P1 Gate evidence: `docs/P1_GATE_RESULT_20260912.md`.

Current development target: **P2 deterministic fail-closed Risk Engine**. P2 remains offline/simulated and must not add real QMT execution capability.
