# Project Status

Updated: 2026-09-12

| Item | State |
| --- | --- |
| Product target | Personal production-grade Big QMT execution platform |
| P0 / G0 | PASS |
| Order-state-machine formal verification | **PASS** |
| P1 Offline OMS | IN PROGRESS |
| P2 Risk engine | NOT STARTED |
| P3 Big QMT read-only | NOT STARTED |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Latest verified unit-test count | 28 passed on Python 3.11 and 3.12 |
| FSM implementation/formal conformance | 169 / 169 state-request pairs PASS |
| TLC OrderFSM | 13 distinct reachable states, PASS |
| TLC SubmitProtocol | 51 distinct reachable states + temporal properties, PASS |

Current next target: complete P1 cancel/crash/leader/migration/replay coverage and extend the formal model with each new safety-critical mechanism before opening P2.
