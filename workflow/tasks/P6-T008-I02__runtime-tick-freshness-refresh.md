---
workflow_schema: 1
phase: P6
task_id: P6-T008
iteration: I02
task_key: P6-T008-I02
state: CHANGES_REQUIRED
owner: agent
audit_base_commit: 86103970284d5314ac3434b7aba1d72f8d442afc
expected_report: workflow/reports/P6-T008-I02__implementation-report.md
expected_review: workflow/reviews/P6-T008-I02__architect-review.md
---

# P6-T008-I02 — Runtime Tick Freshness Refresh

## Objective

Close one prerequisite only: a Host REQUEST_SNAPSHOT against guojin_sim can force a new read-only bounded tick poll and publish fresh exact-symbol instrument_tick_capabilities evidence during the running session.

## Design constraint

Do not add a new trading/mutation command. Reuse REQUEST_SNAPSHOT and add an optional read-only bridge hook for simulation tick refresh.

Preferred behavior:

REQUEST_SNAPSHOT -> read_account_capabilities -> read_snapshot -> force bounded get_full_tick refresh -> publish instrument_tick_capabilities -> flush_transport -> SNAPSHOT_EMITTED

## Required semantics

1. previously observed symbols must be polled again;
2. exact-symbol mismatch remains rejected;
3. refreshed record updates local observation timestamp;
4. broker-provided tick_time remains preserved and authoritative for freshness;
5. all polling is read-only;
6. failure to refresh tick must not mutate broker state;
7. no change to submit/cancel authority;
8. bounded candidate set only.

## Regression coverage

- first poll stores tick A;
- later REQUEST_SNAPSHOT supplies newer tick B for the same symbol;
- published evidence contains B, not A;
- local observation timestamp advances;
- exact-symbol mismatch does not become valid evidence;
- unavailable/exceptional get_full_tick stays fail-closed/read-only;
- generated guojin_sim artifact contains the refresh hook;
- Galaxy/generic mutation surfaces remain unchanged.

## Scope lock

Only runtime tick freshness refresh. Do not rerun HGT mutation in I02. After PASS, use I03 for the HGT linked-route fill rerun.

## Verification

Run full pytest, deployment build check, side-effect audit and permanent formal CI.

## Handoff

Update the matching implementation report and return REVIEW_READY.
