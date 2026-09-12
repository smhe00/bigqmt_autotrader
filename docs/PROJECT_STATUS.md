# Project Status

Updated: 2026-09-12

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| P0 / G0 | PASS |
| Order-state-machine formal verification | **PASS** |
| P1 Offline OMS | **IN PROGRESS — final recovery/audit work remains** |
| P2 Risk engine | NOT STARTED |
| P3 Big QMT read-only | NOT STARTED |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| SQLite schema | v4 forward-only migrations |
| Latest verified unit-test count | **57 passed** on Python 3.11 and 3.12 |
| FSM implementation/formal conformance | **169 / 169** state-request pairs PASS |
| TLC OrderFSM | PASS |
| TLC SubmitProtocol | PASS |
| TLC LeaderLease | PASS |
| TLC EvidenceReplay | PASS |
| Simulated submit at-most-once | Implemented + tested + formally modeled |
| Simulated cancel at-most-once | Implemented + tested + formally modeled |
| Single OMS leader/fencing | Implemented + tested + formally modeled |
| Broker evidence dedup/replay | Implemented + tested + formally modeled |
| SQLite failure injection | Implemented for key submit/cancel boundaries |

Current next target: close pre-side-effect orphan recovery semantics, complete the crash-boundary/no-double-side-effect audit, and issue the final P1 Gate decision before opening P2.
