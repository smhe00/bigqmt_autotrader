# Formal Verification Gate

Updated: 2026-09-25
Status: **MANDATORY PERMANENT GATE**

## 1. Scope

The project combines finite TLA+/TLC model checking, implementation-independent Python
conformance, JSON Schema drift checks, static side-effect auditing and runtime/fault/replay
tests. TLC proves the configured finite abstraction, not CPython, SQLite, NTFS, QMT or
broker infrastructure; those layers remain covered by executable tests and runtime Gates.

No safety-critical change may pass by weakening an invariant or omitting its model from CI.

## 2. Permanent models

| Model | Contract covered |
| --- | --- |
| `OrderFSM` | 14-state order lifecycle including UNKNOWN/RECONCILING/MANUAL_REVIEW |
| `SubmitProtocol` | durable submit/cancel, crash, ambiguity and at-most-once side effect |
| `LeaderLease` | competing writers, lease expiry and fencing |
| `EvidenceReplay` | duplicate/out-of-order evidence and monotonic facts |
| `PreSubmitRecovery` | durable pre-side-effect restart behavior |
| `RiskPrecedence` | deterministic Global→Account→Strategy→Security/Order fail-close |
| `BridgeCommandProtocol` | command publication, expiry, identity, crash and idempotency |
| `GuojinSimDispatchRecovery` | exact-absence recovery and no blind republish |
| `BridgeEventProtocol` | session/sequence/gap/resync and snapshot recovery |
| `BrokerEvidenceBoundary` | control-plane result cannot create broker lifecycle fact |
| `BrokerEvidenceContract` | identity, calibration, dedup, quantities and terminal conflicts |

Core v1 locks its required formal subset in `contracts/core/v1/formal_models.json`.

## 3. Executable conformance

- `verify_fsm_exhaustive.py`: frozen OMS transition relation.
- `verify_bridge_protocol_exhaustive.py`: command/event finite semantics.
- `verify_bridge_schema_contract.py`: implementation versus Bridge JSON Schema.
- `verify_broker_evidence_contract.py`: broker-neutral evidence reference model and schema.
- `verify_core_dependency_boundary.py`: Core cannot import adapter/Runtime code.
- `verify_core_v1_release.py`: public API, schema, inventory and formal release identity.
- `audit_side_effect_calls.py`: permitted broker mutation surfaces only.
- `build_qmt_deployments.py --check`: standalone QMT files match their generated source.
- `verify_workflow_contract.py`: active task/report/review handoff consistency.

The full Python suite supplies concrete quantity, SQLite transaction, Windows-specific,
mapper, fault, replay, archive and integration coverage outside the finite abstractions.

## 4. Broker evidence boundary

```text
command_result / submit return / cancel return != BrokerEvidenceV1
```

Only calibrated ORDER callback, DEAL callback, active ORDER query or active DEAL query may
produce lifecycle evidence. Unknown raw statuses, identity/quantity mismatch, unsupported
source/status pairs and semantic conflicts fail closed. Conflicting terminal facts enter
`MANUAL_REVIEW`; timestamps do not choose a winner.

BrokerEvidence v1 remains broker-neutral. The Guojin simulation mapper is separately
calibrated and PASS only for `guojin_sim`; production Guojin and Galaxy are not implicitly
authorized by the formal contract or discovery.

## 5. Side-effect boundary

Generic and Galaxy artifacts expose zero broker mutation call surface. The pinned
`guojin_sim` build `p5-simulation-calibration-8` contains bounded simulation-only mutation
logic. The separate
`p6-guojin-live-canary-7` Guojin artifact contains only its reviewed single-case canary
surface. Static and contract tests reject broader production authority.

## 6. CI toolchain

- Python: 3.12
- Java: Temurin 17
- `tla2tools.jar`: v1.7.4
- SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`

GitHub Actions runs `test`, `core-v1-release` and `formal-verification`. Core release
`core-v1.0.0` was frozen after all three passed on commit
`068212da517d21603885af7e52f3abb6236dd2f4`, run `36016234582`.

## 7. PASS criteria

An exact candidate requires:

- full Python suite green;
- Core-only tests and frozen Core release contract green;
- every conformance/schema/dependency/workflow check green;
- broker side-effect and standalone deployment audits green;
- every configured TLC model green with no unresolved counterexample;
- no unreviewed authority expansion and no invariant waiver.

Historical model or Gate results remain in dated documents. Current status is summarized in
[PROJECT_STATUS.md](PROJECT_STATUS.md); workflow authority comes only from
`workflow/control/WORKFLOW_STATE.yaml`.
