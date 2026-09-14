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
| P3 Big QMT read-only | **IN PROGRESS — active-query PASS; file-spool Host transport + V05 daily archive implemented; real end-to-end spool/callback calibration pending** |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Big QMT read-only adapter implemented | **YES — active query + callback normalization + bounded queue** |
| Guojin ACCOUNT/POSITION active query | **PASS — real terminal calibration, no query errors** |
| Guojin ORDER/DEAL active query | **CALL SUCCEEDED, 0 rows observed; field rows/status semantics still uncalibrated** |
| Guojin callback delivery | **PENDING CALIBRATION** |
| Guojin built-in `_socket` | **UNAVAILABLE on calibrated install — `socket.py` imports fail because `_socket` DLL cannot load** |
| QMT TCP candidate V03 | **INCOMPATIBLE with calibrated Guojin runtime; retained only as evidence/reference** |
| QMT file-spool candidate V04 | **IMPLEMENTED — Python 3.6-compatible, no socket/thread/process dependency, atomic rename publication** |
| Python 3.12 file-spool receiver | **IMPLEMENTED — default Host transport, account pinning, protocol/session/sequence validation** |
| V05 daily spool archive | **IMPLEMENTED — UTC+08 trading day, 16:10 default archive gate, 300 s quiet period, jsonl.gz + manifest + committed checkpoint** |
| V05 source cleanup | **FAIL-SAFE — exact small files deleted only after archive/manifest/checkpoint revalidation** |
| V05 quarantine | **IMPLEMENTED — malformed/protocol-invalid files retained in `quarantine/`; same-day quarantine blocks archive** |
| TCP receiver | **RETAINED for tests/future runtimes; not the Guojin P3 production path** |
| Host read model | **IMPLEMENTED — gap/restart fail-closed until clean full snapshot resync** |
| Host ORDER/DEAL ingestion | **FAIL-CLOSED — quarantined unless explicit calibrated EvidenceMapper exists** |
| Runnable host receiver | **IMPLEMENTED — `python -m bigqmt_autotrader.qmt.host` defaults to file spool + auto archive** |
| P2 execution-authority policy | **SIMULATION only** |
| SQLite schema | v4 forward-only migrations |
| Latest verified Python tests | **147 passed on Python 3.12** |
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

P3 daily spool archive contract: `docs/P3_DAILY_SPOOL_ARCHIVE.md`.

Current checkpoint: **P0/P1/P2 PASS. P3 IN PROGRESS.** Real Guojin QMT 2.1.19.0 calibration has confirmed built-in CPython 3.6.8, normal `init` / `handlebar` lifecycle behavior, account binding, and successful read-only ACCOUNT/POSITION queries through `get_trade_detail_data()` with zero query errors.

The first localhost TCP transport candidate (V03) failed on the real terminal before model code could run because the bundled Python 3.6.8 environment could not load the `_socket` extension DLL. This terminal capability is treated as a hard runtime boundary; the project does not require users to modify broker-installed DLLs or enable local Python to work around it.

The Guojin-adapted transport is file based. `qmt_side/BIGQMT_EXECUTION_BRIDGE_V04.py` publishes one complete transport frame per event using write/flush/fsync plus same-directory atomic rename into the OS temp spool. The Python 3.12 Host defaults to polling that spool, validates protocol/account/session/sequence, detects gaps/restarts, and keeps the read model unhealthy until a clean full snapshot resynchronizes it. Successfully consumed files move to `processed`; malformed or protocol-invalid files move to `quarantine`. ORDER/DEAL facts remain separately quarantined at the semantic ingestion boundary until explicit Guojin schema/status mapping exists.

V05 adds bounded long-term file management without weakening crash recovery. The Host automatically considers today's archive after 16:10 UTC+08:00 and historical unarchived days on startup. A day commits only after the quiet period, empty same-day inbox, no same-day quarantine, no internal per-session sequence gaps, one account fingerprint, and a final clean snapshot. It then creates a deterministic `YYYY-MM-DD_events.jsonl.gz`, a SHA-256 manifest, and a durable `COMMITTED` checkpoint; exact source files are deleted only after the committed archive set is re-read and verified. A crash after checkpoint but before cleanup is recoverable, corrupt committed archives block deletion, and late events after commit are retained and surfaced rather than silently lost.

The QMT-side adapter still has no trading mutation path. `passorder`, `order_lots`, cancel/task mutation, real submit, and real cancel remain absent/disabled. P3 is **not yet PASS**: remaining work is real QMT→Host file-spool calibration, callback-delivery calibration, reconnect/startup testing, and ORDER/DEAL schema/status mapping before broker order evidence can enter the OMS.
