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
| P3 Big QMT read-only | **IN PROGRESS — QMT lifecycle/query/callback/file-spool PASS; QMT→spool→Host path observed; coherent-session Host restart replay implemented; real restart/failure calibration and ORDER/DEAL semantics pending** |
| P4 Big QMT trading bridge | NOT STARTED |
| P5 Shadow / simulation / live canary | NOT STARTED |
| Live trading allowed | **NO** |
| Real QMT submit implemented | **NO** |
| Real QMT cancel implemented | **NO** |
| Big QMT read-only adapter implemented | **YES — active query + callback normalization + bounded queue** |
| Guojin ACCOUNT/POSITION active query | **PASS — latest real snapshot returned 1 ACCOUNT row and 8 POSITION rows, no query errors** |
| Guojin ORDER/DEAL active query | **PASS at query/schema level — latest real snapshot returned 1 ORDER row and 2 DEAL rows; status semantics still uncalibrated** |
| Guojin callback subscription | **PASS — `ContextInfo.set_account(account)` succeeded** |
| Guojin ACCOUNT callback delivery | **PASS — repeated real callbacks observed** |
| Guojin POSITION/ORDER/DEAL callback delivery | **PENDING CALIBRATION** |
| Guojin built-in `_socket` | **UNAVAILABLE on calibrated install — `socket.py` imports fail because `_socket` DLL cannot load** |
| QMT TCP candidate V03 | **INCOMPATIBLE with calibrated Guojin runtime; retained only as evidence/reference** |
| QMT file-spool candidate V04 | **IMPLEMENTED / REAL-QMT PASS — build `p3-file-spool-2`, Python 3.6-compatible, atomic rename, resolved spool path logging, ACCOUNT callback dedup** |
| ACCOUNT callback dedup | **IMPLEMENTED — state changes emit immediately; identical callbacks suppressed; identical heartbeat at most every 300 s when no newer full snapshot refreshes state** |
| Python 3.12 file-spool receiver | **IMPLEMENTED — default Host transport, account pinning, protocol/session/sequence validation, resolved spool path logging** |
| Host ACCOUNT semantic dedup | **IMPLEMENTED — repeated account facts marked deduplicated while sequence/timestamp still advance** |
| Host-only restart recovery | **IMPLEMENTED — identify latest live spool tail, select only its coherent session+account, replay from that stream's clean processed snapshot, then continue with inbox; historical streams remain on disk** |
| Host console logging | **HARDENED — important events only; duplicate ACCOUNT/routine POSITION backlog suppressed; cumulative summary every 60 s by default** |
| V05 daily spool archive | **IMPLEMENTED — UTC+08 trading day, 16:10 gate, clean-snapshot convergence; identical trailing ACCOUNT heartbeat neither invalidates convergence nor resets the 300 s quiet timer** |
| V05 source cleanup | **FAIL-SAFE — exact small files deleted only after archive/manifest/checkpoint revalidation** |
| V05 quarantine | **IMPLEMENTED — malformed/protocol-invalid files retained in `quarantine/`; same-day quarantine blocks archive; no automatic deletion** |
| TCP receiver | **RETAINED for tests/future runtimes; not the Guojin P3 production path** |
| Host read model | **IMPLEMENTED — gap/session change remains fail-closed until clean full snapshot resync; Host restart recovery is isolated to the current coherent stream** |
| Host ORDER/DEAL ingestion | **FAIL-CLOSED — quarantined unless explicit calibrated EvidenceMapper exists** |
| Runnable host receiver | **IMPLEMENTED — `python -m bigqmt_autotrader.qmt.host` defaults to file spool + auto archive + coherent-session restart replay** |
| P2 execution-authority policy | **SIMULATION only** |
| SQLite schema | v4 forward-only migrations |
| Latest verified Python tests | **159 passed on Python 3.12** |
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

P3 Guojin query/callback calibration: `docs/P3_GUOJIN_QMT_CALIBRATION_20260914.md`.

P3 daily spool archive contract: `docs/P3_DAILY_SPOOL_ARCHIVE.md`.

Current checkpoint: **P0/P1/P2 PASS. P3 IN PROGRESS.** Real Guojin QMT 2.1.19.0 calibration has confirmed built-in CPython 3.6.8, normal model-trading lifecycle behavior, account binding, successful read-only ACCOUNT/POSITION/ORDER/DEAL active queries, callback subscription, ACCOUNT callback delivery, durable file-spool publication, and matching resolved spool paths between QMT and the Python 3.12 Host.

The first Host-only restart implementation exposed a second-order calibration issue: the shared 2026-09-14 TEMP spool contains several historical sessions/accounts. A restarted Host selected a historical clean snapshot (`sequence=1718`, 2 positions, 1 deal) rather than the current 21:40 QMT stream (current snapshot `sequence=2`, 8 positions, 2 deals), briefly became healthy, and then hit `QmtProtocolError` while replay crossed into a different account/session. Recovery is now stream-scoped rather than day-scoped. The Host first identifies the newest valid spool tail across inbox+processed, then selects that tail's `session_id + account_fingerprint`, finds the newest clean processed snapshot in the same stream, and replays only that stream. Historical calibration streams remain physically present and continue to participate in archive-integrity checks; they are not silently discarded.

The first localhost TCP transport candidate (V03) failed because the bundled Python 3.6.8 environment could not load the `_socket` extension DLL. This terminal capability is treated as a hard runtime boundary; the project does not require broker DLL modification or local-Python mode as a workaround.

The Guojin-adapted transport is file based. `qmt_side/BIGQMT_EXECUTION_BRIDGE_V04.py` build `p3-file-spool-2` publishes complete transport frames using write/flush/fsync plus same-directory atomic rename. It logs its fully resolved spool root/inbox path. Repeated identical ACCOUNT callbacks are suppressed at the QMT edge; account changes emit immediately, while an identical callback heartbeat is permitted only after 300 seconds if a newer full snapshot has not already refreshed the account state.

The Python 3.12 Host logs its resolved spool root/inbox path and independently marks repeated ACCOUNT facts as semantic duplicates while preserving sequence/timestamp continuity and gap detection. Console output is important-event oriented: snapshots, ORDER/DEAL, account changes, gap/resync/error, quarantine and archive transitions remain visible; routine duplicate ACCOUNT and POSITION backlog events are not printed one-by-one. A cumulative summary is emitted every 60 seconds by default. Restart diagnostics now include recovery target sequence and snapshot sequence so the selected stream can be checked directly.

V05 daily archive convergence treats the latest clean snapshot as the broker-state baseline. Identical ACCOUNT heartbeat events after that snapshot do not invalidate the day and do not reset the archive quiet timer; the final clean snapshot remains the quiet-period anchor. Any real ACCOUNT change, POSITION/ORDER/DEAL fact, bridge error, or other event after the snapshot still blocks commit until a newer clean snapshot arrives. Same-day filesystem quarantine also continues to block archive commit, and quarantine is never auto-deleted.

The current 2026-09-14 temp spool contains historical calibration material that triggers `account_mismatch` and `quarantine_present`; those conditions are intentionally not auto-cleared. They must be inspected or intentionally retired as calibration data before that day's archive can commit.

The QMT-side adapter still has no trading mutation path. `passorder`, `order_lots`, cancel/task mutation, real submit, and real cancel remain absent/disabled. P3 is **not yet PASS**: remaining work is real coherent-session Host-only restart replay calibration, inspection/reconciliation of existing filesystem quarantine, POSITION/ORDER/DEAL callback calibration, and Guojin ORDER/DEAL status/token mapping before broker order evidence can enter the OMS.
