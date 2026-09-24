# Project Status

Updated: 2026-09-25

## 1. Release and environment

| Item | Authoritative state |
| --- | --- |
| Git branch | `main` |
| Execution Core release | **`core-v1.0.0` / FROZEN** |
| Core release gate commit | `068212da517d21603885af7e52f3abb6236dd2f4` |
| Core release CI run | `36016234582` |
| Latest completed workflow before documentation migration | `P6-T015-I01 / PASS` |
| Host baseline | CPython 3.12 (package supports 3.11+) |
| QMT-side target | Built-in Python 3.6 compatible |
| Observed Guojin | CPython 3.6.8 / QMT 2.1.19.0 |
| Observed Galaxy | QMT 2.1.26.1 |

The machine-readable release identity is
[`contracts/core/v1/release.json`](../contracts/core/v1/release.json). This document does
not override that contract.

## 2. Gate summary

| Gate | State |
| --- | --- |
| P0 domain / G0 | **PASS** |
| P1 Offline OMS | **PASS** |
| P2 deterministic Risk | **PASS**, Runtime extension |
| P3 Big QMT read plane | **PASS** |
| P4 SHADOW execution bridge | **DEPLOYMENT GATE PASS** |
| P5 Guojin simulation mutation calibration | **BOUNDED PASS** |
| P6 runtime tasks T001–T015 | **Final iterations PASS** |
| Bridge API v1 | **Contract + schema/formal CI Gate** |
| BrokerEvidence v1 | **Contract + runtime/formal CI Gate** |
| Execution Core v1 | **FROZEN + permanent release CI job** |
| General production live trading | **NO** |

Intermediate `BLOCKED` or `CHANGES_REQUIRED` P6 iterations are retained in `workflow/` as
audit history; their later matching task iteration supplies the final verdict.

## 3. Deployment authority matrix

| instance | build | mode | current authority |
| --- | --- | --- | --- |
| generic template | `p4-shadow-command-spool-5` | SHADOW | no submit/cancel |
| `galaxy` | `p4-shadow-command-spool-5` | SHADOW | no submit/cancel; no calibrated mapper |
| `guojin_sim` | `p5-simulation-calibration-8` | SIMULATION_CALIBRATION | pinned simulation only, bounded mutation |
| `guojin` | `p6-guojin-live-canary-7` | LIVE_CANARY | one pinned case only; not general LIVE |

The Guojin canary is limited to `00700.HGT BUY 100 @ 1.00 HKD` with one submit and one
cancel fuse per build/session. GC001 is historical calibration evidence and `511880.SH` is
read-only diagnostic only. Galaxy/generic production artifacts must retain zero broker
mutation call surface.

## 4. Core v1 boundary

Frozen roots/files are enumerated by `contracts/core/v1/inventory.json`:

- `core/`, `domain/`, `ports/`;
- broker-neutral OMS authorization/evidence/db/leader/repository/service modules;
- `oms/core_migrations/0001_initial.sql`.

QMT, drivers, Risk, MarketData, Operations, Service, Strategy, Runtime and Web are
adapters/extensions. New Core-only databases use independent Core schema v1 and must not
contain QMT tables. Historical combined schema 7–11 remains readable through the legacy
compatibility path without downgrade.

## 5. Runtime evidence achieved

P6 final PASS evidence covers:

- Host-owned durable dispatch and OMS integration;
- single-writer lease/fencing and replay heartbeat continuity;
- pre/post-publication crash windows and no blind retry;
- passive submit/cancel, marketable fill, resting restart and session rollover;
- HGT and SGT linked-account routes, lot-size handling and BrokerEvidence convergence;
- Windows backup directory fsync behavior;
- archive integrity, readiness anchor and same-timestamp tuple completeness.

The full suite at P6-T015 contained **619 passing tests**; the matching GitHub Actions run
`35988483544` passed Python, workflow, conformance, static side-effect, deployment and TLC
jobs. Later Core freeze commits added a dedicated `core-v1-release` job and passed run
`36016234582`.

## 6. Protocol and evidence status

The Bridge umbrella contract retains calibrated wire versions:

```text
Discovery Contract 1
Command Protocol   0.1
Event Protocol     0.2
File Transport     1
```

`command_result` is control-plane evidence and cannot create broker lifecycle state.
Broker lifecycle mutation requires validated `BrokerEvidenceV1` from an authorized source.
The Guojin simulation mapper `qmt-guojin-sim-20260917-v1` is calibrated only for
`guojin_sim`; it is not automatically enabled for production Guojin or Galaxy.

## 7. Permanent verification

CI jobs:

- `test`: complete Python suite;
- `core-v1-release`: Core tests, dependency boundary and frozen release contract;
- `formal-verification`: workflow contract, finite conformance, schema drift, side-effect
  audit, standalone deployment consistency and every configured TLC model.

No safety invariant waiver is allowed. See [FORMAL_VERIFICATION.md](FORMAL_VERIFICATION.md).

## 8. Runtime data and migration

Runtime state lives outside Git under per-instance spool roots, normally
`D:\BigQMTData\spool\<instance_id>`. It can contain account-sensitive events, commands,
archives, checkpoints and databases. Migration must stop the writer, preserve consistency,
keep instances isolated and start QMT before Host. See
[DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md](DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md).

## 9. Current checkpoint

The repository is at a frozen Core v1 plus bounded QMT Extension baseline. Safe next work is
normally an Extension task. Any new broker/route or broader mutation authority requires a
new explicit workflow Gate; it is not inherited from prior calibration, instance discovery,
configuration or environment migration.
