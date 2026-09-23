---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I03
task_key: P6-T008-I03
reply_to: workflow/tasks/P6-T008-I03__rerun-hgt-linked-fill-fresh-tick.md
status: REVIEW_READY
owner: agent
review_target: workflow/reviews/P6-T008-I03__architect-review.md
---

# P6-T008-I03 Implementation Report

## Result
- Status: `REVIEW_READY`
- Runtime time: 2026-09-23 09:05--09:39 Asia/Shanghai
- Runtime result: PASS candidate. One normal-OMS `00700.HGT` simulation order used current build-8 tick evidence and converged to broker-evidence-backed `FILLED` on the linked HUGANGTONG route.
- Implementation commits: `f788ab4` (build-8 Host OMS authorization) and `f57349c` (explicit HGT Risk support).
- Final implementation commit: `f57349c`.

## Deployment / fresh tick
- Reloaded manifest: `guojin_sim`, `SIMULATION_CALIBRATION`, `simulation_only=true`, build `p5-simulation-calibration-8`, session `2473e2b97ee344fca3bdddee80fd3f85`, pinned STOCK fingerprint `sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702`.
- The initial Host preflight found its OMS build gate still pinned to build-7. Direct authorization returned false, so the Host was stopped before any mutation. Commit `f788ab4` updates only the authorized simulation build and explicitly tests that retired build-7 remains fail-closed.
- Host then started with `oms_evidence_enabled=true`, one leader, healthy replay/read model, zero unresolved `UNKNOWN`/`MANUAL_REVIEW`, and zero semantic quarantine.
- Read-only `REQUEST_SNAPSHOT` command `5c1a97cd715a41449a97b0a86d365128` produced sequence 101 from `snapshot_tick_refresh` at 09:30:53.377. `00700.HGT` requested/reported symbols matched exactly; broker tick time was 09:30:52, local callback time 09:30:53.377, and last price was `451.8`.
- Current account capability retained `HUGANGTONG` DETECTED with route fingerprint `sha256:e475f1a12b1bede72aafada79c0d876e3549a33985b6ce0d3df6baca9fa6c43d`. Its 100 sellable `00700.HGT` shares were route metadata under the pinned STOCK OMS identity, never a second authority.

## HGT OMS submit
- First intent `p6t008-hgt-sell-00700-20260923` was deterministically rejected pre-broker with `RISK_INVALID_ORDER`, because Risk still allowed only `.SH/.SZ/.BJ`. It created no QMT command, dispatch, broker token, or side effect (`submit_call_started=0`).
- Per the task's clean-rejection retry allowance and the user's instruction to repair adjacent blockers in this report, commit `f57349c` adds only `.HGT` to the Risk suffix allowlist. Ordinary `.HK` remains unsupported; the regression proves an explicitly strategy-allowlisted `.HGT` order can pass.
- Successful intent: `p6t008-hgt-sell-00700-20260923-02`, `SELL 100 00700.HGT LIMIT 440.0`, below the current 451.8 quote and inside the 10% deterministic reference-price gate.
- Risk: accepted / `RISK_OK`, rule `p6t008-hgt-fill-v2`, snapshot hash `sha256:a88e4ef0c32ae774d7bfe9ec73dc4db6fecc5d8b5364bb3fd9dc31012bfe0052`.
- Immutable dispatch: command `simoms-da6327d5dc4fb8ccd89ed83fbd928370481e0a6c61032e97`, token `BQ5748b14de4be9df0570c`, frame/command digest `sha256:eec99e5c9f30840b348aba1c5fc7dd80ae5a98d7c8c73c8674fb4b3ad6cc0e51`, expected current session pinned in the frame, final dispatch state `OBSERVED_PROCESSED`.

## Linked-route BrokerEvidence
- `command_result` sequence 189 was `SIMULATION_SUBMIT_CALL_RETURNED`, `live_side_effect=true`; it stayed control-plane evidence and left OMS reconciliation unchanged.
- ORDER callback sequence 191: broker order `1`, order ref `446149875865646907`, exact token, raw `50/51`, filled 0/100. `ORDER_ACCEPTED` advanced `RECONCILING -> ACKNOWLEDGED`.
- ORDER callback sequence 192: same identities, raw `56/51`, filled 100/100. `FULL_FILL` advanced `ACKNOWLEDGED -> FILLED` exactly once.
- DEAL callback sequence 194: broker order `1`, trade `14435`, exact token/order ref, 100 shares at `440.0`. Its same cumulative FULL_FILL was `DUPLICATE_IGNORED`; fill stayed 100.
- Post-fill read-only snapshot sequence 210 contained one HUGANGTONG order and deal with zero query errors. Active ORDER and DEAL query evidence carried `route_account_type=HUGANGTONG` and route fingerprint `sha256:e475...6c43d`; both were `SEMANTIC_DUPLICATE`, leaving the pinned STOCK fingerprint and cumulative fill unchanged.
- Final durable OMS state: `FILLED`, broker order `1`, filled quantity `100`, `submit_call_started=1`, `cancel_call_started=0`.

## Idempotency / identity
- Lifecycle: `CREATED -> RISK_ACCEPTED -> SUBMITTING -> UNKNOWN -> RECONCILING -> ACKNOWLEDGED -> FILLED`.
- There is one successful submit dispatch and one broker order identity. No republish, blind retry, overfill, terminal conflict, unresolved UNKNOWN, or manual review occurred.
- The clean first Risk rejection had no command/side effect. Callback DEAL and active-query ORDER/DEAL facts did not apply a second fill.
- Pinned OMS identity remained the manifest STOCK fingerprint throughout; HUGANGTONG account type/fingerprint remained evidence metadata only.

## Mutation accounting
```text
OMS intents evaluated = 2
clean pre-broker Risk rejections = 1
guojin_sim broker submits = 1
guojin_sim cancels = 0
read-only REQUEST_SNAPSHOT commands = 2
production guojin mutations = 0
galaxy mutations = 0
generic mutations = 0
UNKNOWN blind retries = 0
```

## Verification
- Focused build-8 OMS authorization/execution regressions: 36 passed.
- Focused Risk + OMS regressions after HGT allowlist: 47 passed.
- Full suite: 459 passed in 11.01 s.
- FSM finite conformance: PASS, 196 pairs.
- Bridge protocol: PASS, 4608 transitions plus spool checks.
- Bridge schema drift: PASS.
- Broker Evidence finite contract: PASS, 7200 cases.
- Side-effect surface audit: PASS.
- QMT deployment generator consistency: PASS.
- Workflow contract is run again with the final handoff.

## Safety
- Only `guojin_sim` received one broker submit. Production Guojin, Galaxy and generic command roots were untouched.
- No cancel was needed because the order filled immediately.
- The Host remains pinned to the current build-8/session with OMS evidence enabled and a healthy read model.

## Handoff
Ready for standard Agent -> Architect review of the combined adjacent fixes and successful runtime fill.